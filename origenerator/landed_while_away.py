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

from origenerator import app_link, fix_training
from origenerator.comfyui_api import ComfyUIApi
from origenerator.completion import extract_completion, mark_generation_completed
from origenerator.config import (
    COMFYUI_HOST,
    COMFYUI_PORT,
    LIBRARY_STATE_DIR,
    OUTPUT_PLACES,
    STATE_DIR,
    THUMB_DIR,
)
from origenerator.db import Database
from origenerator.generation_state import GenerationStatus
from origenerator.notice_toast import raise_notice
from origenerator.output_places import OutputPlaces
from origenerator.run_notice import Notice, notice_for, outcome_of_row
from origenerator.single_instance import Copies
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)

POLL_SECONDS = 15.0

# Long enough for the longest run this app makes, short of asking all night.
PATIENCE_SECONDS = 4 * 60 * 60

CARRIES_THE_IDENTITY = "ORIGENERATOR_NOTICE_IDENTITY"


def runs_in_flight(db) -> list[dict]:
    """Every row ComfyUI is still the one to finish, oldest first."""
    return [row for row in reversed(db.list_generations())
            if row.get("status") == GenerationStatus.RUNNING]


def take_what_landed(db, api, row: dict, *, places: OutputPlaces, thumb_dir: Path) -> Notice | None:
    """Record ``row`` if ComfyUI has finished it, and say what to announce."""
    workflow = WORKFLOW_REGISTRY.get(row.get("workflow_name") or "")
    if workflow is None:
        return None
    prompt_id = row["prompt_id"]
    history = api.fetch_history(prompt_id)  # empty until the prompt finishes
    if not history:
        return None
    files, thumb, duration = extract_completion(
        workflow, history, places, thumb_dir, prompt_id)
    mark_generation_completed(db, prompt_id, files, thumb, duration)
    return notice_for(outcome_of_row(db.get_generation(prompt_id) or row,
                                     ok=True, seconds=duration))


def _training_ended(job: dict, announce) -> bool:
    trainer = fix_training.trainer_of(job)
    if trainer is not None and trainer.running():
        return False
    status = fix_training.read_status(job) or {}
    notice = notice_for(fix_training.outcome_of(
        job, ok=status.get("state") == "done",
        seconds=None if trainer is None else fix_training.time_taken(job, trainer)))
    if notice is not None:
        announce(notice)
    return True


def watch(db, api, *, announce, app_is_running, sleep=time.sleep, now=time.monotonic,
          places: OutputPlaces = OUTPUT_PLACES, thumb_dir: Path = THUMB_DIR,
          poll_seconds: float = POLL_SECONDS,
          patience_seconds: float = PATIENCE_SECONDS, trainings=None) -> None:
    """Wait out every run the app left in flight, announcing each as it lands."""
    training = list(fix_training.running_trainings() if trainings is None else trainings)
    giving_up_at = now() + patience_seconds
    while not app_is_running():
        training = [job for job in training if not _training_ended(job, announce)]
        waiting = runs_in_flight(db)
        if not waiting and not training:
            logger.info("Stopped waiting: every run left in flight has landed")
            return
        for row in waiting:
            try:
                notice = take_what_landed(db, api, row,
                                          places=places, thumb_dir=thumb_dir)
            except Exception as e:
                # One unreadable run must not strand the others: the point of
                # this process is the news, and it has no window to fail in.
                logger.warning("Could not take in %s: %s", row.get("prompt_id"), e)
                continue
            if notice is not None:
                announce(notice)
        if now() >= giving_up_at:
            logger.info("Stopped waiting: gave up on %d run(s) still in flight",
                        len(runs_in_flight(db)))
            return
        sleep(poll_seconds)
    logger.info("Stopped waiting: Origenerator is open again")


def hand_over_what_is_in_flight(db, identity: str, *, spawn=None) -> bool:
    """Start a watcher for the runs still in flight, and say whether it started.

    *identity* is the name Windows draws over this copy's notifications.
    """
    if not runs_in_flight(db) and not fix_training.running_trainings():
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
    watch(db, ComfyUIApi(COMFYUI_HOST, COMFYUI_PORT),
          announce=lambda notice: raise_notice(identity, notice),
          app_is_running=Copies(LIBRARY_STATE_DIR).one_holds_the_library)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
