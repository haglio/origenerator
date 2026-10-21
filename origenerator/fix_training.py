"""Training a fix's LoRA from photos of its part, the app's side of it: where
the photos are, the job ``tools/fix_lora_trainer.py`` is handed, and what it
says back."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PureWindowsPath

from app_support.win32 import process_started

from origenerator import comfyui_launcher, config, timing
from origenerator.gallery import JobKind
from origenerator.run_notice import RunOutcome
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
        "job_file": str(work / "job.json"),
        "process": str(work / "process.json"),
    }


def comfyui_python() -> Path:
    return comfyui_launcher.load(config.COMFYUI_DIR).comfyui_python()


@dataclass(frozen=True)
class Trainer:
    pid: int
    started: int | None
    began: float

    def running(self) -> bool:
        return self.started is not None and process_started(self.pid) == self.started

    def stop(self) -> None:
        if self.running():
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.pid)],
                           capture_output=True, creationflags=_NO_WINDOW)


def start(job: dict) -> Trainer:
    Path(job["work"]).mkdir(parents=True, exist_ok=True)
    Path(job["status"]).unlink(missing_ok=True)
    Path(job["log"]).unlink(missing_ok=True)
    Path(job["job_file"]).write_text(json.dumps(dict(job, comfyui_python=str(comfyui_python()))),
                                     encoding="utf-8")
    with open(job["log"], "ab") as log:
        process = subprocess.Popen([str(config.LORA_TRAINING_PYTHON), str(TRAINER), "run",
                                    job["job_file"]],
                                   stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=_IN_THE_BACKGROUND)
    trainer = Trainer(process.pid, process_started(process.pid), time.time())
    Path(job["process"]).write_text(json.dumps(asdict(trainer)), encoding="utf-8")
    return trainer


def trainer_of(job: dict) -> Trainer | None:
    try:
        return Trainer(**json.loads(Path(job["process"]).read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return None


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


def trainings() -> list[dict]:
    jobs = []
    for job_file in sorted(config.FIX_TRAINING_DIR.glob("*/job.json")):
        try:
            jobs.append(json.loads(job_file.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return jobs


def running_trainings() -> list[dict]:
    return [job for job in trainings()
            if (trainer := trainer_of(job)) is not None and trainer.running()]


def outcome_of(job: dict, *, ok: bool, seconds: float | None) -> RunOutcome:
    return RunOutcome(kind=JobKind.TRAINING, recipe=f"{job['part'].capitalize()} fix",
                      seconds=seconds, ok=ok, source="", generation="")


def lora_of(status: dict) -> str:
    return str(PureWindowsPath("fixes") / status["lora"])


def untaken_lora(job: dict) -> str | None:
    status = read_status(job) or {}
    if status.get("state") != "done" or status.get("taken"):
        return None
    return lora_of(status)


def mark_taken(job: dict) -> None:
    Path(job["status"]).write_text(json.dumps(dict(read_status(job) or {}, taken=True)),
                                   encoding="utf-8")


def read_status(job: dict) -> dict | None:
    try:
        return json.loads(Path(job["status"]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
