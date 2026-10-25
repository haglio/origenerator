"""The whole spoken vocabulary: what an utterance means, if anything.

Three things can be said, and any of them may be led by a side: a command about
the picture on screen (:mod:`origenerator.gallery.voice_commands`), one of the
show's own controls (:mod:`origenerator.voice.show_commands`), or a shelf name,
which plays that shelf the way its slideshow button would.

* a command about the picture on screen — ``fix <part>``, ``animate as <lane>
  <act>`` or ``enhance`` (:mod:`origenerator.gallery.voice_commands` owns all
  three).
* ``start`` / ``pause`` / ``stop slideshow`` — the slideshow's own controls
  (:mod:`origenerator.voice.slideshow_commands`).
* ``<collection>`` — play that collection, the way its slideshow button would.

The side ("landscape fix teeth", "landscape favorites") is what makes them
usable inside Fun Time, where two slideshows run at once on the satellite regions
and NEITHER is the active window — the speaker is looking at one of them while
the main window has the keyboard, so "the slideshow that is up" names nothing and a
collection command has no region to land on. Standalone there is one slideshow and no
regions, so a side is accepted and ignored.

Kept deliberately strict, because the mic hears whole sentences too: a command
is a few words, and names something real.
"""

from __future__ import annotations

from typing import NamedTuple

from origenerator.gallery.collection import (
    EXPERIMENTS_KEY,
    EXPERIMENTS_LABEL,
    FAVORITES_KEY,
    FAVORITES_LABEL,
    RECENTS_KEY,
    RECENTS_LABEL,
    REQUESTS_KEY,
    REQUESTS_LABEL,
    TRASH_KEY,
    TRASH_LABEL,
)
from origenerator.gallery.sides import LANDSCAPE, PORTRAIT
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

SIDES = (PORTRAIT, LANDSCAPE)

# The collections, addressed by the names they wear in the tree, so a rename
# carries into the vocabulary rather than leaving it saying the old word.
COLLECTION_KEYS: dict[str, str] = {
    RECENTS_LABEL.lower(): RECENTS_KEY,
    FAVORITES_LABEL.lower(): FAVORITES_KEY,
    EXPERIMENTS_LABEL.lower(): EXPERIMENTS_KEY,
    REQUESTS_LABEL.lower(): REQUESTS_KEY,
    TRASH_LABEL.lower(): TRASH_KEY,
}

# A collection command is its name, at most led by a side: three words is already
# generous. Anything longer is a sentence that happens to contain the word.
_MAX_COLLECTION_WORDS = 3


class SurfaceCommand(NamedTuple):
    """A command about the picture on screen — a
    :class:`~origenerator.gallery.detail_parts.DetailPart` to fix, an
    :class:`~origenerator.animate_command.AnimateRequest` or
    :data:`~origenerator.gallery.voice_commands.ENHANCE_COMMAND` — aimed at
    *side*'s slideshow (``None`` — whichever slideshow is up)."""
    command: object
    side: str | None = None


class CollectionCommand(NamedTuple):
    """Play the collection *collection_key*, on *side*'s region (``None`` — wherever the
    set's own shape routes it)."""
    collection_key: str
    side: str | None = None


class SlideshowControl(NamedTuple):
    """Start, pause or stop the slideshow — on *side*'s region when named."""
    command: SlideshowCommand
    side: str | None = None


def match_voice_command(text: str) -> CollectionCommand | SlideshowControl | SurfaceCommand | None:
    """What *text* asks for, or ``None`` when it is not a command at all.

    Each matcher is strict about its own shape and none can claim another's (a
    slideshow command names the slideshow, a fix leads with "fix", a Genau command
    leads with its own phrase, a collection command is nothing but the collection's
    name), so the order only decides which is asked first.
    """
    side, spoken = split_side(text)
    rest = spoken.split()
    if not rest and side is None:
        return None

    collection = _collection_named(rest)
    if collection is not None:
        return CollectionCommand(collection, side)

    control = match_slideshow_command(spoken)
    if control is not None:
        return SlideshowControl(control, side)

    surface = match_command(spoken)
    if surface is not None:
        return SurfaceCommand(surface, side)
    return None


def split_side(text: str) -> tuple[str | None, str]:
    """The side an utterance leads with, and everything after it.

    ``("landscape", "fix teeth")`` for "landscape fix teeth", ``(None, "fix
    teeth")`` for the same words with no side named.  Punctuation and case go
    with it: both are the transcriber's invention rather than the speaker's,
    and every matcher below works on the bare words.

    Public because a spoken request needs the same split and cannot get it from
    :func:`match_voice_command` — its words are the speaker's own, so no
    matcher here claims them, and the dictation that collects them must not be
    fed the side word as if it were the first word of the request.
    """
    heard = words(text, keep_apostrophes=True)
    if heard and heard[0] in SIDES:
        return heard[0], " ".join(heard[1:])
    return None, " ".join(heard)


def sided_app_command(text: str):
    """The bare app command *text* is, wrapped with the side it named.

    The bare vocabulary (:mod:`origenerator.voice.app_commands`) is whole
    utterances only — "undo", "favorite", "experiments" — which is strict enough to
    be asked ahead of an opening request.  A side may still lead one, for the
    same reason it may lead any other order here: hosted, two slideshows run and
    neither is the active window, so "landscape lock" is the only way to say
    which picture is meant.  Unsided, it comes back bare, exactly as the
    standalone app expects it.
    """
    # The side is taken off the RAW words, not off split_side's letters-only
    # normalisation: this vocabulary says numbers ("center 30"), and a split
    # that drops the digits hands the matcher a command with nothing to set.
    words = (text or "").split()
    side = words[0].lower().strip(".,!?") if words else ""
    if side in SIDES:
        rest = " ".join(words[1:])
    else:
        side, rest = None, (text or "")
    matched = match_app_command(rest)
    if matched is None:
        return None
    return SurfaceCommand(matched, side) if side else matched


def _collection_named(words: list[str]) -> str | None:
    """The collection those words name, on their own — ``None`` for anything else.

    The whole utterance has to BE the name: "favorites" is the command, while
    "put her in my favorites" is a sentence that mentions one.
    """
    if not words or len(words) > _MAX_COLLECTION_WORDS:
        return None
    return COLLECTION_KEYS.get(" ".join(words))


def spoken_phrases() -> frozenset[str]:
    """The whole vocabulary as a recognizer that listens for words is asked to hear it.

    Unsided: a side is for a hosting session's two slideshows, and that session hears for
    itself. One said here still works, by the slower road every sentence takes.
    """
    return app_command_phrases() | _what_is_said_to_a_surface()


def hosted_phrases() -> frozenset[str]:
    return phrases_answered_when_hosted() | _what_is_said_to_a_surface() | {LEAD_WORDS[0]}


def _what_is_said_to_a_surface() -> frozenset[str]:
    return command_phrases() | slideshow_command_phrases() | frozenset(COLLECTION_KEYS)
