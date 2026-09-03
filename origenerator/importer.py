import json
import logging
import os
import shutil
import subprocess
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from origenerator.comfy_graph import (
    clip_prompt_nodes,
    conditioning_node,
    follow,
    graph_model_params,
    input_image_name,
)
from origenerator.db import Database
from origenerator.gallery import parse_params, row_output_files
from origenerator.media import media_type_from_filename, sibling_of_type
from origenerator.thumbnail import generate_thumbnail
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)

# Windows spawns a visible console window for each child process unless told not
# to, so probing a batch of imported videos would flash one window per file.
# CREATE_NO_WINDOW suppresses it; it's absent (and this is a no-op 0) elsewhere.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _workflow_name_by_filename_prefix() -> dict[str, str]:
    """Map each workflow's output-filename prefix to its name, from the registry.

    ComfyUI names outputs ``<prefix>_NNNNN_.<ext>`` where ``<prefix>`` is the
    last path segment of the workflow's ``filename_prefix`` (e.g. the
    ``video/wan22_i2v`` prefix yields files named ``wan22_i2v_00001_.mp4``).
    """
    mapping: dict[str, str] = {}
    for name, wf in WORKFLOW_REGISTRY.items():
        prefix = wf.default_params().get("filename_prefix", "")
        base = prefix.rsplit("/", 1)[-1]
        if base:
            mapping[base] = name
    return mapping


def infer_workflow_name(filename: str) -> str | None:
    """Infer a workflow name from a ComfyUI output filename by its prefix.

    Returns the registered workflow whose output prefix the filename starts
    with (longest match wins), or ``None`` when nothing matches.
    """
    best_prefix = ""
    best_name = None
    for prefix, name in _workflow_name_by_filename_prefix().items():
        if filename.startswith(prefix) and len(prefix) > len(best_prefix):
            best_prefix = prefix
            best_name = name
    return best_name


def import_comfyui_output(output_dir: Path, db: Database, thumb_dir: Path) -> int:
    imported = 0
    existing = _get_existing_filenames(db)

    for dirpath, _, filenames in os.walk(output_dir):
        for fname in sorted(filenames):
            fpath = Path(dirpath) / fname
            output_type = media_type_from_filename(fname)
            if output_type is None:
                continue
            # A video with a metadata image beside it is represented (and made
            # playable) by that image's entry, so skip the bare video file.
            if output_type == "video" and sibling_of_type(fpath, "image") is not None:
                continue
            # An image beside a video is that video's metadata/preview sidecar
            # (VHS_VideoCombine writes one per clip): its entry should play the
            # video, not show the still frame.
            play_path = fpath
            if output_type == "image":
                sibling_video = sibling_of_type(fpath, "video")
                if sibling_video is not None:
                    play_path = sibling_video

            rel_path = play_path.relative_to(output_dir).as_posix()
            if rel_path in existing:
                continue

            metadata = _extract_metadata(fpath, fpath.suffix.lower())
            prompt_id = str(uuid.uuid4())

            thumb_path = None
            try:
                thumb_path = str(
                    generate_thumbnail(fpath, output_type, thumb_dir, name=prompt_id)
                )
            except Exception as e:
                logger.warning("Thumbnail failed for %s: %s", fpath, e)

            mtime = datetime.fromtimestamp(fpath.stat().st_mtime, tz=timezone.utc)

            db.insert_generation(
                prompt_id=prompt_id,
                workflow_name=metadata.get("workflow_name", "unknown"),
                workflow_version=metadata.get("workflow_version", "imported"),
                positive_prompt=metadata.get("positive_prompt"),
                negative_prompt=metadata.get("negative_prompt"),
                seed=metadata.get("seed"),
                params_json=json.dumps(_build_params_json(metadata)),
                workflow_json=json.dumps(metadata.get("prompt_data", {})),
                source="imported",
            )
            db.update_generation(
                prompt_id,
                status="completed",
                output_files=json.dumps([_output_entry(play_path, output_dir)]),
                thumbnail_path=thumb_path,
                completed_at=mtime.isoformat(),
            )
            existing.add(rel_path)
            imported += 1

    return imported


