"""What the microphone hears: a spoken command, a spoken request, or nothing.

While a surface listens for commands the mic stays open
(:class:`~origenerator.voice.hearing.Hearing`), and an utterance the injected
matcher recognizes -- "fix teeth" -- is executed. Anything else does nothing.

An injected :class:`~origenerator.voice.dictation.RequestDictation` gets first
refusal on every transcription, so "Request … over" can be said wherever it is
heard. While one is open it swallows what it hears -- which keeps the words of a
request from matching a command -- and each step of it is re-emitted as
:attr:`CommandAndRequestListener.request`.

One thing outranks even that, and only while no request is open: an injected
``bare_matcher``, the strict whole-utterance vocabulary
(:mod:`origenerator.voice.app_commands`). A word that IS a command, whole and
alone, is a command -- which is what lets "requests" reach the Requests collection
though "request" is the word a dictation opens on. Once one is open the
dictation is back in front, because a command word said mid-sentence belongs to
the sentence.
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, pyqtSignal

from origenerator.voice.dictation import SpokenRequest
from origenerator.voice.hearing import Hearing

logger = logging.getLogger(__name__)


class CommandAndRequestListener(QObject):
    error = pyqtSignal(str)    # a mic that failed, or a sound with no words in it
    heard = pyqtSignal(str)    # what was said
    request = pyqtSignal(object)  # a SpokenRequest: one step of "Request … over"

    def __init__(self, *, hearing=None, command_matcher=None, bare_matcher=None,
                 dictation=None, phrases=(), never_repaired=(), said_in=None,
                 parent=None):
        super().__init__(parent)
        # *phrases* is the vocabulary said outright, which the mic hears fast and
        # exactly; everything else reaches the same matchers as a sentence taken down.
        self._hearing = hearing if hearing is not None else Hearing(
            phrases, never_repaired=never_repaired, said_in=said_in)
        self._matcher = command_matcher
        self._bare_matcher = bare_matcher
        self._execute_command = None
        self._dictation = dictation
        self._hearing.said.connect(self._on_said)
        self._hearing.failed.connect(
            lambda reason: self.error.emit(f"mic unavailable — {reason}"))

    def start_commands(self, execute) -> None:
        """Open the mic: an utterance the matcher recognizes calls ``execute``
        with what it matched."""
        self._execute_command = execute
        self._hearing.start()  # an already-open mic stays as it is

    def stop_commands(self) -> None:
        """Shut the mic and drop any half-said request with it -- one nobody can
        finish saying must not be waiting the next time it opens."""
        self._execute_command = None
        self._hearing.stop()
        self.drop_the_request()

    def bare_command(self, text: str):
        """The whole-utterance command *text* is, or ``None`` -- asked first, and
        only while no request is being said, of what this app's own mic heard
        and of what the HOSTING session heard alike. Without it the session's
        "enhanced only" reached the looser picture matcher, which reads it as
        "enhance" with a word after it and spends a generation on it.
        """
        if self._bare_matcher is None or self.taking_a_request:
            return None
        return self._bare_matcher(text)

    def push_dictation(self, text: str):
        """Feed the open request one transcription, and answer what it meant
        (``None`` when it is not part of a request).

        Hosted inside a Fun Time session this app's mic is shut -- the session
        hears for the whole room and posts what it heard on this app's channel --
        so the words of a request arrive here from there, into the same dictation:
        half a request must never be held in one place and half in another.
        """
        return self._dictation.push(text) if self._dictation is not None else None

    @property
    def taking_a_request(self) -> bool:
        return self._dictation is not None and self._dictation.listening

    def drop_the_request(self) -> None:
        if self._dictation is not None:
            self._dictation.reset()

    def _on_said(self, text: str) -> None:
        if self._execute_command is None:
            return  # a late utterance after the mic was shut
        self.heard.emit(text)
        if not any(char.isalpha() for char in text):  # '', '. . . .', noise
            self.error.emit("Didn't catch that.")
            return
        meaning = self._meaning(text)
        length = len(text.split())
        if isinstance(meaning, SpokenRequest):
            logger.info("Voice: request %s", meaning.state.value)
            self.request.emit(meaning)
        elif meaning is not None:
            logger.info("Voice: a %d-word utterance matched %r", length, meaning)
            self._execute_command(meaning)
        else:
            logger.info("Voice: a %d-word utterance matched no command", length)

    def _meaning(self, text: str):
        """What one transcription meant, or ``None`` for nothing at all.

        A whole-utterance command first, then the dictation, which has first
        refusal over everything else because it is collecting a sentence, then
        the general command matcher.
        """
        bare = self.bare_command(text)
        if bare is not None:
            return bare
        spoken = self.push_dictation(text)
        if spoken is not None:
            return spoken
        return self._matcher(text) if self._matcher is not None else None
