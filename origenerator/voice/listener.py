from __future__ import annotations

import logging
from typing import NamedTuple

from PyQt6.QtCore import QObject, pyqtSignal

from origenerator.voice.dictation import SpokenRequest
from origenerator.voice.hearing import Hearing

logger = logging.getLogger(__name__)


class Phrases(NamedTuple):
    heard: object = ()
    never_repaired: object = ()
    said_in: object = None


class CommandAndRequestListener(QObject):
    error = pyqtSignal(str)
    heard = pyqtSignal(str)
    request = pyqtSignal(object)

    def __init__(self, *, hearing=None, command_matcher=None, bare_matcher=None,
                 dictation=None, phrases: Phrases | None = None):
        super().__init__()
        phrases = phrases or Phrases()
        self._hearing = hearing if hearing is not None else Hearing(
            phrases.heard, never_repaired=phrases.never_repaired, said_in=phrases.said_in)
        self._matcher = command_matcher
        self._bare_matcher = bare_matcher
        self._execute_command = None
        self._dictation = dictation
        self._hearing.said.connect(self._on_said)
        self._hearing.failed.connect(self._on_failed)

    def start_commands(self, execute) -> None:
        self._execute_command = execute
        self._hearing.start()

    def stop_commands(self) -> None:
        self._execute_command = None
        self._hearing.stop()
        self.drop_the_request()

    def close(self) -> None:
        self.stop_commands()
        self._hearing.close()

    def bare_command(self, text: str):
        return self._bare_matcher(text) if self._bare_matcher is not None else None

    def push_dictation(self, text: str, spoken_at: float | None = None):
        return (self._dictation.push(text, spoken_at=spoken_at)
                if self._dictation is not None else None)

    @property
    def taking_a_request(self) -> bool:
        return self._dictation is not None and self._dictation.listening

    def drop_the_request(self) -> None:
        if self._dictation is not None:
            self._dictation.reset()

    def _on_failed(self, reason: str) -> None:
        message = f"mic unavailable — {reason}"
        logger.warning("Voice: %s", message)
        self.error.emit(message)

    def _on_said(self, text: str, spoken_at: float) -> None:
        if self._execute_command is None:
            return
        self.heard.emit(text)
        if not any(char.isalpha() for char in text):
            logger.info("Voice: a sound with no words in it")
            self.error.emit("Didn't catch that.")
            return
        meaning = self._meaning(text, spoken_at)
        length = len(text.split())
        if isinstance(meaning, SpokenRequest):
            logger.info("Voice: request %s", meaning.state.value)
            self.request.emit(meaning)
        elif meaning is not None:
            logger.info("Voice: a %d-word utterance matched %r", length, meaning)
            self._execute_command(meaning, spoken_at)
        else:
            logger.info("Voice: a %d-word utterance matched no command", length)

    def _meaning(self, text: str, spoken_at: float):
        spoken = self.push_dictation(text, spoken_at)
        if spoken is not None:
            return spoken
        bare = self.bare_command(text)
        if bare is not None:
            return bare
        return self._matcher(text) if self._matcher is not None else None
