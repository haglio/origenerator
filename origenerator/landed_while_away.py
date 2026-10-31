"""What becomes of a run that lands while Origenerator is closed.

The app is what watches ComfyUI, so closing it with work still in flight left
the run announced by nobody until somebody opened the app again. This is what
the app starts as it quits.

Qt-free on purpose: it is started to outlive a window, not to draw one.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

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
from origenerator.output_places import OutputPlaces
from origenerator.run_toast import Toast, outcome_of_row, toast_for
from origenerator.single_instance import Copies
from origenerator.toast_raising import raise_toast

logger = logging.getLogger(__name__)

POLL_SECONDS = 15.0

# Long enough for the longest run this app makes, short of asking all night.
PATIENCE_SECONDS = 4 * 60 * 60

CARRIES_THE_IDENTITY = "ORIGENERATOR_TOAST_IDENTITY"


def runs_left_in_flight(db) -> list[dict]:
    """Every run ComfyUI is still the one to finish but the backfill's, oldest first."""
    return [row for row in reversed(db.list_generations())
            if row.get("status") == GenerationStatus.RUNNING
            and source_of(row) != GenerationSource.BACKFILL]


def take_what_landed(db, api, row: dict, *, places: OutputPlaces, thumb_dir: Path) -> Toast | None:
    """Record ``row`` if ComfyUI has finished it, and say what to announce."""
    if not take_in_what_landed(db, api, row, places, thumb_dir):
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


def watch(db, api, *, announce, app_is_running, sleep=time.sleep, now=time.monotonic,
          places: OutputPlaces = OUTPUT_PLACES, thumb_dir: Path = THUMB_DIR,
          poll_seconds: float = POLL_SECONDS,
          patience_seconds: float = PATIENCE_SECONDS, trainings=None) -> None:
    """Wait out every run the app left in flight, announcing each as it lands."""
    training = list(running_trainings() if trainings is None else trainings)
    giving_up_at = now() + patience_seconds
    while not app_is_running():
        training = [job for job in training if not _training_ended(job, announce)]
        waiting = runs_left_in_flight(db)
        if not waiting and not training:
            logger.info("Stopped waiting: every run left in flight has landed")
            return
        for row in waiting:
            try:
                toast = take_what_landed(db, api, row,
                                          places=places, thumb_dir=thumb_dir)
            except Exception as e:
                # One unreadable run must not strand the others: the point of
                # this process is the news, and it has no window to fail in.
                logger.warning("Could not take in %s: %s", row.get("prompt_id"), e)
                continue
            if toast is not None:
                announce(toast)
        if now() >= giving_up_at:
            logger.info("Stopped waiting: gave up on %d run(s) still in flight",
                        len(runs_left_in_flight(db)))
            return
        sleep(poll_seconds)
    logger.info("Stopped waiting: Origenerator is open again")


def hand_over_what_is_in_flight(db, identity: str, *, spawn=None) -> bool:
    """Start a watcher for the runs still in flight, and say whether it started.

    *identity* is the name Windows draws over this copy's toasts.
    """
    if not runs_left_in_flight(db) and not running_trainings():
        return False
    (spawn or _start_a_watcher)(identity)
    return True


def _start_a_watcher(identity: str) -> None:
    """Start this module as a process of its own, outliving the window."""
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
    """Wait out the runs this checkout's app left in flight. What it starts."""
    argv = sys.argv[1:] if argv is None else argv
    identity = argv[0] if argv else os.environ.get(CARRIES_THE_IDENTITY, "")
    if not identity:
        return 2
    _log_into_the_apps_file()
    db = Database(LIBRARY_STATE_DIR / "origenerator.db")
    watch(db, ComfyUIApi(COMFYUI_HOST, COMFYUI_PORT, folders=COMFYUI_FOLDERS),
          announce=lambda toast: raise_toast(identity, toast),
          app_is_running=Copies(LIBRARY_STATE_DIR).one_holds_the_library)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
