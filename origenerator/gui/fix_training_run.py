"""One fix's LoRA being trained, from the Train button to the LoRA it made.

The trainer needs the graphics card to itself, so nothing new is handed to
ComfyUI while it runs: it waits for what ComfyUI is making, has ComfyUI let go
of its models, and lets the queue go again when it ends either way. The
training is a program of its own that outlives the app, so a launch finds one
an earlier launch left running and holds the line for it (:meth:`adopt`)."""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from origenerator import fix_training
from origenerator.gui.generation_job import JobState
from origenerator.gui.inflight import RunReading
from origenerator.run_notice import RunOutcome

logger = logging.getLogger(__name__)

POLL_MS = 2000


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
        self._trainer = None
        self._status: dict = {}
        self._typical = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._look)

    @property
    def name(self) -> str:
        return self._job["part"]

    @property
    def running(self) -> bool:
        return self._trainer is not None and self._trainer.running()

    def reading(self) -> RunReading:
        if self._trainer is None:
            return RunReading(status=JobState.QUEUED, typical_seconds=self._typical)
        training = self._status.get("state") == "training"
        counted = (self._status["done"], self._status["total"]) if self._status.get("total") else None
        return RunReading(status=JobState.RUNNING,
                          progress=counted if training else None,
                          pass_progress=None if training else counted,
                          stage="Training" if training else "Cropping photos",
                          started_at=self._trainer.began, typical_seconds=self._typical)

    def begin(self) -> None:
        self._hold_the_line()
        self.progress.emit("Waiting")
        self._look()

    def adopt(self, trainer) -> None:
        self._trainer = trainer
        self._hold_the_line()
        self.progress.emit("Training")

    def _hold_the_line(self) -> None:
        self._typical = fix_training.typical_seconds()
        self._queue.hold_for_training(self)
        self._timer.start(POLL_MS)

    def _look(self) -> None:
        if self._trainer is None:
            if not self._queue.making_something():
                self._queue.free_comfyui_memory()
                self._start()
            return
        alive = self._trainer.running()
        status = self._status = fix_training.read_status(self._job) or {}
        if not alive:
            logger.info("Fix training %s: its program ended, saying %s", self.name, status)
        if status.get("state") == "done":
            self._end(self._outcome(ok=True))
            self.finished.emit(fix_training.lora_of(status))
        elif status.get("state") == "failed":
            self._fail(status["message"])
        elif not alive:
            self._fail("The training program quit without saying why. An agent can read "
                       f"what it printed in {self._job['log']}.")
        elif status.get("total"):
            done = round(100 * status["done"] / status["total"])
            word = "Training" if status["state"] == "training" else "Cropping"
            self.progress.emit(f"{word} {done}%")

    def _start(self) -> None:
        try:
            self._trainer = fix_training.start(self._job)
        except Exception as error:
            logger.exception("Fix training %s could not be started", self.name)
            self._fail(f"The training couldn't be started: {error}")
            return
        self.progress.emit("Cropping")

    def cancel(self) -> None:
        if self._trainer is not None:
            self._trainer.stop()
        logger.info("Fix training %s: canceled", self.name)
        self._end(None)
        self.canceled.emit()

    def _outcome(self, *, ok: bool) -> RunOutcome:
        return fix_training.outcome_of(
            self._job, ok=ok,
            seconds=None if self._trainer is None else fix_training.time_taken(self._job, self._trainer))

    def _fail(self, why: str) -> None:
        self._end(self._outcome(ok=False))
        self.failed.emit(why)

    def _end(self, outcome: RunOutcome | None) -> None:
        self._timer.stop()
        self.ended.emit(outcome)
