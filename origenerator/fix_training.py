"""Training a fix's LoRA from photos of its part, the app's side of it: where
the photos are, the job ``tools/fix_lora_trainer.py`` is handed, and what it
says back."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

from origenerator import config
from origenerator.workflows.detail_parts import detector_folder, detector_for_part

TRAINER = Path(__file__).resolve().parents[1] / "tools" / "fix_lora_trainer.py"
_PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_IN_THE_BACKGROUND = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                      | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))


def photos_folder(part) -> Path:
    return config.FIX_PHOTOS_DIR / part.name.capitalize()


def photo_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(path for path in folder.iterdir() if path.suffix.lower() in _PHOTO_SUFFIXES)


def training_job(part, checkpoint: str, now: datetime) -> dict:
    models = config.COMFYUI_DIR / "models"
    work = config.FIX_TRAINING_DIR / part.name
    return {
        "part": part.name,
        "photos": [str(path) for path in photo_files(photos_folder(part))],
        "detector": str(config.COMFYUI_DIR / detector_folder(part) / detector_for_part(part)),
        "caption": f"close-up photo of {part.name}",
        "base_model": str(models / "checkpoints" / checkpoint),
        "sd_scripts": str(config.LORA_TRAINING_SCRIPTS),
        "output_dir": str(models / "loras" / "fixes"),
        "output_name": f"{part.name} {now:%Y-%m-%d %H%M}",
        "work": str(work),
        "status": str(work / "status.json"),
    }


def start(job: dict) -> subprocess.Popen:
    work = Path(job["work"])
    work.mkdir(parents=True, exist_ok=True)
    Path(job["status"]).unlink(missing_ok=True)
    job_file = work / "job.json"
    job_file.write_text(json.dumps(job), encoding="utf-8")
    return subprocess.Popen([str(config.LORA_TRAINING_PYTHON), str(TRAINER), str(job_file)],
                            creationflags=_IN_THE_BACKGROUND)


def read_status(job: dict) -> dict | None:
    try:
        return json.loads(Path(job["status"]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
