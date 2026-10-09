from __future__ import annotations

import functools
import json
import logging
import os
import shutil
import subprocess
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from app_support.subprocess_utils import hidden_subprocess_kwargs
from PIL import Image

from origenerator.comfy_graph import (
    clip_prompt_nodes,
    conditioning_node,
    empty_latent,
    follow,
    graph_model_params,
    input_image_name,
    sound_params,
)
from origenerator.db import Database
from origenerator.gallery import parse_params, row_output_files
from origenerator.gallery.sides import orientation_of_size
from origenerator.gallery_contract import LANES
from origenerator.generation_state import GenerationSource, GenerationStatus, source_of
from origenerator.media import MediaType, media_type_from_filename, sibling_of_type
from origenerator.thumbnail import generate_thumbnail
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.base import soundless_copies_of

logger = logging.getLogger(__name__)



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
            if (output_type == MediaType.VIDEO
                    and sibling_of_type(fpath, MediaType.IMAGE) is not None):
                continue
            # An image beside a video is that video's metadata/preview sidecar
            # (VHS_VideoCombine writes one per clip): its entry should play the
            # video, not show the still frame.
            play_path = fpath
            if output_type == MediaType.IMAGE:
                sibling_video = sibling_of_type(fpath, MediaType.VIDEO)
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

            mtime = datetime.fromtimestamp(fpath.stat().st_mtime, tz=UTC)

            db.insert_generation(
                prompt_id=prompt_id,
                workflow_name=metadata.get("workflow_name", "unknown"),
                workflow_version=metadata.get("workflow_version", "imported"),
                positive_prompt=metadata.get("positive_prompt"),
                negative_prompt=metadata.get("negative_prompt"),
                seed=metadata.get("seed"),
                params_json=json.dumps(metadata.get("params", {})),
                workflow_json=json.dumps(metadata.get("prompt_data", {})),
                source=GenerationSource.IMPORTED,
            )
            db.update_generation(
                prompt_id,
                status=GenerationStatus.COMPLETED,
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
    rows = db.list_generations()
    video_by_key: dict[tuple[str, str], dict] = {}
    for row in rows:
        files = row_output_files(row)
        if files and media_type_from_filename(files[0].get("filename", "")) == MediaType.VIDEO:
            video_by_key[_sidecar_key(files[0])] = row

    merged = 0
    for row in rows:
        files = row_output_files(row)
        if (not files
                or media_type_from_filename(files[0].get("filename", "")) != MediaType.IMAGE):
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


def merge_soundless_copy_rows(db: Database, *, send_down) -> int:
    rows = db.list_generations()
    video_by_copy_key: dict[tuple[str, str], dict] = {}
    for row in rows:
        files = row_output_files(row)
        if row.get("source") != GenerationSource.IMPORTED and files:
            for copy in soundless_copies_of(files[:1]):
                video_by_copy_key[_sidecar_key(copy)] = row

    merged = 0
    for row in rows:
        files = row_output_files(row)
        if row.get("source") != GenerationSource.IMPORTED or len(files) != 1:
            continue
        video = video_by_copy_key.get(_sidecar_key(files[0]))
        if video is None:
            continue
        try:
            for lane in _lanes_its_video_is_owed(row, video):
                send_down(video, lane)
        except Exception:
            logger.warning("Could not send %s where its soundless copy had gone; "
                           "the copy waits for the next launch",
                           video["prompt_id"], exc_info=True)
            continue
        _fold_soundless_copy(db, row, video, rows)
        merged += 1
    return merged


def _lanes_its_video_is_owed(copy: dict, video: dict) -> list[str]:
    return [lane for lane, stamps in LANES.items()
            if copy.get(stamps["sent"])
            and not video.get(stamps["sent"]) and not video.get(stamps["unsent"])]


def _fold_soundless_copy(db: Database, copy: dict, video: dict, rows: list[dict]) -> None:
    listed = row_output_files(video)
    listed_names = {f.get("filename") for f in listed}
    unlisted = [c for c in soundless_copies_of(listed[:1]) if c["filename"] not in listed_names]
    db.update_generation(video["prompt_id"], output_files=json.dumps(listed + unlisted))
    if copy.get("starred") and not video.get("starred"):
        db.set_generation_favorite(video["prompt_id"], True)
    for combined in rows:
        if combined.get("recipe_video_id") == copy["prompt_id"]:
            db.set_recipe_source(combined["prompt_id"], category=combined.get("recipe_category"),
                                 video_prompt_id=video["prompt_id"])
    db.delete_generation(copy["prompt_id"])


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


def backfill_import_params(db: Database, output_dir: Path) -> int:
    """Give every import the settings its own file states and its row is
    missing — the size it was made at, what it was told to avoid, the models it
    loaded, the image it started from, the sound it was scored with — read off
    its stored graph, and its size off the picture itself where the graph gives
    none.

    An import records only what the reading of a file knew to look for on the
    day it landed, and everything it missed then comes from the workflow's
    defaults wherever the app shows that picture's configuration: a portrait
    import read before sizes were read offered a landscape re-roll. So the
    reading is run again, filling only keys the row lacks — what the app
    generated itself is already complete, and a re-roll's own edits (a fresh
    start frame) are never clobbered. Returns how many rows were filled.
    Idempotent.
    """
    updated = 0
    for row in db.list_generations():
        if source_of(row) != GenerationSource.IMPORTED:
            continue
        params = parse_params(row.get("params_json"))
        stated = _graph_params(graph_from_text(row.get("workflow_json") or ""))
        if "width" not in params and "width" not in stated:
            stated.update(_size_from_its_own_file(_first_output_path(row, output_dir),
                                    row.get("workflow_name") or ""))
        missing = {k: v for k, v in stated.items() if k not in params}
        if not missing:
            continue
        db.set_params_json(row["prompt_id"], json.dumps({**params, **missing}))
        updated += 1
    return updated


def backfill_imported_video_seeds(db: Database) -> int:
    updated = 0
    for row in db.list_generations():
        params = parse_params(row.get("params_json"))
        if row.get("source") != GenerationSource.IMPORTED or "noise_seed" not in params:
            continue
        graph = graph_from_text(row.get("workflow_json") or "")
        seed = _sampler_settings(graph)[0] if graph else None
        if seed is None or params["noise_seed"] == seed:
            continue
        params["noise_seed"] = seed
        db.set_params_json(row["prompt_id"], json.dumps(params))
        updated += 1
    return updated


def _first_output_path(row: dict, output_dir: Path) -> Path:
    files = row_output_files(row)
    first = files[0] if files else {}
    return output_dir / first.get("subfolder", "") / first.get("filename", "")


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


def graph_from_text(text: str) -> dict:
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


def _probe_video(fpath: Path) -> dict:
    """ffprobe's account of a video container -- its ``format`` (the tags
    ComfyUI embeds its graph in) and its ``streams`` -- or {} when ffprobe is
    unavailable or anything goes wrong."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {}
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(fpath)],
            capture_output=True, text=True, timeout=30, **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    return graph_from_text(proc.stdout)


def _video_prompt_graph(fpath: Path) -> dict:
    """Read ComfyUI's embedded prompt graph from a video container, or {} --
    callers then fall back to filename inference."""
    tags = (_probe_video(fpath).get("format", {}) or {}).get("tags", {})
    prompt = tags.get("prompt")
    return graph_from_text(prompt) if prompt else {}


def _media_size(fpath: Path) -> tuple[int, int] | None:
    if media_type_from_filename(fpath.name) == MediaType.VIDEO:
        frames = next((stream for stream in _probe_video(fpath).get("streams", [])
                       if stream.get("codec_type") == "video"), {})
        width, height = frames.get("width"), frames.get("height")
        return (width, height) if isinstance(width, int) and isinstance(height, int) else None
    try:
        with Image.open(fpath) as image:
            return image.size
    except (OSError, ValueError):
        return None


def graph_in_file(fpath: Path, suffix: str) -> dict:
    """Return the embedded ComfyUI prompt graph for an output file, or {}.

    Images carry it in the PNG ``prompt`` text chunk; videos carry it in the
    container metadata.
    """
    if suffix == ".png":
        try:
            prompt_str = Image.open(fpath).info.get("prompt")
        except Exception:
            return {}
        return graph_from_text(prompt_str) if prompt_str else {}
    if media_type_from_filename(fpath.name) == MediaType.VIDEO:
        return _video_prompt_graph(fpath)
    return {}


def _prompt_texts(graph: dict) -> tuple[str | None, str | None]:
    """The positive and negative prompt a graph was run with, or ``None`` each
    (located by :func:`origenerator.comfy_graph.clip_prompt_nodes`)."""
    def text_of(node):
        if node and isinstance(node.get("inputs", {}).get("text"), str):
            return node["inputs"]["text"]
        return None

    positive, negative = clip_prompt_nodes(graph)
    return text_of(positive), text_of(negative)


def _size_params(graph: dict) -> dict:
    conditioning = conditioning_node(graph)
    if conditioning is not None:
        inputs = conditioning.get("inputs", {})
        return {
            dst: inputs[src]
            for src, dst in (("width", "width"), ("height", "height"),
                             ("length", "frame_count"))
            if isinstance(inputs.get(src), int)
        }
    latent = empty_latent(graph)
    return {} if latent is None else _scalars(latent["inputs"])


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
    if seed is not None and "noise_seed" in params:
        params["noise_seed"] = seed
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


@functools.cache
def _own_graph_reads_as(name: str) -> str | None:
    """What the chain reads a registered workflow's own default graph as."""
    workflow = WORKFLOW_REGISTRY[name]
    return _workflow_from_nodes(workflow.build_api_payload(dict(workflow.default_params())))


def _reconciled(filename_guess: str, graph_read: str | None) -> str:
    """The workflow name the two witnesses agree on.

    The graph overrules the filename -- a file can be renamed and a prefix
    reused -- except where it cannot tell the filename's workflow from the one
    it read: two workflows building the same kind of graph (an SDXL checkpoint
    graph, say) both read as one of them, and a filename naming the other is
    then the better witness, not the worse.
    """
    if graph_read is None:
        return filename_guess
    if filename_guess in WORKFLOW_REGISTRY and _own_graph_reads_as(filename_guess) == graph_read:
        return filename_guess
    return graph_read


def _extract_metadata(fpath: Path, suffix: str) -> dict:
    """What an output file says about the run that made it.

    Its embedded graph first, read by :func:`_graph_params`; the filename's
    prefix is the first guess at which workflow ran and the graph overrules it
    where it can tell (:func:`_reconciled`), because a file can be renamed and a
    prefix reused. Where the graph states no size for a workflow that asks for
    one, the picture itself does (:func:`_size_from_its_own_file`).
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

    graph = graph_in_file(fpath, suffix)
    if not graph:
        result["params"] = _size_from_its_own_file(fpath, result["workflow_name"])
        return result

    workflow_name = _reconciled(result["workflow_name"], _workflow_from_nodes(graph))
    params = _graph_params(graph)
    if "width" not in params:
        params = {**_size_from_its_own_file(fpath, workflow_name), **params}
    result.update(
        prompt_data=graph,
        positive_prompt=params.get("positive_prompt"),
        negative_prompt=params.get("negative_prompt"),
        seed=params.get("seed"),
        params=params,
        workflow_name=workflow_name,
    )
    return result


def _size_from_its_own_file(fpath: Path, workflow_name: str) -> dict:
    workflow = WORKFLOW_REGISTRY.get(workflow_name)
    if workflow is not None and "width" not in workflow.default_params():
        return {}
    size = _media_size(fpath)
    if size is None:
        return {}
    width, height = size
    if workflow is None:
        return {"orientation": orientation_of_size(width, height)}
    return {"width": width, "height": height}


def _graph_params(graph: dict) -> dict:
    """Every setting a prompt graph states, keyed as the workflows store them:
    the size it was sampled at, the image it started from, its base sampler's
    settings and seed, the model files it loaded, and the prompts it was
    conditioned on. Empty for a graph that states none."""
    seed, sampler_params = _sampler_settings(graph)
    positive, negative = _prompt_texts(graph)
    stated = (("positive_prompt", positive), ("negative_prompt", negative), ("seed", seed))
    return {
        **_size_params(graph),
        **_input_image_params(graph),
        **sampler_params,
        **graph_model_params(graph),
        **sound_params(graph),
        **{key: value for key, value in stated if value is not None},
    }
