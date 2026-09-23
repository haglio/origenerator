"""The microphone, as text.

Hearing is voice_core's, the listener every app in the family runs. What is this
app's is which of its two roads an utterance takes: a phrase of the vocabulary said
outright arrives as that phrase, fast; anything else is a sentence, taken down word
for word. Both arrive as the same signal, so everything downstream reads one text.
"""
from __future__ import annotations

from collections.abc import Collection

from PyQt6.QtCore import QObject, pyqtSignal
from voice_core.commands import CommandRules
from voice_core.listener import (
    CommandListener,
    Engines,
    ListenerEvents,
    ListenerSettings,
)
from voice_core.listening import Heard
from voice_core.listening_thread import ListeningThread
from voice_core.whisper_reader import WhisperReader

from origenerator import config
from origenerator.voice.dictation import request_bias

# A sound this loud with no words in it is answered ("Didn't catch that."); a quieter one is
# let go. The pause detector is ten times as sensitive as the one this app had, which is
# what lets his quiet words through -- over a sample of his recorded dictation 49 sentences
# arrived where 39 had -- and answering every quiet nothing as well would have flashed the
# caption 91 times where it had flashed 34.
LOUD_ENOUGH_TO_ANSWER = 1000


class Hearing(QObject):
    said = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, phrases: Collection[str], *, never_repaired: Collection[str] = (),
                 engines: Engines | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rules = CommandRules(phrases=frozenset(phrases),
                                   never_rescued=frozenset(never_repaired).__contains__)
        self._engines = engines
        self._thread = ListeningThread(
            self._listener, failed=lambda exc: self.failed.emit(str(exc) or type(exc).__name__))

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._thread.stop()

    def _listener(self) -> CommandListener:
        return CommandListener(
            self._rules,
            ListenerSettings(model_name=config.VOICE_MODEL_NAME,
                             device_name=config.VOICE_DEVICE_NAME, speech_hint=request_bias()),
            ListenerEvents(heard=self._on_heard, speech=self._on_speech),
            self._engines or Engines(second_opinion=WhisperReader(),
                                     take_down=WhisperReader(for_dictation=True)))

    def _on_heard(self, heard: Heard) -> None:
        if heard.recognition.phrase:
            self.said.emit(heard.recognition.phrase)

    def _on_speech(self, words: str, heard: Heard) -> None:
        if heard.peak >= LOUD_ENOUGH_TO_ANSWER or any(character.isalpha() for character in words):
            self.said.emit(words)
