"""What a spoken utterance over a fullscreen picture can ask for.

Three commands share one mic: "fix <part>"
(:mod:`~origenerator.workflows.detail_parts`), "animate as <act>"
(:mod:`~origenerator.animate_command`), and "enhance".
:func:`match_command` is the one matcher the voice surface is given,
:func:`command_phrases` what the recognizer is asked to hear, and
:func:`recognized_spelling` an utterance in the words it was understood as, for a
caption saying it back. All three are strict about shape: an utterance that
matches nothing here is no command.
"""
from __future__ import annotations

from origenerator.animate_command import (
    animate_command_phrases,
    animate_command_spelling,
    match_animate_command,
)
from origenerator.voice.text import words
from origenerator.workflows.detail_parts import (
    fix_command_phrases,
    fix_command_spelling,
    match_fix_command,
)

# The enhance command, as a value the dispatcher can test for. A bare marker
# rather than a richer object because the command carries no argument: what to
# enhance is whatever picture is on the screen being spoken over.
ENHANCE_COMMAND = "enhance"

# The word itself, and the past tense whisper offers about as readily off a
# quiet mic. Nothing looser: a sentence may well open with "enhanced".
ENHANCE_PHRASES: tuple[str, ...] = ("enhance", "enhanced")

# Anything past the phrase and a trailing "it" is a sentence that happens to
# begin with the words.
_MAX_TRAILING_WORDS = 1


def _lead_words(text: str, phrases: tuple[str, ...]) -> list | None:
    """What the utterance says after the phrase it *leads* with — ``[]`` when it
    says nothing more, ``None`` when it leads with none of ``phrases``; a sentence
    merely containing the words does not count. The trailing words come back
    because the phrase is the half :func:`recognized_spelling` replaces."""
    heard = words(text)
    if not heard:
        return None
    for phrase in phrases:
        lead = phrase.split()
        if heard[: len(lead)] == lead and len(heard) - len(lead) <= _MAX_TRAILING_WORDS:
            return heard[len(lead):]
    return None


def match_enhance_command(text: str) -> str | None:
    """``ENHANCE_COMMAND`` when the utterance asks for the better version of
    what's on screen — "enhance", "enhance it"."""
    return ENHANCE_COMMAND if _lead_words(text, ENHANCE_PHRASES) is not None else None


def match_command(text: str):
    """The command an utterance asks for, or ``None`` when it asks for none: a
    tuple of :class:`~origenerator.workflows.detail_parts.DetailPart`, an
    :class:`~origenerator.animate_command.AnimateRequest`, or
    :data:`ENHANCE_COMMAND`. No two of the vocabularies overlap, and a fix that
    names no part falls through the chain like any other miss."""
    return (match_fix_command(text) or match_animate_command(text)
            or match_enhance_command(text))


def recognized_spelling(text: str) -> str | None:
    """The utterance in the words it was recognized as — "enhanced it" read back
    as "enhance it" — or ``None`` when it is no command. Only the phrase naming
    the command is respelled. Mirrors :func:`match_command`, so an utterance shown
    respelled is exactly one about to be run."""
    spelled = fix_command_spelling(text) or animate_command_spelling(text)
    if spelled is not None:
        return spelled
    trailing = _lead_words(text, ENHANCE_PHRASES)
    if trailing is None:
        return None
    return " ".join([ENHANCE_COMMAND, *trailing])


# What a speaker says for the Genau lane: the German word, and the "go now" said
# when it is not heard, as Fun Time does.
GENAU_SAID: tuple[str, ...] = ("genau", "go now")


def said_in(phrase: str) -> str | None:
    """German where *phrase* names the Genau lane, so a mangled hearing of it is
    read once more in German before it is doubted."""
    return "de" if any(said in phrase for said in GENAU_SAID) else None


def command_phrases() -> frozenset[str]:
    """Every command about the picture that a recognizer listening for words should hear."""
    return (fix_command_phrases() | animate_command_phrases()
            | {ENHANCE_COMMAND, f"{ENHANCE_COMMAND} it"})
