from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

from app_support.logging_utils import configure_logging, install_exception_logging

from origenerator import app_link, fix_training, look_training, lora_training
from origenerator.comfyui_api import ComfyUIApi
from origenerator.config import (
    COMFYUI_FOLDERS,
    COMFYUI_HOST,
    COMFYUI_PORT,
    LIBRARY_STATE_DIR,
    OUTPUT_PLACES,
    STATE_DIR,
    THUMB_DIR,
)
from origenerator.db import Database
from origenerator.generation_state import GenerationSource, GenerationStatus, source_of
from origenerator.inflight import take_in_what_landed
from origenerator.output_places import OutputFolders
from origenerator.run_toast import Toast, outcome_of_row, toast_for
from origenerator.single_instance import Copies
from origenerator.toast_raising import raise_toast

logger = logging.getLogger(__name__)

POLL_SECONDS = 15.0

PATIENCE_SECONDS = 4 * 60 * 60

CARRIES_THE_IDENTITY = "ORIGENERATOR_TOAST_IDENTITY"


def runs_left_in_flight(db) -> list[dict]:
    return [row for row in reversed(db.list_generations())
            if row.get("status") == GenerationStatus.RUNNING
            and source_of(row) != GenerationSource.BACKFILL]


def take_what_landed(db, api, row: dict, folders: OutputFolders) -> Toast | None:
    if not take_in_what_landed(db, api, row, folders):
        return None
    landed = db.get_generation(row["prompt_id"]) or row
    return toast_for(outcome_of_row(landed, ok=True, seconds=landed.get("duration_seconds")))


def training_toast(job: dict) -> Toast | None:
    trainer = lora_training.trainer_of(job)
    status = lora_training.read_status(job) or {}
    return toast_for(lora_training.outcome_of(
        job, ok=status.get("state") == "done",
        seconds=None if trainer is None else lora_training.time_taken(job, trainer)))


def running_trainings() -> list[dict]:
    return fix_training.running_trainings() + look_training.running_trainings()


def _training_ended(job: dict, announce) -> bool:
    trainer = lora_training.trainer_of(job)
    if trainer is not None and trainer.running():
        return False
    if (toast := training_toast(job)) is not None:
        announce(toast)
    return True


@dataclass(frozen=True)
class Watch:
    db: object
    api: object
    announce: Callable[[Toast], object]
    app_is_running: Callable[[], bool]
    sleep: Callable[[float], object] = time.sleep
    folders: OutputFolders = OutputFolders(OUTPUT_PLACES, THUMB_DIR)
    patience_seconds: float = PATIENCE_SECONDS
    trainings: list | None = None

    def run(self) -> None:
        training = list(running_trainings() if self.trainings is None else self.trainings)
        giving_up_at = time.monotonic() + self.patience_seconds
        while not self.app_is_running():
            training = [job for job in training if not _training_ended(job, self.announce)]
            waiting = runs_left_in_flight(self.db)
            if not waiting and not training:
                logger.info("Stopped waiting: every run left in flight has landed")
                return
            for row in waiting:
                try:
                    toast = take_what_landed(self.db, self.api, row, self.folders)
                except Exception as e:
                    logger.warning("Could not take in %s: %s", row.get("prompt_id"), e)
                    continue
                if toast is not None:
                    self.announce(toast)
            if time.monotonic() >= giving_up_at:
                logger.info("Stopped waiting: gave up on %d run(s) still in flight",
                            len(runs_left_in_flight(self.db)))
                return
            self.sleep(POLL_SECONDS)
        logger.info("Stopped waiting: Origenerator is open again")


def hand_over_what_is_in_flight(db, identity: str, *, spawn=None) -> bool:
    if not runs_left_in_flight(db) and not running_trainings():
        return False
    (spawn or _start_a_watcher)(identity)
    return True


def _start_a_watcher(identity: str) -> None:
    import subprocess  # noqa: PLC0415
    try:
        watcher = subprocess.Popen(
            [str(app_link.windowless_interpreter()), "-m", __name__, identity],
            cwd=str(app_link.CHECKOUT),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as e:
        logger.warning("Nothing will wait out the runs still in flight: %s", e)
        return
    logger.info("Process %d waits out the runs still in flight", watcher.pid)


def _log_into_the_apps_file() -> None:
    configure_logging("", STATE_DIR / "origenerator.log")
    install_exception_logging(logger)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    identity = argv[0] if argv else os.environ.get(CARRIES_THE_IDENTITY, "")
    if not identity:
        return 2
    _log_into_the_apps_file()
    db = Database(LIBRARY_STATE_DIR / "origenerator.db")
    Watch(db, ComfyUIApi(COMFYUI_HOST, COMFYUI_PORT, folders=COMFYUI_FOLDERS),
          announce=lambda toast: raise_toast(identity, toast),
          app_is_running=Copies(LIBRARY_STATE_DIR).one_holds_the_library).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
