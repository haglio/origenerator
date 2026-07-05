"""Always-listening prompt steering for voice-driven auto-generate.

While active, the mic stays open (:class:`~origenerator.voice.listener.Listener`)
and each endpointed utterance is transcribed and used to rewrite the prompt the
caller exposes via ``get_prompt``, written back through ``set_prompt``. The
transcribe+rewrite runs on the global thread pool so audio callbacks and the UI
never block. The listener and worker are injectable, so the flow tests inline
without a mic, a model, or a server.
"""

import logging
import threading
from functools import partial

from PyQt6.QtCore import QObject, QThreadPool, pyqtSignal

from origenerator import config
from origenerator.voice.listener import Listener
from origenerator.voice.rewrite import rewrite_prompt
from origenerator.voice.transcribe import Transcriber
from origenerator.voice.worker import ProcessTask, VoiceWorker

logger = logging.getLogger(__name__)


class VoiceSteering(QObject):
    edited = pyqtSignal(str)   # applied a revised prompt
    error = pyqtSignal(str)    # a mic/transcribe/rewrite failure, for the caller to surface
    heard = pyqtSignal(str)    # the raw transcription (re-emitted from the worker)

    def __init__(self, *, listener=None, worker=None, parent=None):
        super().__init__(parent)
        self._listener = listener if listener is not None else Listener(
            floor=config.VOICE_VAD_THRESHOLD
        )
        self._async = worker is None  # a real worker runs on the pool; an injected one inline
        self._transcriber = None  # set when building the real worker, for preloading
        self._worker = worker if worker is not None else self._build_worker()
        self._get_prompts = None
        self._set_prompts = None
        self._listener.utterance.connect(self._on_utterance)
        self._worker.rewritten.connect(self._on_rewritten)
        self._worker.failed.connect(self.error)
        self._worker.heard.connect(self.heard)  # re-emit for on-screen feedback

    def _build_worker(self) -> VoiceWorker:
        self._transcriber = Transcriber()
        return VoiceWorker(
            self._transcriber.transcribe,
            partial(
                rewrite_prompt,
                base_url=config.LOCAL_LLM_BASE_URL, model=config.LOCAL_LLM_MODEL,
                system_prompt=config.VOICE_REWRITE_SYSTEM_PROMPT,
            ),
        )

    def start(self, get_prompts, set_prompts) -> None:
        """Begin listening; each utterance rewrites ``get_prompts()`` (a {positive,
        negative} pair) via ``set_prompts``."""
        self._get_prompts = get_prompts
        self._set_prompts = set_prompts
        if self._transcriber is not None:  # warm the model now, not on the 1st command
            threading.Thread(target=self._preload, daemon=True).start()
        try:
            self._listener.start()
        except Exception as exc:  # no mic or no audio backend
            self.error.emit(str(exc))

    def _preload(self) -> None:
        try:
            self._transcriber.preload()
        except Exception as exc:
            logger.warning("Voice: whisper preload failed: %s", exc)

    def stop(self) -> None:
        self._listener.stop()
        self._get_prompts = None  # a late utterance after stop is then ignored
        self._set_prompts = None

    def _on_utterance(self, audio) -> None:
        if self._get_prompts is None:
            return
        prompts = self._get_prompts()
        logger.info("Voice: processing utterance (positive %r)", prompts.get("positive"))
        if self._async:
            QThreadPool.globalInstance().start(ProcessTask(self._worker, audio, prompts))
        else:
            self._worker.process(audio, prompts)

    def _on_rewritten(self, new_prompts) -> None:
        logger.info("Voice: rewrote -> %r", new_prompts)
        if self._set_prompts is not None:
            self._set_prompts(new_prompts)
            self.edited.emit(new_prompts.get("positive", ""))