def _output_entry(path: Path, output_dir: Path) -> dict:
    subfolder = path.parent.relative_to(output_dir).as_posix()
    if subfolder == ".":
        subfolder = ""
    return {"filename": path.name, "subfolder": subfolder, "type": "output"}


def merge_video_sidecar_rows(db: Database) -> int:
    """Consolidate already-imported image sidecars with the video they preview.

    Older imports created a separate gallery row for the metadata PNG that
    VHS_VideoCombine saves beside each video. This repoints each such image row
    at its sibling video — so it plays, keeping the prompt/seed it carries — and
    deletes the now-redundant bare video row. Returns the number consolidated.
    """
    rows = db.list_generations()
    video_by_key: dict[tuple[str, str], dict] = {}
    for row in rows:
        files = row_output_files(row)
        if files and media_type_from_filename(files[0].get("filename", "")) == "video":
            video_by_key[_sidecar_key(files[0])] = row

    merged = 0
    for row in rows:
        files = row_output_files(row)
        if not files or media_type_from_filename(files[0].get("filename", "")) != "image":
            continue
        video = video_by_key.pop(_sidecar_key(files[0]), None)
        if video is None:
            continue
        db.update_generation(row["prompt_id"], output_files=video["output_files"])
        db.delete_generation(video["prompt_id"])
        merged += 1
    return merged


def _sidecar_key(file_entry: dict) -> tuple[str, str]:
    return (file_entry.get("subfolder", ""), Path(file_entry.get("filename", "")).stem)


def backfill_shared_thumbnails(db: Database, output_dir: Path, thumb_dir: Path) -> int:
    """Re-render thumbnails an old naming collision left wrong or missing.

    Thumbnails were once named after the source file's stem, so two outputs that
    shared a stem — ComfyUI's default ``ComfyUI_00001_.png`` beside
    ``video/ComfyUI_00001_.mp4`` — wrote to one file, the later import
    overwriting the earlier; the losing row then displayed the winner's frame.
    Each row whose thumbnail file is shared by another row, or has since gone
    missing (e.g. trashed when its stem-twin was deleted), is re-rendered from
    its own output under a name keyed by its unique ``prompt_id``. Returns how
    many rows were repaired. Idempotent: once every thumbnail is uniquely owned
    and present, a re-run touches nothing.
    """
    rows = db.list_generations()
    owners = Counter(r["thumbnail_path"] for r in rows if r.get("thumbnail_path"))
    repaired = 0
    for row in rows:
        thumb = row.get("thumbnail_path")
        if not thumb:
            continue
        if owners[thumb] == 1 and Path(thumb).exists():
            continue  # uniquely owned and present — already correct
        fresh = _render_row_thumbnail(row, output_dir, thumb_dir)
        if fresh is not None:
            db.update_generation(row["prompt_id"], thumbnail_path=str(fresh))
            repaired += 1
    return repaired


def _render_row_thumbnail(row: dict, output_dir: Path, thumb_dir: Path) -> Path | None:
    """A fresh thumbnail for ``row`` from its own output, keyed by its prompt_id.

    Returns the new path, or ``None`` when the row has no renderable output file
    on disk to draw from (so the caller leaves the existing reference alone).
    """
    files = row_output_files(row)
    if not files:
        return None
    first = files[0]
    media = media_type_from_filename(first.get("filename", ""))
    if media is None:
        return None
    source = output_dir / first.get("subfolder", "") / first.get("filename", "")
    if not source.exists():
        return None
    try:
        return generate_thumbnail(source, media, thumb_dir, name=row["prompt_id"])
    except Exception as e:
        logger.warning("Thumbnail repair failed for %s: %s", source, e)
        return None


