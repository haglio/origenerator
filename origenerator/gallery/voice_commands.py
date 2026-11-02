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

ENHANCE_COMMAND = "enhance"

ENHANCE_PHRASES: tuple[str, ...] = ("enhance", "enhanced")

_MAX_TRAILING_WORDS = 1


def _lead_words(text: str, phrases: tuple[str, ...]) -> list | None:
    heard = words(text)
    if not heard:
        return None
    for phrase in phrases:
        lead = phrase.split()
        if heard[: len(lead)] == lead and len(heard) - len(lead) <= _MAX_TRAILING_WORDS:
            return heard[len(lead):]
    return None


def match_enhance_command(text: str) -> str | None:
    return ENHANCE_COMMAND if _lead_words(text, ENHANCE_PHRASES) is not None else None


def match_command(text: str):
    return (match_fix_command(text) or match_animate_command(text)
            or match_enhance_command(text))


def recognized_spelling(text: str) -> str | None:
    spelled = fix_command_spelling(text) or animate_command_spelling(text)
    if spelled is not None:
        return spelled
    trailing = _lead_words(text, ENHANCE_PHRASES)
    if trailing is None:
        return None
    return " ".join([ENHANCE_COMMAND, *trailing])


GENAU_SAID: tuple[str, ...] = ("genau", "go now")


def said_in(phrase: str) -> str | None:
    return "de" if any(said in phrase for said in GENAU_SAID) else None


def command_phrases() -> frozenset[str]:
    return (fix_command_phrases() | animate_command_phrases()
            | {ENHANCE_COMMAND, f"{ENHANCE_COMMAND} it"})
