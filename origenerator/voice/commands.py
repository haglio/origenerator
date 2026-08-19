"""The whole spoken vocabulary: what an utterance means, if anything.

Three things can be said, and any of them may be led by a side:

* a command about the picture on screen — ``fix <part>`` or ``genau it``
  (:mod:`origenerator.gallery.voice_commands` owns both).
* ``start`` / ``pause`` / ``stop slideshow`` — the show's own controls
  (:mod:`origenerator.voice.show_commands`).
* ``<shelf>`` — play that shelf, the way its slideshow button would.

The side ("landscape fix teeth", "landscape favorites") is what makes them
usable inside Fun Time, where two shows run at once on the satellite regions
and NEITHER is the active window — the speaker is looking at one of them while
the main window has the keyboard, so "the show that is up" names nothing and a
shelf command has no region to land on. Standalone there is one show and no
regions, so a side is accepted and ignored.

Kept deliberately strict, because everything unmatched here falls through to a
prompt rewrite: a command is a few words, and names something real.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from origenerator.gallery.voice_commands import command_bias, match_command
from origenerator.gui.gallery_tree import (
    EXPERIMENTS_KEY, EXPERIMENTS_LABEL, RECENTS_KEY, RECENTS_LABEL,
    REQUESTS_KEY, REQUESTS_LABEL, STARRED_KEY, STARRED_LABEL,
    TRASH_KEY, TRASH_LABEL,
)
from origenerator.gui.orientation import LANDSCAPE, PORTRAIT
from origenerator.voice.show_commands import (
    ShowCommand, match_show_command, show_command_bias,
)

SIDES = (PORTRAIT, LANDSCAPE)

# The shelves, addressed by the names they wear in the tree, so a rename
# carries into the vocabulary rather than leaving it saying the old word.
SHELF_KEYS: dict[str, str] = {
    RECENTS_LABEL.lower(): RECENTS_KEY,
    STARRED_LABEL.lower(): STARRED_KEY,
    EXPERIMENTS_LABEL.lower(): EXPERIMENTS_KEY,
    REQUESTS_LABEL.lower(): REQUESTS_KEY,
    TRASH_LABEL.lower(): TRASH_KEY,
}

# A shelf command is its name, at most led by a side: three words is already
# generous. Anything longer is a sentence that happens to contain the word.
_MAX_SHELF_WORDS = 3


class SurfaceCommand(NamedTuple):
    """A command about the picture on screen — a
    :class:`~origenerator.gallery.detail_parts.DetailPart` to fix or
    :data:`~origenerator.gallery.voice_commands.GENAU_COMMAND` — aimed at
    *side*'s show (``None`` — whichever show is up)."""
    command: object
    side: str | None = None


class ShelfCommand(NamedTuple):
    """Play the shelf *shelf_key*, on *side*'s region (``None`` — wherever the
    set's own shape routes it)."""
    shelf_key: str
    side: str | None = None


class ShowControl(NamedTuple):
    """Start, pause or stop the show — on *side*'s region when named."""
    command: ShowCommand
    side: str | None = None


def match_voice_command(text: str) -> ShelfCommand | ShowControl | SurfaceCommand | None:
    """What *text* asks for, or ``None`` when it is not a command at all.

    Each matcher is strict about its own shape and none can claim another's (a
    show command names the slideshow, a fix leads with "fix", a Genau command
    leads with its own phrase, a shelf command is nothing but the shelf's
    name), so the order only decides which is asked first.
    """
    words = re.findall(r"[a-z]+", (text or "").lower())
    if not words:
        return None
    side = words[0] if words[0] in SIDES else None
    rest = words[1:] if side else words
    spoken = " ".join(rest)

    shelf = _shelf_named(rest)
    if shelf is not None:
        return ShelfCommand(shelf, side)

    show = match_show_command(spoken)
    if show is not None:
        return ShowControl(show, side)

    surface = match_command(spoken)
    if surface is not None:
        return SurfaceCommand(surface, side)
    return None


def _shelf_named(words: list[str]) -> str | None:
    """The shelf those words name, on their own — ``None`` for anything else.

    The whole utterance has to BE the name: "favorites" is the command, while
    "put her in my favorites" is a prompt edit that mentions one.
    """
    if not words or len(words) > _MAX_SHELF_WORDS:
        return None
    return SHELF_KEYS.get(" ".join(words))


def voice_command_bias() -> str:
    """The vocabulary as whisper's initial prompt — every word the picture and
    slideshow commands use, plus the sides and shelf names, which a quiet mic
    mangles the same way."""
    extra = ", ".join([*SIDES, *SHELF_KEYS])
    return f"{command_bias()} {show_command_bias()} Sides and shelves: {extra}."
