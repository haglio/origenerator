"""Off-UI-thread transcribe + rewrite for a captured utterance.

A :class:`VoiceWorker` turns one audio utterance into an edited prompt: it
transcribes (faster-whisper) and rewrites (local LLM) via injected callables, so
the pipeline unit-tests inline. :class:`ProcessTask` runs one such call on the
global thread pool; the worker's signals carry the result back to the UI thread
that owns it.
"""

import logging

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot

logger = logging.getLogger(__name__)


class VoiceWorker(QObject):
    rewritten = pyqtSignal(object)  # the revised {positive, negative} pair
    failed = pyqtSignal(str)      # a human-readable reason (nothing heard, no server, …)
    busy = pyqtSignal(bool)       # work started / finished
    heard = pyqtSignal(str)       # the raw transcription, for on-screen feedback

    def __init__(self, transcribe_fn, rewrite_fn, parent=None):
        super().__init__(parent)
        self._transcribe = transcribe_fn
        self._rewrite = rewrite_fn

    @pyqtSlot(object, object)
    def process(self, audio, prompts) -> None:
        """Transcribe ``audio`` and apply it to the ``prompts`` pair
        ({positive, negative}), emitting the revised pair or a failure. Runs on a
        pool thread; never raises."""
        self.busy.emit(True)
        try:
            instruction = self._transcribe(audio)
            logger.info("Voice: transcribed %r", instruction)
            self.heard.emit(instruction)
            if not any(char.isalpha() for char in instruction):  # '', '. . . .', noise
                self.failed.emit("Didn't catch that.")
                return
            new_positive, new_negative = self._rewrite(
                prompts.get("positive", ""), prompts.get("negative", ""), instruction)
            self.rewritten.emit({"positive": new_positive, "negative": new_negative})
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.busy.emit(False)


class ProcessTask(QRunnable):
    """Runs one ``VoiceWorker.process`` off the UI thread. The worker's signals
    carry the result back — delivered (queued) to the thread that owns the worker."""

    def __init__(self, worker: VoiceWorker, audio, prompts):
        super().__init__()
        self._worker = worker
        self._audio = audio
        self._prompts = prompts

    def run(self):
        self._worker.process(self._audio, self._prompts)
