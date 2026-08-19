"""Always-listening prompt steering for voice-driven auto-generate.

While active, the mic stays open (:class:`~origenerator.voice.listener.Listener`)
and each endpointed utterance is transcribed and used to rewrite the prompt the
caller exposes via ``get_prompt``, written back through ``set_prompt``. The
transcribe+rewrite runs on the global thread pool so audio callbacks and the UI
never block. The listener and worker are injectable, so the flow tests inline
without a mic, a model, or a server.

The same mic also serves spoken commands (:meth:`VoiceSteering.start_commands`):
while a fullscreen surface is up, an utterance the injected matcher recognizes —
"fix teeth" — is executed instead of becoming a prompt edit. The two uses share
the one listener and run independently: commands alone keep the mic open with no
loop steering, and with both active a matched command is consumed as a command,
never a rewrite.

A third use rides above both: an injected
:class:`~origenerator.voice.dictation.RequestDictation` gets first refusal on
every transcription for as long as the mic is open at all, so "Request … over"
can be said wherever it is heard rather than only over a fullscreen surface.
While one is open it swallows what it hears — which is exactly what keeps the
words of a request from steering the prompt or matching a command — and each
step of it is re-emitted as :attr:`VoiceSteering.request`.

One thing outranks even that, and only while no request is open: an injected
``bare_matcher``, the strict whole-utterance vocabulary
(:mod:`origenerator.voice.app_commands`). A word that IS a command, whole and
alone, is a command — which is what lets "requests" reach the Requests shelf
though "request" is the word a dictation opens on. Once one is open the
dictation is back in front, because a command word said mid-sentence belongs to
the sentence.

"""

import logging
import threading
from functools import partial

from PyQt6.QtCore import QObject, QThreadPool, pyqtSignal

from origenerator import config
from origenerator.voice.dictation import SpokenRequest
from origenerator.voice.listener import Listener
from origenerator.voice.rewrite import rewrite_prompt
from origenerator.voice.transcribe import Transcriber
from origenerator.voice.worker import ProcessTask, VoiceWorker

logger = logging.getLogger(__name__)


class VoiceSteering(QObject):
    edited = pyqtSignal(str)   # applied a revised prompt
    error = pyqtSignal(str)    # a mic/transcribe/rewrite failure, for the caller to surface
    heard = pyqtSignal(str)    # the raw transcription (re-emitted from the worker)
    request = pyqtSignal(object)  # a SpokenRequest: one step of "Request … over"

    def __init__(self, *, listener=None, worker=None, command_matcher=None,
                 bare_matcher=None, dictation=None, transcribe_bias=None,
                 parent=None):
        super().__init__(parent)
        self._listener = listener if listener is not None else Listener(
            floor=config.VOICE_VAD_THRESHOLD
        )
        self._async = worker is None  # a real worker runs on the pool; an injected one inline
        self._transcribe_bias = transcribe_bias  # before _build_worker, which hands it on
        self._transcriber = None  # set when building the real worker, for preloading
        self._worker = worker if worker is not None else self._build_worker()
        self._get_prompts = None
        self._set_prompts = None
        self._matcher = command_matcher  # recognizes a spoken command in a transcription
        # The whole-utterance half of that vocabulary, which is strict enough to
        # be asked before a request can open (see the module docstring).
        self._bare_matcher = bare_matcher
        self._execute_command = None     # runs one, while a surface is listening for them
        self._dictation = dictation      # collects "Request … over" across utterances
        # Utterances are transcribed on the pool, so two can finish at once; the
        # dictation is the one piece of state here that a second one could walk
        # into mid-update.
        self._lock = threading.Lock()
        self._listener.utterance.connect(self._on_utterance)
        self._worker.rewritten.connect(self._on_rewritten)
        self._worker.failed.connect(self.error)
        self._worker.heard.connect(self.heard)  # re-emit for on-screen feedback
        self._worker.command.connect(self._on_command)

    def _build_worker(self) -> VoiceWorker:
        self._transcriber = Transcriber(prompt_bias=self._transcribe_bias)
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
        self._listen()

    def start_commands(self, execute) -> None:
        """Begin listening for spoken commands: an utterance the matcher
        recognizes calls ``execute`` with what it matched. Independent of
        steering — this alone keeps the mic open, and alongside a steered loop
        a matched command is consumed rather than rewriting the prompt."""
        self._execute_command = execute
        self._listen()

    def _listen(self) -> None:
        if self._transcriber is not None:  # warm the model now, not on the 1st command
            threading.Thread(target=self._preload, daemon=True).start()
        try:
            self._listener.start()  # already-open mics stay as they are
        except Exception as exc:  # no mic or no audio backend
            logger.warning("Voice: the mic could not be opened: %s", exc)
            self.error.emit(f"mic unavailable — {exc}")

    def _preload(self) -> None:
        try:
            self._transcriber.preload()
        except Exception as exc:
            logger.warning("Voice: whisper preload failed: %s", exc)

    def stop(self) -> None:
        self._get_prompts = None  # a late utterance after stop is then ignored
        self._set_prompts = None
        if self._execute_command is None:  # commands may still want the mic
            self._close_mic()

    def stop_commands(self) -> None:
        self._execute_command = None
        if self._get_prompts is None:  # steering may still want the mic
            self._close_mic()

    def _close_mic(self) -> None:
        """Shut the mic and drop any half-said request with it — one nobody can
        finish saying must not be waiting the next time it opens."""
        self._listener.stop()
        if self._dictation is not None:
            with self._lock:
                self._dictation.reset()

    def _on_utterance(self, audio) -> None:
        if self._get_prompts is None and self._execute_command is None:
            return
        prompts = self._get_prompts() if self._get_prompts is not None else None
        logger.info("Voice: processing utterance (positive %r)",
                    (prompts or {}).get("positive"))
        if self._async:
            QThreadPool.globalInstance().start(
                ProcessTask(self._worker, audio, prompts, self._interpret))
        else:
            self._worker.process(audio, prompts, self._interpret)

    def _interpret(self, text: str):
        """What one transcription meant, or ``None`` to let it steer the prompt.

        An utterance that is nothing but a command word is that command, so long
        as no request is already being said — that is the one thing ahead of the
        dictation, and it is what keeps a shelf named by the dictation's own
        opening word reachable. Then the open dictation, which has first refusal
        over everything else because it is collecting a sentence and half of one
        landing in the prompt would be worse than either use alone. Then the
        general command matcher, which only answers while a surface is listening
        for commands.
        """
        with self._lock:
            collecting = self._dictation is not None and self._dictation.listening
            if not collecting and self._listening_for_commands():
                bare = self._bare_matcher(text) if self._bare_matcher is not None else None
                if bare is not None:
                    return bare
            spoken = self._dictation.push(text) if self._dictation is not None else None
        if spoken is not None:
            return spoken
        if self._listening_for_commands() and self._matcher is not None:
            return self._matcher(text)
        return None

    def _listening_for_commands(self) -> bool:
        """Whether a surface is up that spoken commands run against."""
        return self._execute_command is not None

    def _on_command(self, matched) -> None:
        if isinstance(matched, SpokenRequest):
            logger.info("Voice: request %s -> %r", matched.state, matched.text)
            self.request.emit(matched)
            return
        logger.info("Voice: command -> %r", matched)
        if self._execute_command is not None:
            self._execute_command(matched)

    def _on_rewritten(self, new_prompts) -> None:
        logger.info("Voice: rewrote -> %r", new_prompts)
        if self._set_prompts is not None:
            self._set_prompts(new_prompts)
            self.edited.emit(new_prompts.get("positive", ""))
