"""One LoRA being trained, from the Train button to the LoRA it made.

A fix's trainer needs the graphics card to itself, so nothing new is handed to
ComfyUI while it runs: it waits for what ComfyUI is making, has ComfyUI let go
of its models, and lets the queue go again when it ends either way. A look
LoRA's trainer yields the card itself whenever ComfyUI has work, so the queue
only watches it. Either training is a program of its own that outlives the
app, so a launch finds one an earlier launch left running and takes it up
(:meth:`adopt`)."""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from origenerator import lora_training
from origenerator.gui.generation_job import JobState
from origenerator.gui.inflight import RunReading
from origenerator.run_notice import RunOutcome

logger = logging.getLogger(__name__)

POLL_MS = 2000
STAGES = {
    "cropping": ("Cropping", "Cropping photos"),
    "preparing": ("Copying", "Copying pictures"),
    "describing": ("Describing", "Describing pictures"),
    "caching": ("Preparing", "Preparing"),
    "waiting": ("Waiting", "Waiting for the graphics card"),
    "training": ("Training", "Training"),
}


class TrainingRun(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)
    canceled = pyqtSignal()
    ended = pyqtSignal(object)

    def __init__(self, job: dict, queue, kind, *, reveal, parent=None):
        super().__init__(parent)
        self._job = job
        self._queue = queue
        self._kind = kind
        self.holds_the_line = kind.HOLDS_THE_LINE
        self.reveal = reveal
        self._trainer = None
        self._status: dict = {"state": kind.FIRST_STATE}
        self._typical = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._look)

    @property
    def caption(self) -> str:
        return f"{self._job['display_name']} LoRA"

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
                          stage=self._stage()[1],
                          started_at=self._trainer.began, typical_seconds=self._typical)

    def _stage(self) -> tuple[str, str]:
        return STAGES.get(self._status.get("state"), STAGES["training"])

    def begin(self) -> None:
        self._watch()
        self.progress.emit("Waiting")
        self._look()

    def adopt(self, trainer) -> None:
        self._trainer = trainer
        self._watch()
        self.progress.emit("Training")

    def _watch(self) -> None:
        self._typical = self._kind.typical_seconds()
        self._queue.watch_training(self)
        self._timer.start(POLL_MS)

    def _look(self) -> None:
        if self._trainer is None:
            if self.holds_the_line:
                if self._queue.making_something():
                    return
                self._queue.free_comfyui_memory()
            self._start()
            return
        alive = self._trainer.running()
        status = self._status = lora_training.read_status(self._job) or self._status
        if not alive:
            logger.info("Training %s: its program ended, saying %s", self.caption, status)
        if status.get("state") == "done":
            self._end(self._outcome(ok=True))
            self.finished.emit(status["lora"])
        elif status.get("state") == "failed":
            self._fail(status["message"])
        elif not alive:
            self._fail("The training program quit without saying why. An agent can read "
                       f"what it printed in {self._job['log']}.")
        else:
            word = self._stage()[0]
            if status.get("total"):
                word = f"{word} {round(100 * status['done'] / status['total'])}%"
            self.progress.emit(word)

    def _start(self) -> None:
        try:
            self._trainer = self._kind.start(self._job)
        except Exception as error:
            logger.exception("Training %s could not be started", self.caption)
            self._fail(f"The training couldn't be started: {error}")
            return
        self.progress.emit(self._stage()[0])

    def cancel(self) -> None:
        if self._trainer is not None:
            self._trainer.stop()
        logger.info("Training %s: canceled", self.caption)
        self._end(None)
        self.canceled.emit()

    def _outcome(self, *, ok: bool) -> RunOutcome:
        return lora_training.outcome_of(
            self._job, ok=ok,
            seconds=None if self._trainer is None else lora_training.time_taken(self._job, self._trainer))

    def _fail(self, why: str) -> None:
        self._end(self._outcome(ok=False))
        self.failed.emit(why)

    def _end(self, outcome: RunOutcome | None) -> None:
        self._timer.stop()
        self.ended.emit(outcome)
