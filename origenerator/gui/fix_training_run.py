"""One fix's LoRA being trained, from the Train button to the LoRA it made.

The trainer needs the graphics card to itself, so nothing new is handed to
ComfyUI while it runs: it waits for what ComfyUI is making, has ComfyUI let go
of its models, and lets the queue go again when it ends either way."""

from __future__ import annotations

import logging
import time
from pathlib import PureWindowsPath

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from origenerator import fix_training
from origenerator.gallery import JobKind
from origenerator.gui.generation_job import JobState
from origenerator.gui.inflight import RunReading
from origenerator.run_notice import RunOutcome

logger = logging.getLogger(__name__)

POLL_MS = 2000
_STAGES = {"crop": ("cropping", "Cropping photos"), "train": ("training", "Training")}


class FixTrainingRun(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)
    canceled = pyqtSignal()
    ended = pyqtSignal(object)

    def __init__(self, job: dict, queue, *, reveal, parent=None):
        super().__init__(parent)
        self._job = job
        self._queue = queue
        self.reveal = reveal
        self._step_name = None
        self._process = None
        self._status: dict = {}
        self._started_at = None
        self._typical = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)

    @property
    def name(self) -> str:
        return self._job["part"]

    def reading(self) -> RunReading:
        if self._process is None:
            return RunReading(status=JobState.QUEUED, typical_seconds=self._typical)
        state, stage = _STAGES[self._step_name]
        counted = self._status.get("state") == state and self._status.get("total")
        return RunReading(status=JobState.RUNNING,
                          progress=(self._status["done"], self._status["total"]) if counted else None,
                          stage=stage, started_at=self._started_at,
                          typical_seconds=self._typical)

    def begin(self) -> None:
        self._typical = fix_training.typical_seconds()
        self._queue.hold_for_training(self)
        self.progress.emit("Waiting")
        self._timer.start(POLL_MS)
        self._step()

    def _step(self) -> None:
        if self._process is None:
            if not self._queue.making_something():
                self._queue.free_comfyui_memory()
                self._started_at = time.time()
                self._start(fix_training.STEPS[0])
            return
        code = self._process.poll()
        status = self._status = fix_training.read_status(self._job) or {}
        if code is not None:
            logger.info("Fix training %s: its %s step ended with exit code %s, saying %s",
                        self._job.get("part"), self._step_name, code, status)
        if status.get("state") == "done":
            outcome = self._outcome(ok=True)
            fix_training.note_duration(outcome.seconds)
            self._end(outcome)
            self.finished.emit(str(PureWindowsPath("fixes") / status["lora"]))
        elif status.get("state") == "failed":
            self._fail(status["message"])
        elif code == 0 and self._step_name != fix_training.STEPS[-1]:
            self._start(fix_training.STEPS[fix_training.STEPS.index(self._step_name) + 1])
        elif code is not None:
            self._fail("The training program quit without saying why. An agent can read "
                       f"what it printed in {self._job['log']}.")
        elif status.get("total"):
            done = round(100 * status["done"] / status["total"])
            word = "Cropping" if status["state"] == "cropping" else "Training"
            self.progress.emit(f"{word} {done}%")

    def _start(self, step: str) -> None:
        self._step_name = step
        try:
            self._process = fix_training.start(self._job, step)
        except Exception as error:
            logger.exception("Fix training %s: its %s step could not be started",
                             self._job.get("part"), step)
            self._fail(f"The training couldn't be started: {error}")
            return
        self.progress.emit("Cropping" if step == fix_training.STEPS[0] else "Training")

    def cancel(self) -> None:
        if self._process is not None:
            fix_training.stop(self._process)
        logger.info("Fix training %s: canceled during its %s step", self._job.get("part"),
                    self._step_name or "wait")
        self._end(None)
        self.canceled.emit()

    def _outcome(self, *, ok: bool) -> RunOutcome:
        seconds = None if self._started_at is None else time.time() - self._started_at
        return RunOutcome(kind=JobKind.TRAINING, recipe=f"{self.name.capitalize()} fix",
                          seconds=seconds, ok=ok, source="", generation="")

    def _fail(self, why: str) -> None:
        self._end(self._outcome(ok=False))
        self.failed.emit(why)

    def _end(self, outcome: RunOutcome | None) -> None:
        self._timer.stop()
        self.ended.emit(outcome)