def backfill_unknown_workflows(db: Database) -> int:
    """Relabel rows imported as workflow 'unknown' (before filename inference
    existed) whose output filename matches a known workflow's prefix.

    Returns the number of rows updated. Rows that match nothing are left as
    'unknown', and already-identified rows are never touched.
    """
    updated = 0
    for row in db.list_generations():
        if row.get("workflow_name") != "unknown":
            continue
        files_json = row.get("output_files")
        if not files_json:
            continue
        try:
            files = json.loads(files_json)
        except json.JSONDecodeError:
            continue
        if not files:
            continue
        name = infer_workflow_name(files[0].get("filename", ""))
        if name:
            db.set_workflow_name(row["prompt_id"], name)
            updated += 1
    return updated


def backfill_model_and_lora_params(db: Database) -> int:
    """Record the base model and LoRA on imports that predate reading them.

    Early imports stored the embedded graph but not the model filenames it loads,
    so those rows lack the params the gallery's model and LoRA folders group by —
    they collapse under "(unknown model)" / "(no LoRA)". This re-reads each row's
    stored graph and folds any model file it finds (SDXL checkpoint, Flux GGUF
    UNET, WAN high/low UNET + LoRA) into ``params_json``, filling only keys the
    row is missing so a row that already carries them (or whose graph has none)
    is left untouched. Returns how many rows were filled. Idempotent.
    """
    updated = 0
    for row in db.list_generations():
        graph = _as_graph(row.get("workflow_json") or "")
        found = graph_model_params(graph) if graph else {}
        params = parse_params(row.get("params_json"))
        missing = {k: v for k, v in found.items() if k not in params}
        if not missing:
            continue
        params.update(missing)
        db.set_params_json(row["prompt_id"], json.dumps(params))
        updated += 1
    return updated


def backfill_input_image(db: Database) -> int:
    """Record the source image on image-to-video imports that predate reading it.

    Early video imports stored the embedded graph but not the ``LoadImage``
    filename it starts from, so i2v/flf2v rows couldn't link back to the gallery
    image they were animated from. This re-reads each row's stored graph and fills
    ``input_image`` only when the row lacks it and the graph names one — a row that
    already carries an input image (a re-roll's fresh start frame) or whose graph
    loads none is left untouched. Returns how many rows were filled. Idempotent.
    """
    updated = 0
    for row in db.list_generations():
        params = parse_params(row.get("params_json"))
        if params.get("input_image"):
            continue
        graph = _as_graph(row.get("workflow_json") or "")
        name = input_image_name(graph) if graph else None
        if not name:
            continue
        params["input_image"] = name
        db.set_params_json(row["prompt_id"], json.dumps(params))
        updated += 1
    return updated


def _get_existing_filenames(db: Database) -> set[str]:
    result = set()
    for row in db.list_generations():
        files_json = row.get("output_files")
        if files_json:
            try:
                for f in json.loads(files_json):
                    sub = f.get("subfolder", "")
                    name = f.get("filename", "")
                    if sub:
                        result.add(f"{sub}/{name}")
                    else:
                        result.add(name)
            except (json.JSONDecodeError, KeyError):
                pass
    return result


def _as_graph(text: str) -> dict:
    """Decode a ComfyUI prompt graph, tolerating double-JSON-encoding.

    Native ``SaveVideo`` and PNG chunks store the graph as a JSON object;
    ``VHS_VideoCombine`` stores it as a JSON *string* of that object. Decode
    until we reach the dict (or give up).
    """
    try:
        data = json.loads(text)
        if isinstance(data, str):
            data = json.loads(data)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _video_prompt_graph(fpath: Path) -> dict:
    """Read ComfyUI's embedded prompt graph from a video container via ffprobe.

    Returns {} when ffprobe is unavailable, the ``prompt`` tag is absent, or
    anything goes wrong — callers fall back to filename inference.
    """
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {}
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", str(fpath)],
            capture_output=True, text=True, timeout=30, creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    tags = (_as_graph(proc.stdout).get("format", {}) or {}).get("tags", {})
    prompt = tags.get("prompt")
    return _as_graph(prompt) if prompt else {}


