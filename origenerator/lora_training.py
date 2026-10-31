from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

from app_support.win32 import process_started

from origenerator import timing
from origenerator.gallery import JobKind
from origenerator.run_toast import RunOutcome

TRAINERS = Path(__file__).resolve().parents[1] / "tools"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_IN_THE_BACKGROUND = _NO_WINDOW | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)


class TrainingState(Enum):
    UNTRAINED = "untrained"
    CURRENT = "current"
    OUT_OF_DATE = "out of date"


def training_state(trained: Path, picture_stamps: dict) -> TrainingState:
    try:
        kept = json.loads(trained.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return TrainingState.UNTRAINED
    if kept.get("photo_stamps") == picture_stamps:
        return TrainingState.CURRENT
    return TrainingState.OUT_OF_DATE


@dataclass(frozen=True)
class TrainingOffer:
    label: str
    enabled: bool
    tooltip: str
    pictures: int
    folder: Path
    counted: str = "picture"


def offer(state: TrainingState, *, tooltip: str, pictures: int, folder: Path,
          counted: str = "picture") -> TrainingOffer:
    return TrainingOffer("Train" if state is TrainingState.UNTRAINED else "Retrain",
                         state is not TrainingState.CURRENT, tooltip, pictures, folder, counted)


def picture_stamps(pictures: list[Path]) -> dict[str, list[int]]:
    stamps = {}
    for picture in pictures:
        found = picture.stat()
        stamps[f"{picture.parent.name}/{picture.name}"] = [found.st_size, found.st_mtime_ns]
    return stamps


def work_files(work: Path) -> dict[str, str]:
    return {
        "work": str(work),
        "status": str(work / "status.json"),
        "log": str(work / "training.log"),
        "job_file": str(work / "job.json"),
        "process": str(work / "process.json"),
        "trained": str(work / "trained.json"),
    }


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
                           capture_output=True, creationflags=_NO_WINDOW, check=False)


def start(job: dict, python: Path, trainer: Path, **for_the_program) -> Trainer:
    Path(job["work"]).mkdir(parents=True, exist_ok=True)
    Path(job["status"]).unlink(missing_ok=True)
    Path(job["log"]).unlink(missing_ok=True)
    Path(job["job_file"]).write_text(json.dumps(dict(job, **for_the_program)), encoding="utf-8")
    with open(job["log"], "ab") as log:
        process = subprocess.Popen([str(python), str(trainer), "run", job["job_file"]],
                                   stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=_IN_THE_BACKGROUND)
    started = Trainer(process.pid, process_started(process.pid), time.time())
    Path(job["process"]).write_text(json.dumps(asdict(started)), encoding="utf-8")
    return started


def trainer_of(job: dict) -> Trainer | None:
    try:
        return Trainer(**json.loads(Path(job["process"]).read_text(encoding="utf-8")))
    except (KeyError, OSError, ValueError, TypeError):
        return None


def _durations(folder: Path) -> list[float]:
    try:
        return json.loads((folder / "durations.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def time_taken(job: dict, trainer: Trainer) -> float:
    try:
        ended = Path(job["status"]).stat().st_mtime
    except OSError:
        ended = time.time()
    return ended - trainer.began


def note_duration(folder: Path, seconds: float) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "durations.json").write_text(json.dumps((_durations(folder) + [seconds])[-10:]),
                                           encoding="utf-8")


def typical_seconds(folder: Path) -> float | None:
    return timing.estimate_seconds(_durations(folder))


def trainings(folder: Path) -> list[dict]:
    jobs = []
    for job_file in sorted(folder.glob("*/job.json")):
        try:
            jobs.append(json.loads(job_file.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return jobs


def running_trainings(folder: Path) -> list[dict]:
    return [job for job in trainings(folder)
            if (trainer := trainer_of(job)) is not None and trainer.running()]


def outcome_of(job: dict, *, ok: bool, seconds: float | None) -> RunOutcome:
    return RunOutcome(kind=JobKind.TRAINING, display_name=job["display_name"],
                      seconds=seconds, ok=ok, source="", generation="")


def untaken_lora(job: dict) -> str | None:
    status = read_status(job) or {}
    if status.get("state") != "done" or status.get("taken"):
        return None
    return status["lora"]


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


def take_up(kind, *, adopt, take) -> None:
    for job in kind.trainings():
        trainer = trainer_of(job)
        if trainer is None:
            continue
        if trainer.running() and job.get("automatic"):
            trainer.stop()
        elif trainer.running():
            adopt(job, trainer)
        elif (lora := untaken_lora(job)) is not None:
            take(job, lora)
