"""The routing around the spoken commands: which side, and which shelf.

The vocabularies themselves live where they are owned — the picture commands
in :mod:`origenerator.gallery.voice_commands`, the slideshow's in
:mod:`origenerator.voice.show_commands`.  This is what wraps them: an optional
leading side, and the shelf names, so an utterance can say WHICH show it means
when two are running on the satellite regions.

Everything this does NOT match falls through to a prompt rewrite, so the
misses matter as much as the hits — a sentence mentioning a shelf is a prompt
edit, not an order to play it.
"""

import pytest

from origenerator.gallery.voice_commands import GENAU_COMMAND
from origenerator.gui.gallery_tree import (
    RECENTS_KEY, REQUESTS_KEY, STARRED_KEY, TRASH_KEY,
)
from origenerator.voice.commands import (
    ShelfCommand, ShowControl, SurfaceCommand, match_voice_command, split_side,
    voice_command_bias,
)
from origenerator.voice.show_commands import ShowCommand


@pytest.mark.parametrize("text, side", [
    ("fix teeth", None),
    ("landscape fix teeth", "landscape"),
    ("portrait fix her hands", "portrait"),
])
def test_a_fix_can_name_the_side_it_means(text, side):
    """Hosted, two shows run and neither is the active window, so the side word
    is the only thing that says which picture is being looked at."""
    command = match_voice_command(text)

    assert isinstance(command, SurfaceCommand)
    assert command.side == side


@pytest.mark.parametrize("text, key, side", [
    ("favorites", STARRED_KEY, None),
    ("landscape favorites", STARRED_KEY, "landscape"),
    ("portrait latest", RECENTS_KEY, "portrait"),
    ("trash", TRASH_KEY, None),
    ("requests", REQUESTS_KEY, None),
])
def test_a_shelf_name_is_an_order_to_play_it(text, key, side):
    command = match_voice_command(text)

    assert command == ShelfCommand(key, side)


def test_the_shelf_names_are_the_tree_s_own():
    """Spoken by the label the shelf wears, so a rename carries into the
    vocabulary rather than leaving it answering to the old word — "favorites"
    is what the shelf says, where the key still says starred."""
    assert match_voice_command("favorites") == ShelfCommand(STARRED_KEY, None)
    assert match_voice_command("starred") is None


@pytest.mark.parametrize("text", [
    "put her in my favorites",       # a prompt edit that mentions one
    "fix the lighting",              # names no part
    "she is standing in the trash",  # ditto, at length
    "",
])
def test_anything_else_is_left_to_the_prompt_rewriter(text):
    assert match_voice_command(text) is None


def test_the_bias_teaches_whisper_the_whole_vocabulary():
    """A quiet mic mangles a short imperative, and the sides and shelf names
    are as manglable as the fix words — so all of them are handed to whisper
    up front."""
    bias = voice_command_bias()

    for word in ("fix", "teeth", "portrait", "landscape", "favorites", "latest"):
        assert word in bias


@pytest.mark.parametrize("text, side", [
    ("start slideshow", None),
    ("landscape start slideshow", "landscape"),
    ("portrait stop slideshow", "portrait"),
])
def test_a_show_command_can_name_the_side_it_means(text, side):
    """The show's own controls take a side too, for the same reason: hosted,
    "stop slideshow" with two up has to say which one."""
    command = match_voice_command(text)

    assert isinstance(command, ShowControl)
    assert command.side == side
    assert isinstance(command.command, ShowCommand)


@pytest.mark.parametrize("text, side", [
    ("go now", None),
    ("landscape go now", "landscape"),
    ("portrait genau it", "portrait"),
])
def test_a_genau_command_can_name_the_side_it_means(text, side):
    """The other picture command takes a side for the same reason a fix does."""
    command = match_voice_command(text)

    assert command == SurfaceCommand(GENAU_COMMAND, side)


@pytest.mark.parametrize("text, side, rest", [
    ("landscape request no feet", "landscape", "request no feet"),
    ("portrait fix teeth", "portrait", "fix teeth"),
    ("request no feet", None, "request no feet"),
    ("", None, ""),
])
def test_the_side_splits_off_from_the_rest_of_what_was_said(text, side, rest):
    """The one thing a request needs and cannot get from the matcher: its words
    are the speaker's own, so nothing here claims them, and the dictation that
    collects them must not be handed the side word as the first word of the
    request itself."""
    assert split_side(text) == (side, rest)


def test_a_side_word_alone_is_a_side_and_nothing_else():
    """It names a region without asking it for anything — the caller's other
    uses get to decide what an empty rest means."""
    assert split_side("portrait") == ("portrait", "")
