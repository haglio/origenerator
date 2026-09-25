"""Off-UI-thread reading + rewrite of one thing that was said.

A :class:`VoiceWorker` turns the words of one utterance into a command or an
edited prompt: the rewrite (local LLM) is an injected callable, so the pipeline
unit-tests inline. :class:`ProcessTask` runs one such call on the global thread
pool; the worker's signals carry the result back to the UI thread that owns it.
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot

logger = logging.getLogger(__name__)


class VoiceWorker(QObject):
    rewritten = pyqtSignal(object)  # the revised {positive, negative} pair
    failed = pyqtSignal(str)      # a human-readable reason (nothing heard, no server, …)
    heard = pyqtSignal(str)       # what was said, for on-screen feedback
    command = pyqtSignal(object)  # a recognized spoken command's matched value

    def __init__(self, rewrite_fn, parent=None):
        super().__init__(parent)
        self._rewrite = rewrite_fn

    @pyqtSlot(object, object, object)
    def process(self, instruction, prompts, match_command=None) -> None:
        """Read ``instruction``; a recognized command (``match_command`` says)
        emits ``command`` and ends the matter, else the instruction rewrites the
        ``prompts`` pair ({positive, negative}) and the revised pair or a failure
        is emitted. ``prompts`` is ``None`` while nothing is steering — command
        listening alone must never invent a rewrite. Runs on a pool thread;
        never raises."""
        try:
            self.heard.emit(instruction)
            if not any(char.isalpha() for char in instruction):  # '', '. . . .', noise
                self.failed.emit("Didn't catch that.")
                return
            if match_command is not None:
                matched = match_command(instruction)
                if matched is not None:
                    self.command.emit(matched)
                    return
            if prompts is None:
                return  # listening for commands alone, and this wasn't one
            new_positive, new_negative = self._rewrite(
                prompts.get("positive", ""), prompts.get("negative", ""), instruction)
            self.rewritten.emit({"positive": new_positive, "negative": new_negative})
        except Exception as exc:
            self.failed.emit(str(exc))


class ProcessTask(QRunnable):
    """Runs one ``VoiceWorker.process`` off the UI thread. The worker's signals
    carry the result back — delivered (queued) to the thread that owns the worker."""

    def __init__(self, worker: VoiceWorker, instruction, prompts, match_command=None):
        super().__init__()
        self._worker = worker
        self._instruction = instruction
        self._prompts = prompts
        self._match_command = match_command

    def run(self):
        try:
            self._worker.process(self._instruction, self._prompts, self._match_command)
        except RuntimeError:
            logger.info("An utterance came back after the app let go of its worker")
