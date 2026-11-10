from __future__ import annotations

import json
from pathlib import Path

CONTRACT_AT_THE_CHECKOUT_ROOT = "origenerator_gallery_contract.json"

DATABASE_PATH = "state/origenerator.db"

TABLE = "generations"

COLUMNS = (
    "prompt_id",
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

PROJECT_DIR = Path(__file__).resolve().parent.parent


def declaration() -> dict:
    from origenerator.workflows.frame_rate import NATIVE_FPS  # noqa: PLC0415

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
        "downtime_command": list(DOWNTIME_COMMAND),
        "outside_video_entries_command": list(OUTSIDE_VIDEO_ENTRIES_COMMAND),
    }


def published_text() -> str:
    return json.dumps(declaration(), indent=2) + "\n"


def contract_path(root: Path | None = None) -> Path:
    return (root if root is not None else PROJECT_DIR) / CONTRACT_AT_THE_CHECKOUT_ROOT


def publish(root: Path | None = None) -> Path:
    path = contract_path(root)
    path.write_text(published_text(), encoding="utf-8")
    return path