def _read_prompt_graph(fpath: Path, suffix: str) -> dict:
    """Return the embedded ComfyUI prompt graph for an output file, or {}.

    Images carry it in the PNG ``prompt`` text chunk; videos carry it in the
    container metadata.
    """
    if suffix == ".png":
        try:
            prompt_str = Image.open(fpath).info.get("prompt")
        except Exception:
            return {}
        return _as_graph(prompt_str) if prompt_str else {}
    if media_type_from_filename(fpath.name) == "video":
        return _video_prompt_graph(fpath)
    return {}


def _prompt_texts(graph: dict) -> tuple[str | None, str | None]:
    """The positive and negative prompt a graph was run with, or ``None`` each.

    Located structurally for the Wan workflows and by node title otherwise (see
    :func:`origenerator.comfy_graph.clip_prompt_nodes`).
    """
    def text_of(node):
        if node and isinstance(node.get("inputs", {}).get("text"), str):
            return node["inputs"]["text"]
        return None

    positive, negative = clip_prompt_nodes(graph)
    return text_of(positive), text_of(negative)


def _conditioning_params(graph: dict) -> dict:
    """The dimensions the conditioning node was built at: width, height, frames."""
    node = conditioning_node(graph)
    if not node:
        return {}
    inputs = node.get("inputs", {})
    return {
        dst: inputs[src]
        for src, dst in (("width", "width"), ("height", "height"),
                         ("length", "frame_count"))
        if isinstance(inputs.get(src), int)
    }


def _input_image_params(graph: dict) -> dict:
    """The image an image-to-video graph animated, when it names one."""
    name = input_image_name(graph)
    return {} if name is None else {"input_image": name}


def _sampler_settings(graph: dict) -> tuple[int | None, dict]:
    """The seed the run used, and every scalar its samplers were given.

    One pass over the graph, because the two sampler kinds decide the seed
    together: a plain KSampler's seed wins outright, while a KSamplerAdvanced's
    is taken only when nothing has claimed the seed yet or when this is the
    noise-adding (stage-1) sampler.
    """
    skip = {id(node) for node in _refine_passes(graph)}
    seed = None
    params: dict = {}
    for node in graph.values():
        class_type = node.get("class_type", "")
        inputs = node.get("inputs", {})

        if class_type == "KSampler":
            if id(node) in skip:
                continue
            if isinstance(inputs.get("seed"), int):
                seed = inputs["seed"]
            params.update(_scalars(inputs))

        if class_type == "KSamplerAdvanced":
            noise_seed = inputs.get("noise_seed")
            if isinstance(noise_seed, int) and (
                    seed is None or inputs.get("add_noise") == "enable"):
                seed = noise_seed
            params.update(_scalars(inputs))
    return seed, params


def _refine_passes(graph: dict) -> list[dict]:
    """The KSamplers whose settings describe a refinement rather than the recipe.

    The SDXL workflows end in a second, low-denoise KSampler over a re-encoded
    image (the enhance pass), recognized by sampling a VAEEncode'd latent. Its
    steps/denoise are the refinement's, so they are skipped — but only when a
    base sampler exists too, since a graph that is nothing BUT a refinement has
    no other settings to report.
    """
    def is_refinement(node: dict) -> bool:
        source = follow(graph, node.get("inputs", {}).get("latent_image"))
        return bool(source) and source.get("class_type") == "VAEEncode"

    samplers = [n for n in graph.values() if n.get("class_type") == "KSampler"]
    refinements = [n for n in samplers if is_refinement(n)]
    return refinements if len(refinements) < len(samplers) else []


def _scalars(inputs: dict) -> dict:
    """The plainly-valued inputs of a node — the ones worth recording as params."""
    return {k: v for k, v in inputs.items() if isinstance(v, (int, float, str, bool))}


