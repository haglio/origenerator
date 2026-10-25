"""Training a fix's LoRA from photos of its part, the app's side of it: where
the photos are, the job ``tools/fix_lora_trainer.py`` is handed, and what it
says back."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path, PureWindowsPath

from app_support.win32 import process_started

from origenerator import comfyui_launcher, config, gallery, timing
from origenerator.gallery import JobKind
from origenerator.gallery.enhance_settings import MATCH_SOURCE_MODEL
from origenerator.model_titles import FIX_LORA_FOLDER, fix_lora_name
from origenerator.run_notice import RunOutcome
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.detail_parts import detector_folder, detector_for_part, part_table

TRAINER = Path(__file__).resolve().parents[1] / "tools" / "fix_lora_trainer.py"
_PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_IN_THE_BACKGROUND = _NO_WINDOW | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)


def photos_folder(part) -> Path:
    return config.FIX_PHOTOS_DIR / part.name.lower()


def shared_photos_folder() -> Path:
    return config.FIX_PHOTOS_DIR / "shared"


def photo_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(path for path in folder.iterdir() if path.suffix.lower() in _PHOTO_SUFFIXES)


def training_folders(part) -> list[Path]:
    return [photos_folder(part)] + ([shared_photos_folder()] if part.shared_photos else [])


def training_photos(part) -> list[Path]:
    return [photo for folder in training_folders(part) for photo in photo_files(folder)]


def photo_stamps(part) -> dict[str, list[int]]:
    stamps = {}
    for photo in training_photos(part):
        found = photo.stat()
        stamps[f"{photo.parent.name}/{photo.name}"] = [found.st_size, found.st_mtime_ns]
    return stamps


class TrainingState(Enum):
    UNTRAINED = "untrained"
    CURRENT = "current"
    OUT_OF_DATE = "out of date"


def _work_folder(part) -> Path:
    return config.FIX_TRAINING_DIR / part.name


def training_state(part) -> TrainingState:
    try:
        trained = json.loads((_work_folder(part) / "trained.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return TrainingState.UNTRAINED
    if trained.get("photo_stamps") == photo_stamps(part):
        return TrainingState.CURRENT
    return TrainingState.OUT_OF_DATE


def fix_to_train():
    return next((part for part in part_table()
                 if detector_for_part(part) and training_photos(part)
                 and training_state(part) is not TrainingState.CURRENT), None)


def model_to_train_for(enhance_params: dict) -> str:
    chosen = enhance_params.get("checkpoint")
    if not chosen or chosen == MATCH_SOURCE_MODEL:
        return WORKFLOW_REGISTRY[gallery.ENHANCE_WORKFLOW].default_params()["checkpoint"]
    return chosen


def training_job(part, checkpoint: str, now: datetime, *, automatic: bool = False) -> dict:
    models = config.COMFYUI_DIR / "models"
    work = _work_folder(part)
    return {
        "part": part.name,
        "photos": [str(path) for path in training_photos(part)],
        "photos_folders": [str(folder) for folder in training_folders(part)],
        "photo_stamps": photo_stamps(part),
        "detector": str(config.COMFYUI_DIR / detector_folder(part) / detector_for_part(part)),
        "caption": f"close-up photo of {part.name}",
        "base_model": str(models / "checkpoints" / checkpoint),
        "sd_scripts": str(config.LORA_TRAINING_SCRIPTS),
        "output_dir": str(models / "loras" / FIX_LORA_FOLDER),
        "output_name": fix_lora_name(part.name, now),
        "work": str(work),
        "status": str(work / "status.json"),
        "log": str(work / "training.log"),
        "job_file": str(work / "job.json"),
        "process": str(work / "process.json"),
        "trained": str(work / "trained.json"),
        "automatic": automatic,
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
    except (KeyError, OSError, ValueError, TypeError):
        return None


def _durations_file() -> Path:
    return config.FIX_TRAINING_DIR / "durations.json"


def _durations() -> list[float]:
    try:
        return json.loads(_durations_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def time_taken(job: dict, trainer: Trainer) -> float:
    try:
        ended = Path(job["status"]).stat().st_mtime
    except OSError:
        ended = time.time()
    return ended - trainer.began


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
    return RunOutcome(kind=JobKind.TRAINING, display_name=f"{job['part'].capitalize()} fix",
                      seconds=seconds, ok=ok, source="", generation="")


def lora_of(status: dict) -> str:
    return str(PureWindowsPath(FIX_LORA_FOLDER) / status["lora"])


def untaken_lora(job: dict) -> str | None:
    status = read_status(job) or {}
    if status.get("state") != "done" or status.get("taken"):
        return None
    return lora_of(status)


def mark_taken(job: dict) -> None:
    _mark(job, taken=True)


def mark_announced(job: dict) -> None:
    _mark(job, announced=True)


def _mark(job: dict, **marks) -> None:
    Path(job["status"]).write_text(json.dumps(dict(read_status(job) or {}, **marks)),
                                   encoding="utf-8")


def read_status(job: dict) -> dict | None:
    try:
        return json.loads(Path(job["status"]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
