"""What a spoken utterance over a fullscreen picture can ask for.

Three commands share one mic. "fix <part>" aims a targeted detail pass at what's
on screen — one part, several ("fix hands and mouth"), or the lot ("fix all"),
with :mod:`~origenerator.workflows.detail_parts` owning the parts and the match;
"genau it" animates the picture as a Genau clip; "enhance" asks for the better
version of it. :func:`match_command` is the one matcher the voice surface
is given, so adding a verb here is all it takes to teach it — and
:func:`command_bias` hands every word to whisper up front, which is what makes a
short imperative off a quiet mic land at all.

The vocabulary is a set of renderings per command, not one word each, so what
the mic heard is rarely how the command is spelled. :func:`recognized_spelling`
is the other direction: an utterance in the words it was understood as, which is
what a caption saying it back should print.

All three are deliberately strict about shape: an utterance that matches nothing
here falls through to prompt steering, so a loose match would silently spend a
command on rewriting a prompt.
"""

import re

from origenerator.workflows.detail_parts import (
    fix_command_bias, fix_command_spelling, match_fix_command,
)

# The Genau command, as a value the dispatcher can test for. A bare marker rather
# than a richer object because the command carries no argument: what to animate is
# whatever picture is on the screen being spoken over.
GENAU_COMMAND = "genau"

# What the recognizer is actually listening for. "Genau" is not English and no
# recognizer in this suite hears it: Fun Time settled on the sound-alike "go now"
# for every one of its Genau commands, and displays it back as "genau" — so this
# listens for the same sound and answers in the same word. The spelling and the
# renderings whisper has actually come back with ride alongside, because it is a
# looser transcriber than Fun Time's vosk grammar; each was heard off this mic
# rather than guessed at. A trailing "it" is all any of them may carry
# (:data:`_MAX_TRAILING_WORDS`), which is what keeps the two that are ordinary
# English — "good now", "can now" — from claiming a sentence.
GENAU_PHRASES: tuple[str, ...] = (
    "go now", "genau", "gunow", "genow", "ganau",
    "good now", "can now", "canow",
)

# The enhance command, the same shape: what to enhance is the picture on screen.
ENHANCE_COMMAND = "enhance"

# The word itself, and the past tense whisper offers about as readily off a
# quiet mic. Nothing looser: everything unmatched here is rewritten into the
# prompt instead, and "enhanced" is a word a prompt edit may well open with.
ENHANCE_PHRASES: tuple[str, ...] = ("enhance", "enhanced")

# The command takes no argument, so anything past the phrase and a trailing "it"
# is a sentence that happens to begin with the words.
_MAX_TRAILING_WORDS = 1


def _lead_words(text: str, phrases: tuple[str, ...]) -> list | None:
    """What the utterance says after the phrase it *leads* with — ``[]`` when it
    says nothing more, ``None`` when it leads with none of ``phrases``.

    A sentence merely containing the words does not count. That is far more
    likely to be a prompt edit mentioning them than an order to run anything,
    and the cost of being wrong is a generation the speaker did not ask for.

    The trailing words come back rather than a bare yes, because the phrase is
    the half :func:`recognized_spelling` replaces and the rest is the half it
    keeps.
    """
    words = re.findall(r"[a-z]+", (text or "").lower())
    if not words:
        return None
    for phrase in phrases:
        lead = phrase.split()
        if words[: len(lead)] == lead and len(words) - len(lead) <= _MAX_TRAILING_WORDS:
            return words[len(lead):]
    return None


def _leads_with(text: str, phrases: tuple[str, ...]) -> bool:
    """Whether the utterance leads with one of ``phrases`` and says no more than
    a trailing "it"."""
    return _lead_words(text, phrases) is not None


def match_genau_command(text: str) -> str | None:
    """``GENAU_COMMAND`` when the utterance asks to animate what's on screen —
    "go now", "go now it", "genau it"."""
    return GENAU_COMMAND if _leads_with(text, GENAU_PHRASES) else None


def match_enhance_command(text: str) -> str | None:
    """``ENHANCE_COMMAND`` when the utterance asks for the better version of
    what's on screen — "enhance", "enhance it"."""
    return ENHANCE_COMMAND if _leads_with(text, ENHANCE_PHRASES) else None


def match_command(text: str):
    """The command an utterance asks for, or ``None`` when it asks for none.

    A tuple of :class:`~origenerator.workflows.detail_parts.DetailPart` for a
    targeted fix, :data:`GENAU_COMMAND`, or :data:`ENHANCE_COMMAND`. Fixes are
    tried first: they are the oldest and most tightly-shaped of the three, and
    none of the three vocabularies overlaps another. A fix that names no part
    is no fix, and the empty tuple it comes back as falls through the chain the
    way any other miss does.
    """
    return (match_fix_command(text) or match_genau_command(text)
            or match_enhance_command(text))


# How each command is written when the app says back what it heard. Whisper
# renders "genau" a dozen ways and the matcher answers to all of them, so the
# transcription is a misspelling of a word the app knows — and it is the app's
# spelling that belongs on screen. The Genau lane keeps the capital it is named
# by everywhere else here; enhance is its own plain verb, and a fix's is "fix"
# (:func:`~origenerator.workflows.detail_parts.fix_command_spelling`).
_SPELLINGS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Genau", GENAU_PHRASES),
    ("enhance", ENHANCE_PHRASES),
)


def recognized_spelling(text: str) -> str | None:
    """The utterance in the words it was recognized as — "gunow it" read back as
    "Genau it" — or ``None`` when it is no command.

    Only the phrase that names the command is respelled; whatever else was said
    stands as heard, lowercased the way the matchers read it. Mirrors
    :func:`match_command`, so an utterance that is shown respelled is exactly
    one that is about to be run: a caption saying "Genau it" over a picture that
    then animates is the truthful pair, and printing the mangling that was
    understood perfectly well is what this replaces.
    """
    spelled = fix_command_spelling(text)
    if spelled is not None:
        return spelled
    for spelling, phrases in _SPELLINGS:
        trailing = _lead_words(text, phrases)
        if trailing is not None:
            return " ".join([spelling, *trailing])
    return None


def command_bias() -> str:
    """Every command word as whisper's initial prompt — fixes, Genau, enhance."""
    spoken = ", ".join([*GENAU_PHRASES, *ENHANCE_PHRASES])
    return f"{fix_command_bias().rstrip('.')}, {spoken}."