# Which registered workflow a graph's node classes name, MOST SPECIFIC FIRST.
# The order is load-bearing and cannot come from the registry, whose own order
# runs the other way (sdxl_t2i first): a graph can satisfy more than one entry —
# an flf2v graph also carries the i2v conditioning, a Flux one can also load a
# checkpoint — and the first match wins. Nor can it be derived from the
# signatures, since flf2v and i2v are each one node class and neither is a
# superset of the other; what orders them is that an flf2v graph contains both.
#
# Each entry is a workflow name and the node-class sets that identify it: any
# one set being wholly present is enough. tests/test_importer.py holds every
# case with the losers named; tests/test_workflows.py holds these names against
# the registry, and holds what every registered workflow's own graph reads as.
_GRAPH_SIGNATURES = (
    ("wan22_flf2v_loop", (frozenset({"WanFirstLastFrameToVideo"}),)),
    ("wan22_i2v", (frozenset({"WanImageToVideo"}),)),
    # A Wan/Hunyuan video latent saved as a still image: text-to-image.
    ("wan22_t2i", (frozenset({"EmptyHunyuanLatentVideo", "SaveImage"}),)),
    # Flux samples off a GGUF UNET with dual (clip_l + t5xxl) text encoders and a
    # FluxGuidance node — none of which the other workflows use.
    ("flux_t2i_upscaled", (frozenset({"FluxGuidance"}),
                           frozenset({"UnetLoaderGGUF", "DualCLIPLoader"}))),
    ("sdxl_t2i", (frozenset({"CheckpointLoaderSimple"}),)),
)


def _workflow_from_nodes(graph: dict) -> str | None:
    """Which registered workflow built this graph, from its node classes.

    ``None`` when nothing matches, which leaves the filename's guess standing.
    """
    node_types = {n.get("class_type") for n in graph.values()}
    return next(
        (name for name, signatures in _GRAPH_SIGNATURES
         if any(signature <= node_types for signature in signatures)),
        None,
    )


def _extract_metadata(fpath: Path, suffix: str) -> dict:
    """What an output file says about the run that made it.

    Seven readings of one embedded graph, each its own function above: the
    prompts, the conditioning dimensions, the input image, the sampler settings
    and the seed, the model files, and which workflow the node classes name. The
    filename's prefix is the first guess at that last one and the graph overrules
    it, because a file can be renamed and a prefix reused.
    """
    result: dict = {
        "workflow_name": infer_workflow_name(fpath.name) or "unknown",
        "workflow_version": "imported",
        "positive_prompt": None,
        "negative_prompt": None,
        "seed": None,
        "params": {},
        "prompt_data": {},
    }

    graph = _read_prompt_graph(fpath, suffix)
    if not graph:
        return result

    seed, sampler_params = _sampler_settings(graph)
    params = {}
    params.update(_conditioning_params(graph))
    params.update(_input_image_params(graph))
    params.update(sampler_params)
    # Whichever model files the graph loads (SDXL checkpoint, Flux GGUF UNET,
    # WAN dual-noise high/low UNET + LoRA), so the gallery can nest the import
    # by model the same way it does a run generated here.
    params.update(graph_model_params(graph))

    positive, negative = _prompt_texts(graph)
    result.update(
        prompt_data=graph,
        positive_prompt=positive,
        negative_prompt=negative,
        seed=seed,
        params=params,
        workflow_name=_workflow_from_nodes(graph) or result["workflow_name"],
    )
    return result


def _build_params_json(metadata: dict) -> dict:
    params = dict(metadata.get("params", {}))
    if metadata.get("positive_prompt") is not None:
        params["positive_prompt"] = metadata["positive_prompt"]
    if metadata.get("negative_prompt") is not None:
        params["negative_prompt"] = metadata["negative_prompt"]
    if metadata.get("seed") is not None:
        params["seed"] = metadata["seed"]
    return params
