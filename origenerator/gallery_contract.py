from __future__ import annotations

import json
from pathlib import Path

CONTRACT_FILE = "origenerator_gallery_contract.json"

DATABASE_PATH = "state/origenerator.db"

TABLE = "generations"

COLUMNS = (
    "prompt_id",
    "source",
    "workflow_name",
    "workflow_version",
    "positive_prompt",
    "negative_prompt",
    "seed",
    "params_json",
    "output_files",
    "created_at",
)

OPTIONAL_COLUMNS = (
    "provenance",
    "evolver_exported_at",
    "evolver_unsent_at",
    "genau_exported_at",
    "genau_unsent_at",
    "remade_at",
    "starred",
    "evolver_upscale",
    "web_url",
    "library_id",
    "upscale_provenance",
    "watch_completions",
    "watch_skips",
    "watch_locks",
    "recipe_category",
    "combined_labels",
    "shape",
    "video_seconds",
    "genau_flipped",
    "video_resolution",
    "video_aspect_ratio",
)

PARAMS_MODEL_KEYS = ("unet_high", "unet", "checkpoint", "unet_low")

# ComfyUI's LoadImage node records the image under its own annotated name.
PARAMS_INPUT_IMAGE_KEY = "input_image"

LANES = {
    "evolver": {"sent": "evolver_exported_at", "unsent": "evolver_unsent_at"},
    "genau": {"sent": "genau_exported_at", "unsent": "genau_unsent_at"},
}

SILENT_COPY_ROLE = "silent"

DOWNTIME_COMMAND = (".venv/Scripts/python.exe", "-m", "origenerator.downtime")

OUTSIDE_VIDEO_ENTRIES_COMMAND = (".venv/Scripts/python.exe", "-m",
                                 "origenerator.outside_video_entries")

RECORDS_COMMAND = (".venv/Scripts/python.exe", "-m", "origenerator.ai_video_records")

PROJECT_DIR = Path(__file__).resolve().parent.parent


def declaration() -> dict:
    from origenerator.media import MediaType  # noqa: PLC0415
    from origenerator.workflows import WORKFLOW_REGISTRY  # noqa: PLC0415
    from origenerator.workflows.frame_rate import NATIVE_FPS  # noqa: PLC0415
    from origenerator.workflows.outside import published_prefixes  # noqa: PLC0415

    return {
        "database_path": DATABASE_PATH,
        "table": TABLE,
        "columns": list(COLUMNS),
        "optional_columns": list(OPTIONAL_COLUMNS),
        "params_model_keys": list(PARAMS_MODEL_KEYS),
        "params_input_image_key": PARAMS_INPUT_IMAGE_KEY,
        "lanes": {lane: dict(stamps) for lane, stamps in LANES.items()},
        "silent_copy_role": SILENT_COPY_ROLE,
        "generated_fps": NATIVE_FPS,
        "generated_fps_by_workflow": {name: workflow.native_fps
                                      for name, workflow in sorted(WORKFLOW_REGISTRY.items())
                                      if workflow.output_type == MediaType.VIDEO},
        "downtime_command": list(DOWNTIME_COMMAND),
        "outside_video_entries_command": list(OUTSIDE_VIDEO_ENTRIES_COMMAND),
        "records_command": list(RECORDS_COMMAND),
        "outside_workflow_prefixes": published_prefixes(),
    }


def published_text() -> str:
    return json.dumps(declaration(), indent=2) + "\n"


def contract_path(root: Path | None = None) -> Path:
    return (root if root is not None else PROJECT_DIR) / CONTRACT_FILE


def publish(root: Path | None = None) -> Path:
    path = contract_path(root)
    path.write_text(published_text(), encoding="utf-8")
    return path
