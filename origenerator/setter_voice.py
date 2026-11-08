from __future__ import annotations

from typing import NamedTuple

from origenerator.action_vocabulary import Vocabulary, said_as, vocabulary
from origenerator.media import MediaType
from origenerator.voice.text import words

PRESS, SKIP, SAME, UNDO, TRASH = "press", "skip", "same", "undo", "trash"

_UNDER_THE_BUTTONS: dict[str, str] = {
    "skip": SKIP, "same": SAME, "same as last": SAME, "undo": UNDO, "trash": TRASH,
}


class Heard(NamedTuple):
    does: str
    button: str = ""


class SetterWords(NamedTuple):
    meanings: dict[str, Heard]

    @property
    def phrases(self) -> frozenset[str]:
        return frozenset(self.meanings)

    def heard(self, text: str) -> Heard | None:
        return self.meanings.get(" ".join(words(text)))


def setter_words(named: Vocabulary) -> SetterWords:
    meanings = {said: Heard(does) for said, does in _UNDER_THE_BUTTONS.items()}
    for button in named.buttons:
        meanings.update({form: Heard(PRESS, button) for form in named.spoken_forms(said_as(button))
                         if form not in _UNDER_THE_BUTTONS})
    return SetterWords(meanings)


def setter_phrases() -> frozenset[str]:
    return frozenset().union(*(setter_words(vocabulary(side)).phrases
                               for side in (MediaType.IMAGE, MediaType.VIDEO)))
