import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from origenerator.db import Database
from origenerator.thumbnail import generate_thumbnail

logger = logging.getLogger(__name__)

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
_VIDEO_EXTS = {".mp4", ".webm"}


def import_comfyui_output(output_dir: Path, db: Database, thumb_dir: Path) -> int:
    imported = 0
    existing = _get_existing_filenames(db)

    for dirpath, _, filenames in os.walk(output_dir):
        for fname in sorted(filenames):
            fpath = Path(dirpath) / fname
            suffix = fpath.suffix.lower()
            if suffix not in _IMAGE_EXTS and suffix not in _VIDEO_EXTS:
                continue

            rel_path = fpath.relative_to(output_dir).as_posix()
            if rel_path in existing:
                continue

            output_type = "image" if suffix in _IMAGE_EXTS else "video"
            metadata = _extract_metadata(fpath, suffix)
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
                params_json=json.dumps(metadata.get("params", {})),
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


def _extract_metadata(fpath: Path, suffix: str) -> dict:
    result: dict = {
        "workflow_name": "unknown",
        "workflow_version": "imported",
        "positive_prompt": None,
        "negative_prompt": None,
        "seed": None,
        "params": {},
        "prompt_data": {},
    }

    if suffix != ".png":
        return result

    try:
        img = Image.open(fpath)
        prompt_str = img.info.get("prompt")
        if not prompt_str:
            return result
        prompt_data = json.loads(prompt_str)
        result["prompt_data"] = prompt_data
    except Exception:
        return result

    # Extract prompts and seed from nodes
    for node_id, node in prompt_data.items():
        class_type = node.get("class_type", "")
        inputs = node.get("inputs", {})
        meta_title = node.get("_meta", {}).get("title", "")

        if class_type == "CLIPTextEncode":
            text = inputs.get("text")
            if isinstance(text, str):
                if "Negative" in meta_title:
                    result["negative_prompt"] = text
                elif result["positive_prompt"] is None:
                    result["positive_prompt"] = text

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
            if isinstance(seed, int) and result["seed"] is None:
                result["seed"] = seed
            result["params"].update({
                k: v for k, v in inputs.items()
                if isinstance(v, (int, float, str, bool))
            })

    # Try to infer workflow name from filename prefix or node types
    node_types = {n.get("class_type") for n in prompt_data.values()}
    if "WanFirstLastFrameToVideo" in node_types:
        result["workflow_name"] = "wan22_flf2v_loop"
    elif "CheckpointLoaderSimple" in node_types:
        result["workflow_name"] = "sdxl_t2i"

    return result
