"""What a spoken utterance over a fullscreen picture can ask for.

Two commands share one mic. "fix <part>" aims a targeted detail pass at what's on
screen (:mod:`~origenerator.gallery.detail_parts` owns the parts and the match);
"genau it" animates the picture as a Genau clip. :func:`match_command` is the one
matcher the voice surface is given, so adding a verb here is all it takes to teach
it — and :func:`command_bias` hands every word to whisper up front, which is what
makes a short imperative off a quiet mic land at all.

Both are deliberately strict about shape: an utterance that matches nothing here
falls through to prompt steering, so a loose match would silently spend a command
on rewriting a prompt.
"""

import re

from origenerator.gallery.detail_parts import (
    fix_command_bias, match_fix_command,
)

# The Genau command, as a value the dispatcher can test for. A bare marker rather
# than a richer object because the command carries no argument: what to animate is
# whatever picture is on the screen being spoken over.
GENAU_COMMAND = "genau"

# What the recognizer is actually listening for. "Genau" is not English and no
# recognizer in this suite hears it: Fun Time settled on the sound-alike "go now"
# for every one of its Genau commands, and displays it back as "genau" — so this
# listens for the same sound and answers in the same word. The spelling and a
# couple of near renderings ride alongside for whisper's benefit, which is a
# looser transcriber than Fun Time's vosk grammar.
GENAU_PHRASES: tuple[str, ...] = (
    "go now", "genau", "gunow", "genow", "ganau",
)

# The command takes no argument, so anything past the phrase and a trailing "it"
# is a sentence that happens to begin with the words.
_MAX_TRAILING_WORDS = 1


def match_genau_command(text: str) -> str | None:
    """``GENAU_COMMAND`` when the utterance asks to animate what's on screen.

    It must *lead* with the phrase — "go now", "go now it", "genau it" all count,
    while a sentence merely containing it does not. That is far more likely to be
    a prompt edit mentioning the word than an order to run anything, and the cost
    of being wrong is a generation the speaker did not ask for.
    """
    words = re.findall(r"[a-z]+", (text or "").lower())
    if not words:
        return None
    for phrase in GENAU_PHRASES:
        lead = phrase.split()
        if words[: len(lead)] != lead:
            continue
        if len(words) - len(lead) <= _MAX_TRAILING_WORDS:
            return GENAU_COMMAND
    return None


def match_command(text: str):
    """The command an utterance asks for, or ``None`` when it asks for none.

    A :class:`~origenerator.gallery.detail_parts.DetailPart` for a targeted fix,
    or :data:`GENAU_COMMAND`. Fixes are tried first: they are the older and more
    tightly-shaped of the two, and the two vocabularies do not overlap.
    """
    return match_fix_command(text) or match_genau_command(text)


def command_bias() -> str:
    """Every command word as whisper's initial prompt, fixes and Genau alike."""
    return f"{fix_command_bias().rstrip('.')}, " + ", ".join(GENAU_PHRASES) + "."
