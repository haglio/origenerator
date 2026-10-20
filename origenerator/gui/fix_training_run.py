"""One fix's LoRA being trained, from the Train button to the LoRA it made.

The trainer needs the graphics card to itself, so nothing new is handed to
ComfyUI while it runs: it waits for what ComfyUI is making, has ComfyUI let go
of its models, and lets the queue go again when it ends either way."""

from __future__ import annotations

from pathlib import PureWindowsPath

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from origenerator import fix_training

POLL_MS = 2000


class FixTrainingRun(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, job: dict, queue, parent=None):
        super().__init__(parent)
        self._job = job
        self._queue = queue
        self._trainer = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)

    def begin(self) -> None:
        self._queue.hold_for_training(True)
        self.progress.emit("Waiting")
        self._timer.start(POLL_MS)
        self._step()

    def _step(self) -> None:
        if self._trainer is None:
            if not self._queue.making_something():
                self._queue.free_comfyui_memory()
                self._trainer = fix_training.start(self._job)
                self.progress.emit("Training")
            return
        status = fix_training.read_status(self._job) or {}
        if status.get("state") == "done":
            self._end()
            self.finished.emit(str(PureWindowsPath("fixes") / status["lora"]))
        elif status.get("state") == "failed" or self._trainer.poll() is not None:
            self._end()
            self.failed.emit(status.get("message") or "The training stopped.")
        elif status.get("total"):
            done = round(100 * status["done"] / status["total"])
            word = "Cropping" if status["state"] == "cropping" else "Training"
            self.progress.emit(f"{word} {done}%")

    def _end(self) -> None:
        self._timer.stop()
        self._queue.hold_for_training(False)
