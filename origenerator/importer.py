import json
import logging
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from origenerator.db import Database
from origenerator.media import media_type_from_filename
from origenerator.thumbnail import generate_thumbnail
from origenerator.workflows import WORKFLOW_REGISTRY

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

            rel_path = fpath.relative_to(output_dir).as_posix()
            if rel_path in existing:
                continue

            metadata = _extract_metadata(fpath, fpath.suffix.lower())
            prompt_id = str(uuid.uuid4())

            thumb_path = None
            try:
                thumb_path = str(generate_thumbnail(fpath, output_type, thumb_dir))
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
            subfolder = Path(dirpath).relative_to(output_dir).as_posix()
            if subfolder == ".":
                subfolder = ""
            db.update_generation(
                prompt_id,
                status="completed",
                output_files=json.dumps([{
                    "filename": fname,
                    "subfolder": subfolder,
                    "type": "output",
                }]),
                thumbnail_path=thumb_path,
                completed_at=mtime.isoformat(),
            )
            existing.add(rel_path)
            imported += 1

    return imported


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
            capture_output=True, text=True, timeout=30,
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


def _follow(graph: dict, ref) -> dict | None:
    """Resolve a ComfyUI input link ``[node_id, slot]`` to its source node."""
    if isinstance(ref, list) and ref:
        return graph.get(str(ref[0]))
    return None


def _extract_metadata(fpath: Path, suffix: str) -> dict:
    result: dict = {
        "workflow_name": infer_workflow_name(fpath.name) or "unknown",
        "workflow_version": "imported",
        "positive_prompt": None,
        "negative_prompt": None,
        "seed": None,
        "params": {},
        "prompt_data": {},
    }

    prompt_data = _read_prompt_graph(fpath, suffix)
    if not prompt_data:
        return result
    result["prompt_data"] = prompt_data

    # Wan video workflows route prompts through a conditioning node; follow its
    # links structurally so we don't depend on CLIPTextEncode node titles.
    cond = next(
        (n for n in prompt_data.values()
         if n.get("class_type") in ("WanImageToVideo", "WanFirstLastFrameToVideo")),
        None,
    )
    if cond:
        ci = cond.get("inputs", {})
        pos = _follow(prompt_data, ci.get("positive"))
        neg = _follow(prompt_data, ci.get("negative"))
        if pos and pos.get("class_type") == "CLIPTextEncode":
            result["positive_prompt"] = pos["inputs"].get("text")
        if neg and neg.get("class_type") == "CLIPTextEncode":
            result["negative_prompt"] = neg["inputs"].get("text")
        for src, dst in (("width", "width"), ("height", "height"), ("length", "frame_count")):
            if isinstance(ci.get(src), int):
                result["params"][dst] = ci[src]

    for node in prompt_data.values():
        class_type = node.get("class_type", "")
        inputs = node.get("inputs", {})
        meta_title = node.get("_meta", {}).get("title", "")

        # Title-based prompts only when there's no structural source above.
        if class_type == "CLIPTextEncode" and cond is None:
            text = inputs.get("text")
            if isinstance(text, str):
                if "Negative" in meta_title:
                    result["negative_prompt"] = text
                elif result["positive_prompt"] is None:
                    result["positive_prompt"] = text

        if class_type == "LoadImage":
            image = inputs.get("image")
            if isinstance(image, str):
                result["params"]["input_image"] = image

        if class_type == "CheckpointLoaderSimple":
            ckpt = inputs.get("ckpt_name")
            if isinstance(ckpt, str):
                result["params"]["checkpoint"] = ckpt

        if class_type == "KSampler":
            seed = inputs.get("seed")
            if isinstance(seed, int):
                result["seed"] = seed
            result["params"].update({
                k: v for k, v in inputs.items()
                if isinstance(v, (int, float, str, bool))
            })

        if class_type == "KSamplerAdvanced":
            seed = inputs.get("noise_seed")
            # Prefer the noise-adding (stage-1) sampler's seed.
            if isinstance(seed, int) and (result["seed"] is None or inputs.get("add_noise") == "enable"):
                result["seed"] = seed
            result["params"].update({
                k: v for k, v in inputs.items()
                if isinstance(v, (int, float, str, bool))
            })

    # The embedded graph is authoritative; refine the filename guess.
    node_types = {n.get("class_type") for n in prompt_data.values()}
    if "WanFirstLastFrameToVideo" in node_types:
        result["workflow_name"] = "wan22_flf2v_loop"
    elif "WanImageToVideo" in node_types:
        result["workflow_name"] = "wan22_i2v"
    elif "CheckpointLoaderSimple" in node_types:
        result["workflow_name"] = "sdxl_t2i"

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
