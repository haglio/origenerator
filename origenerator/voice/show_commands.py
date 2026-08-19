"""Spoken control of the fullscreen show: get it going, hold it, close it.

Three things to say, because three are what a show has: **start** it (or resume
one held at nought), **pause** it, **stop** it. Each is a verb plus the word
"slideshow", which is what keeps them clear of prompt steering — the same mic is
often rewriting a prompt, and an utterance this doesn't claim falls through to
become a prompt edit. "start slideshow" is not a sentence anyone types at an
image generator, so the pairing is safe to match on.

Pausing is a pace of nought, not a fourth state: a show that never moves on is a
picture on the screen, which is the whole reason there is no separate full-screen
viewer any more. So "pause slideshow" turns the clip-seconds pace to nought and
"start slideshow" turns it back to the standard number — the same pair Genau's
console steps by hand, spoken.

Whisper's own renderings are what these are matched against, so "slide show"
arrives as two words about as often as one, and punctuation and case are its to
choose. :func:`show_command_bias` hands the vocabulary to the transcriber up
front for the same reason the fix commands do it (see
:mod:`origenerator.workflows.detail_parts`): off a quiet mic a short imperative
comes back mangled, and telling whisper what to expect is what makes it land.
"""

import re
from enum import Enum


class ShowCommand(Enum):
    """What a spoken utterance asked of the show."""

    START = "start"   # open one if none is up, and set the pace to the standard
    PAUSE = "pause"   # hold what is on screen: the pace goes to nought
    STOP = "stop"     # close it


# The verbs, as said. Each maps to the one thing it asks for; anything else
# beside "slideshow" is not a command and falls through to prompt steering.
_VERBS = {
    "start": ShowCommand.START,
    "open": ShowCommand.START,
    "pause": ShowCommand.PAUSE,
    "stop": ShowCommand.STOP,
    "end": ShowCommand.STOP,
    "close": ShowCommand.STOP,
}

# A command is a few words — "start the slideshow, please" — while anything
# sentence-shaped that happens to mention a slideshow is a prompt edit.
_MAX_COMMAND_WORDS = 6


def _names_the_show(words: list) -> bool:
    """Whether these words name the slideshow — as one word or as the two
    whisper splits it into about as often."""
    return "slideshow" in words or any(
        first == "slide" and second == "show"
        for first, second in zip(words, words[1:])
    )


def match_show_command(text: str) -> ShowCommand | None:
    """What a spoken utterance asks of the show, or ``None`` when it isn't asking.

    Both halves are required — a verb this table knows and the word "slideshow" —
    so "stop" alone (which could be anything) and "a slideshow of her" (which is
    a prompt) are both left to fall through.
    """
    words = re.findall(r"[a-z]+", (text or "").lower())
    if not words or len(words) > _MAX_COMMAND_WORDS or not _names_the_show(words):
        return None
    for word in words:
        command = _VERBS.get(word)
        if command is not None:
            return command
    return None


def show_command_bias() -> str:
    """The show vocabulary as part of whisper's initial prompt."""
    return "Slideshow commands: " + ", ".join(
        list(_VERBS) + ["slideshow"]
    ) + "."
