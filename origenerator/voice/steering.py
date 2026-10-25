"""Always-listening prompt steering for voice-driven auto-generate.

While active, the mic stays open (:class:`~origenerator.voice.hearing.Hearing`)
and each thing said is used to rewrite the prompt the caller exposes via
``get_prompt``, written back through ``set_prompt``. The rewrite runs on the
global thread pool so the UI never blocks. The listener and worker are injectable,
so the flow tests inline without a mic, a model, or a server.

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

"""
from __future__ import annotations

import logging
import threading
from functools import partial
from typing import NamedTuple

from PyQt6.QtCore import QObject, QThreadPool, pyqtSignal

from origenerator import config
from origenerator.prompts import VOICE_REWRITE_SYSTEM_PROMPT
from origenerator.voice.dictation import SpokenRequest
from origenerator.voice.hearing import Hearing
from origenerator.voice.rewrite import rewrite_prompt
from origenerator.voice.worker import ProcessTask, VoiceWorker

logger = logging.getLogger(__name__)


class _SaidCommand(NamedTuple):
    command: object
    said_at: float


class VoiceSteering(QObject):
    edited = pyqtSignal(str)   # applied a revised prompt
    error = pyqtSignal(str)    # a mic/transcribe/rewrite failure, for the caller to surface
    heard = pyqtSignal(str)    # what was said (re-emitted from the worker)
    request = pyqtSignal(object)  # a SpokenRequest: one step of "Request … over"

    def __init__(self, *, listener=None, worker=None, command_matcher=None,
                 bare_matcher=None, dictation=None, phrases=(), never_repaired=(),
                 said_in=None, parent=None):
        super().__init__(parent)
        # *phrases* is the vocabulary said outright, which the listener hears fast and
        # exactly; everything else reaches the same matchers as a sentence taken down.
        self._listener = listener if listener is not None else Hearing(
            phrases, never_repaired=never_repaired, said_in=said_in)
        self._async = worker is None  # a real worker runs on the pool; an injected one inline
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
        self._listener.said.connect(self._on_said)
        self._listener.failed.connect(
            lambda reason: self.error.emit(f"mic unavailable — {reason}"))
        self._worker.rewritten.connect(self._on_rewritten)
        self._worker.failed.connect(self.error)
        self._worker.heard.connect(self.heard)  # re-emit for on-screen feedback
        self._worker.command.connect(self._on_command)

    def _build_worker(self) -> VoiceWorker:
        return VoiceWorker(
            partial(
                rewrite_prompt,
                base_url=config.LOCAL_LLM_BASE_URL, model=config.LOCAL_LLM_MODEL,
                system_prompt=VOICE_REWRITE_SYSTEM_PROMPT,
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
        recognizes calls ``execute`` with what it matched and when it was said. Independent of
        steering — this alone keeps the mic open, and alongside a steered loop
        a matched command is consumed rather than rewriting the prompt."""
        self._execute_command = execute
        self._listen()

    def _listen(self) -> None:
        self._listener.start()  # already-open mics stay as they are

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
        self.drop_the_request()

    def bare_command(self, text: str):
        """The whole-utterance command *text* is, or ``None`` — asked of a
        transcription the HOSTING session heard, the way :meth:`_meaning`
        asks it of this app's own mic: once the request has passed on it, and
        before the looser matchers.  Without this the session's "enhanced only"
        reached the looser picture matcher, which reads it as "enhance" with a
        word after it and spends a generation on it.
        """
        return self._bare_matcher(text) if self._bare_matcher is not None else None

    def push_dictation(self, text: str, spoken_at: float | None = None):
        """Feed the open request one transcription heard somewhere else, and
        answer what it meant (``None`` when it is not part of a request).

        Hosted inside a Fun Time session this app's mic is shut — the session
        hears for the whole room, its own commands and this app's alike, and
        posts what it heard on this app's channel — so the words of a request
        arrive there rather than through the listener.  They go to the same
        dictation under the same lock: the two sources never run at once, and
        half a request must never be held in one of them and half in the other.
        """
        with self._lock:
            return (self._dictation.push(text, spoken_at=spoken_at)
                    if self._dictation is not None else None)

    @property
    def taking_a_request(self) -> bool:
        with self._lock:
            return self._dictation is not None and self._dictation.listening

    def drop_the_request(self) -> None:
        if self._dictation is not None:
            with self._lock:
                self._dictation.reset()

    def _on_said(self, text: str, spoken_at: float) -> None:
        if self._get_prompts is None and self._execute_command is None:
            return
        prompts = self._get_prompts() if self._get_prompts is not None else None
        interpret = partial(self._interpret, steering=prompts is not None, spoken_at=spoken_at)
        if self._async:
            QThreadPool.globalInstance().start(
                ProcessTask(self._worker, text, prompts, interpret))
        else:
            self._worker.process(text, prompts, interpret)

    def _interpret(self, text: str, *, steering: bool, spoken_at: float):
        meaning = self._meaning(text, spoken_at)
        length = len(text.split())
        if isinstance(meaning, SpokenRequest):
            logger.info("Voice: request %s", meaning.state.value)
        elif meaning is not None:
            logger.info("Voice: a %d-word utterance matched %r", length, meaning)
        elif steering:
            logger.info("Voice: rewriting the prompt with a %d-word instruction", length)
        else:
            logger.info("Voice: a %d-word utterance matched no command", length)
        if meaning is None or isinstance(meaning, SpokenRequest):
            return meaning
        return _SaidCommand(meaning, spoken_at)

    def _meaning(self, text: str, spoken_at: float):
        """What one transcription meant, or ``None`` to let it steer the prompt.

        The dictation first, which has first refusal because it is collecting a
        sentence and half of one landing in the prompt would be worse than
        either use alone. Then, while a surface is listening for commands, the
        whole-utterance vocabulary and after it the general command matcher.
        """
        with self._lock:
            spoken = (self._dictation.push(text, spoken_at=spoken_at)
                      if self._dictation is not None else None)
        if spoken is not None:
            return spoken
        if not self._listening_for_commands():
            return None
        for matcher in (self._bare_matcher, self._matcher):
            matched = matcher(text) if matcher is not None else None
            if matched is not None:
                return matched
        return None

    def _listening_for_commands(self) -> bool:
        """Whether a surface is up that spoken commands run against."""
        return self._execute_command is not None

    def _on_command(self, matched) -> None:
        if isinstance(matched, SpokenRequest):
            self.request.emit(matched)
            return
        if self._execute_command is not None:
            self._execute_command(matched.command, matched.said_at)

    def _on_rewritten(self, new_prompts) -> None:
        logger.info("Voice: rewrote the prompt pair")
        if self._set_prompts is not None:
            self._set_prompts(new_prompts)
            self.edited.emit(new_prompts.get("positive", ""))
