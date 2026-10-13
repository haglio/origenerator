"""Spoken control of the fullscreen slideshow: get it going, pause it, close it.

Three things to say, because three are what a slideshow has: **start** it (or resume
one sitting at nought), **pause** it, **stop** it. Each is a verb plus the word
"slideshow", which is what keeps them clear of prompt steering — the same mic is
often rewriting a prompt, and an utterance this doesn't claim falls through to
become a prompt edit. "start slideshow" is not a sentence anyone types at an
image generator, so the pairing is safe to match on.

Pausing is a pace of nought, not a fourth state: a slideshow that never moves on is a
picture on the screen, which is the whole reason there is no separate full-screen
viewer any more. So "pause slideshow" turns the clip-seconds pace to nought and
"start slideshow" turns it back to the standard number — the same pair Genau's
console steps by hand, spoken.

Whisper's own renderings are what these are matched against, so "slide show"
arrives as two words about as often as one, and punctuation and case are its to
choose. :func:`slideshow_command_phrases` is what the recognizer is asked to hear, the
slideshow named both ways.
"""
from __future__ import annotations

from enum import Enum

from origenerator.voice.text import words


class SlideshowCommand(Enum):
    """What a spoken utterance asked of the slideshow."""

    START = "start"   # open one if none is up, and set the pace to the standard
    PAUSE = "pause"   # stop on what is on screen: the pace goes to nought
    STOP = "stop"     # close it


# The verbs, as said. Each maps to the one thing it asks for; anything else
# beside "slideshow" is not a command and falls through to prompt steering.
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
# sentence-shaped that happens to mention a slideshow is a prompt edit.
_MAX_COMMAND_WORDS = 6


def _names_the_slideshow(words: list) -> bool:
    """Whether these words name the slideshow — as one word or as the two
    whisper splits it into about as often."""
    return "slideshow" in words or any(
        first == "slide" and second == "show"
        for first, second in zip(words, words[1:])
    )


def match_slideshow_command(text: str) -> SlideshowCommand | None:
    """What a spoken utterance asks of the slideshow, or ``None`` when it isn't asking.

    Both halves are required — a verb this table knows and the word "slideshow" —
    so "stop" alone (which could be anything) and "a slideshow of her" (which is
    a prompt) are both left to fall through.
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
