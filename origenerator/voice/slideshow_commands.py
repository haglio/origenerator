from __future__ import annotations

from enum import Enum
from itertools import pairwise

from origenerator.voice.text import words


class SlideshowCommand(Enum):
    START = "start"
    PAUSE = "pause"
    STOP = "stop"


_VERBS = {
    "start": SlideshowCommand.START,
    "play": SlideshowCommand.START,
    "open": SlideshowCommand.START,
    "pause": SlideshowCommand.PAUSE,
    "stop": SlideshowCommand.STOP,
    "end": SlideshowCommand.STOP,
    "close": SlideshowCommand.STOP,
}

_MAX_COMMAND_WORDS = 6


def _names_the_slideshow(words: list) -> bool:
    return "slideshow" in words or any(
        first == "slide" and second == "show"
        for first, second in pairwise(words)
    )


def match_slideshow_command(text: str) -> SlideshowCommand | None:
    heard = words(text)
    if not heard or len(heard) > _MAX_COMMAND_WORDS or not _names_the_slideshow(heard):
        return None
    for word in heard:
        command = _VERBS.get(word)
        if command is not None:
            return command
    return None


def slideshow_command_phrases() -> frozenset[str]:
    return frozenset(f"{verb} {name}" for verb in _VERBS for name in ("slideshow", "slide show"))
