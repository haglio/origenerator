"""Training a fix's LoRA from photos of its part, the app's side of it: where
the photos are, the job ``tools/fix_lora_trainer.py`` is handed, and what it
says back."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

from origenerator import comfyui_launcher, config, timing
from origenerator.workflows.detail_parts import detector_folder, detector_for_part

TRAINER = Path(__file__).resolve().parents[1] / "tools" / "fix_lora_trainer.py"
_PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_IN_THE_BACKGROUND = _NO_WINDOW | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)


def photos_folder(part) -> Path:
    return config.FIX_PHOTOS_DIR / part.name.capitalize()


def photo_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(path for path in folder.iterdir() if path.suffix.lower() in _PHOTO_SUFFIXES)


def training_job(part, checkpoint: str, now: datetime) -> dict:
    models = config.COMFYUI_DIR / "models"
    work = config.FIX_TRAINING_DIR / part.name
    folder = photos_folder(part)
    return {
        "part": part.name,
        "photos": [str(path) for path in photo_files(folder)],
        "photos_folder": str(folder),
        "detector": str(config.COMFYUI_DIR / detector_folder(part) / detector_for_part(part)),
        "caption": f"close-up photo of {part.name}",
        "base_model": str(models / "checkpoints" / checkpoint),
        "sd_scripts": str(config.LORA_TRAINING_SCRIPTS),
        "output_dir": str(models / "loras" / "fixes"),
        "output_name": f"{part.name} {now:%Y-%m-%d %H%M}",
        "work": str(work),
        "status": str(work / "status.json"),
        "log": str(work / "training.log"),
    }


def comfyui_python() -> Path:
    return comfyui_launcher.load(config.COMFYUI_DIR).comfyui_python()


_PYTHONS = {"crop": lambda: comfyui_python(), "train": lambda: config.LORA_TRAINING_PYTHON}
STEPS = tuple(_PYTHONS)


def start(job: dict, step: str) -> subprocess.Popen:
    work = Path(job["work"])
    work.mkdir(parents=True, exist_ok=True)
    job_file = work / "job.json"
    if step == STEPS[0]:
        Path(job["status"]).unlink(missing_ok=True)
        Path(job["log"]).unlink(missing_ok=True)
        job_file.write_text(json.dumps(job), encoding="utf-8")
    with open(job["log"], "ab") as log:
        return subprocess.Popen([str(_PYTHONS[step]()), str(TRAINER), step, str(job_file)],
                                stdout=log, stderr=subprocess.STDOUT,
                                creationflags=_IN_THE_BACKGROUND)


def _durations_file() -> Path:
    return config.FIX_TRAINING_DIR / "durations.json"


def _durations() -> list[float]:
    try:
        return json.loads(_durations_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def note_duration(seconds: float) -> None:
    _durations_file().parent.mkdir(parents=True, exist_ok=True)
    _durations_file().write_text(json.dumps((_durations() + [seconds])[-10:]), encoding="utf-8")


def typical_seconds() -> float | None:
    return timing.estimate_seconds(_durations())


def stop(process: subprocess.Popen) -> None:
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                   capture_output=True, creationflags=_NO_WINDOW)


def read_status(job: dict) -> dict | None:
    try:
        return json.loads(Path(job["status"]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
