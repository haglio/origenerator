"""The push-to-talk mic button and the worker that turns speech into a prompt edit.

Holding the button records; releasing it hands the audio to a :class:`VoiceWorker`
that transcribes it (faster-whisper) and rewrites the current prompt with a local
LLM. In the app that work runs on the global thread pool so the UI never blocks;
the worker's signals carry the result back to the UI thread. The worker takes its
transcribe and rewrite steps as plain callables, and tests inject it so the whole
pipeline runs inline — no mic, model, server, or background thread.
"""

from functools import partial

from PyQt6.QtCore import QObject, QRunnable, QSize, QThreadPool, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QHBoxLayout, QToolButton, QWidget

from origenerator import config
from origenerator.gui import icons
from origenerator.voice.recorder import Recorder
from origenerator.voice.rewrite import rewrite_prompt
from origenerator.voice.transcribe import Transcriber


class VoiceWorker(QObject):
    rewritten = pyqtSignal(str)   # the revised prompt
    failed = pyqtSignal(str)      # a human-readable reason (nothing heard, no server, …)
    busy = pyqtSignal(bool)       # work started / finished, for the button's state

    def __init__(self, transcribe_fn, rewrite_fn, parent=None):
        super().__init__(parent)
        self._transcribe = transcribe_fn
        self._rewrite = rewrite_fn

    @pyqtSlot(object, str)
    def process(self, audio, current_prompt: str) -> None:
        """Transcribe ``audio`` and apply it to ``current_prompt``, emitting the new
        prompt or a failure. Runs on a pool thread; never raises."""
        self.busy.emit(True)
        try:
            instruction = self._transcribe(audio)
            if not instruction.strip():
                self.failed.emit("Didn't catch that — try again.")
                return
            self.rewritten.emit(self._rewrite(current_prompt, instruction))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.busy.emit(False)


class _ProcessTask(QRunnable):
    """Runs one transcribe+rewrite off the UI thread. The worker's signals carry
    the result back — delivered (queued) to the UI thread that owns the worker."""

    def __init__(self, worker: VoiceWorker, audio, prompt: str):
        super().__init__()
        self._worker = worker
        self._audio = audio
        self._prompt = prompt

    def run(self):
        self._worker.process(self._audio, self._prompt)


class VoiceButton(QWidget):
    """A hold-to-talk mic button that edits the current prompt by voice.

    ``get_prompt``/``set_prompt`` read and write the field it steers; ``on_error``
    (optional) surfaces failures. In the app the transcribe+rewrite runs on the
    global thread pool so the UI never blocks; tests inject a worker and it runs
    inline, exercising the whole pipeline synchronously.
    """

    def __init__(self, get_prompt, set_prompt, *, recorder=None, worker=None,
                 on_error=None, parent=None):
        super().__init__(parent)
        self._get_prompt = get_prompt
        self._set_prompt = set_prompt
        self._on_error = on_error or (lambda _message: None)
        self._recorder = recorder if recorder is not None else Recorder()
        self._recording = False
        self._async = worker is None  # real worker runs on the pool; an injected one inline
        self._worker = worker if worker is not None else self._build_worker()
        self._worker.rewritten.connect(self._on_rewritten)
        self._worker.failed.connect(self._on_failed)
        self._worker.busy.connect(self._on_busy)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._button = QToolButton()
        self._button.setObjectName("iconButton")
        self._button.setIcon(icons.mic_icon())
        self._button.setIconSize(QSize(16, 16))
        self._button.setToolTip("Hold and speak to edit the prompt")
        self._button.pressed.connect(self._start)
        self._button.released.connect(self._stop)
        layout.addWidget(self._button)

    def _build_worker(self) -> VoiceWorker:
        return VoiceWorker(
            Transcriber().transcribe,
            partial(
                rewrite_prompt,
                base_url=config.LOCAL_LLM_BASE_URL, model=config.LOCAL_LLM_MODEL,
                system_prompt=config.VOICE_REWRITE_SYSTEM_PROMPT,
            ),
        )

    # --- recording ---------------------------------------------------------

    def _start(self):
        try:
            self._recorder.start()
            self._recording = True
            self._button.setToolTip("Listening… release to apply")
        except Exception as exc:  # a missing mic or absent audio backend
            self._recording = False
            self._on_failed(str(exc))

    def _stop(self):
        if not self._recording:
            return
        self._recording = False
        self._button.setToolTip("Hold and speak to edit the prompt")
        try:
            audio = self._recorder.stop()
        except Exception as exc:
            self._on_failed(str(exc))
            return
        if audio is not None:
            self._submit(audio, self._get_prompt())

    def _submit(self, audio, prompt: str):
        if self._async:
            QThreadPool.globalInstance().start(_ProcessTask(self._worker, audio, prompt))
        else:
            self._worker.process(audio, prompt)

    # --- worker outcomes ---------------------------------------------------

    def _on_rewritten(self, new_prompt: str):
        self._set_prompt(new_prompt)

    def _on_failed(self, message: str):
        self._on_error(message)

    def _on_busy(self, busy: bool):
        self._button.setEnabled(not busy)  # ignore holds while transcribing/rewriting
