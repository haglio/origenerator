from __future__ import annotations

from typing import NamedTuple

from origenerator.gallery.collection import spoken_collections
from origenerator.gallery.shapes import LANDSCAPE, PORTRAIT
from origenerator.gallery.voice_commands import command_phrases, match_command
from origenerator.voice.app_commands import match_app_command, phrases_answered_when_hosted
from origenerator.voice.app_commands import spoken_phrases as app_command_phrases
from origenerator.voice.dictation import LEAD_WORDS
from origenerator.voice.slideshow_commands import (
    SlideshowCommand,
    match_slideshow_command,
    slideshow_command_phrases,
)
from origenerator.voice.text import words

SHAPES = (PORTRAIT, LANDSCAPE)

def _heard_by_a_surface() -> tuple:
    return tuple(spoken for spoken in spoken_collections() if spoken.voice.heard_by_a_surface)


def _collection_words() -> dict[str, str]:
    return {spoken.label.lower(): spoken.key for spoken in _heard_by_a_surface()}

_MAX_COLLECTION_WORDS = 3


class SurfaceCommand(NamedTuple):
    command: object
    shape: str | None = None


class CollectionCommand(NamedTuple):
    collection_key: str
    shape: str | None = None


class SlideshowControl(NamedTuple):
    command: SlideshowCommand
    shape: str | None = None


def match_voice_command(text: str) -> CollectionCommand | SlideshowControl | SurfaceCommand | None:
    shape, spoken = split_shape(text)
    rest = spoken.split()
    if not rest and shape is None:
        return None

    collection = _collection_named(rest)
    if collection is not None:
        return CollectionCommand(collection, shape)

    control = match_slideshow_command(spoken)
    if control is not None:
        return SlideshowControl(control, shape)

    surface = match_command(spoken)
    if surface is not None:
        return SurfaceCommand(surface, shape)
    return None


def split_shape(text: str) -> tuple[str | None, str]:
    heard = words(text, keep_apostrophes=True)
    if heard and heard[0] in SHAPES:
        return heard[0], " ".join(heard[1:])
    return None, " ".join(heard)


def shaped_app_command(text: str):
    words = (text or "").split()
    shape = words[0].lower().strip(".,!?") if words else ""
    if shape in SHAPES:
        rest = " ".join(words[1:])
    else:
        shape, rest = None, (text or "")
    matched = match_app_command(rest)
    if matched is None:
        return None
    return SurfaceCommand(matched, shape) if shape else matched


def _collection_named(words: list[str]) -> str | None:
    if not words or len(words) > _MAX_COLLECTION_WORDS:
        return None
    return _collection_words().get(" ".join(words))


def spoken_phrases() -> frozenset[str]:
    return app_command_phrases() | _what_is_said_to_a_surface()


def hosted_phrases() -> frozenset[str]:
    return (phrases_answered_when_hosted() | command_phrases()
            | frozenset(spoken.label.lower() for spoken in _heard_by_a_surface()
                        if spoken.voice.answered_when_hosted) | {LEAD_WORDS[0]})


def _what_is_said_to_a_surface() -> frozenset[str]:
    return command_phrases() | slideshow_command_phrases() | frozenset(_collection_words())
