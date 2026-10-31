"""Spoken control of the fullscreen slideshow: get it going, pause it, close it.

Three things to say: **start** it, **pause** it, **stop** it. Each is a verb plus the word
"slideshow", which is what keeps them clear of the sentences the same mic hears:
"start slideshow" is not a sentence anyone says by chance, so the pairing is
safe to match on.

Whisper's own renderings are what these are matched against, so "slide show"
arrives as two words about as often as one, and punctuation and case are its to
choose. :func:`slideshow_command_phrases` is what the recognizer is asked to hear, the
slideshow named both ways.
"""
from __future__ import annotations

from enum import Enum
from itertools import pairwise

from origenerator.voice.text import words


class SlideshowCommand(Enum):
    """What a spoken utterance asked of the slideshow."""

    START = "start"   # play the room, and open one or set it going at the standard pace
    PAUSE = "pause"   # pause the room, as Esc does
    STOP = "stop"     # close it


# The verbs, as said. Each maps to the one thing it asks for; anything else
# beside "slideshow" is not a command.
_VERBS = {
    "start": SlideshowCommand.START,
    "play": SlideshowCommand.START,
    "open": SlideshowCommand.START,
    "pause": SlideshowCommand.PAUSE,
    "stop": SlideshowCommand.STOP,
    "end": SlideshowCommand.STOP,
    "close": SlideshowCommand.STOP,
}

# A command is a few words — "start the slideshow, please" — while anything
# sentence-shaped that happens to mention a slideshow is no command.
_MAX_COMMAND_WORDS = 6


def _names_the_slideshow(words: list) -> bool:
    """Whether these words name the slideshow — as one word or as the two
    whisper splits it into about as often."""
    return "slideshow" in words or any(
        first == "slide" and second == "show"
        for first, second in pairwise(words)
    )


def match_slideshow_command(text: str) -> SlideshowCommand | None:
    """What a spoken utterance asks of the slideshow, or ``None`` when it isn't asking.

    Both halves are required — a verb this table knows and the word "slideshow" —
    so "stop" alone (which could be anything) and "a slideshow of her" (which is
    a sentence) are both left alone.
    """
    heard = words(text)
    if not heard or len(heard) > _MAX_COMMAND_WORDS or not _names_the_slideshow(heard):
        return None
    for word in heard:
        command = _VERBS.get(word)
        if command is not None:
            return command
    return None


def slideshow_command_phrases() -> frozenset[str]:
    """Each verb with the slideshow named after it, as one word and as the two it is as often
    heard as."""
    return frozenset(f"{verb} {name}" for verb in _VERBS for name in ("slideshow", "slide show"))
