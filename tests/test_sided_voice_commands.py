"""The routing around the spoken commands: which side, and which collection.

The vocabularies themselves live where they are owned — the picture commands
in :mod:`origenerator.gallery.voice_commands`, the slideshow's in
:mod:`origenerator.voice.slideshow_commands`.  This is what wraps them: an optional
leading side, and the collection names, so an utterance can say WHICH slideshow it means
when two are running on the satellite regions.

Everything this does NOT match falls through to a prompt rewrite, so the
misses matter as much as the hits — a sentence mentioning a collection is a prompt
edit, not an order to play it.
"""
from __future__ import annotations

import pytest

from origenerator.gallery.collection import (
    FAVORITES_KEY,
    RECENTS_KEY,
    TRASH_KEY,
)
from origenerator.voice.commands import (
    CollectionCommand,
    SlideshowControl,
    SurfaceCommand,
    match_voice_command,
    sided_app_command,
    split_side,
    spoken_phrases,
)
from origenerator.voice.slideshow_commands import SlideshowCommand


@pytest.mark.parametrize("text, side", [
    ("fix teeth", None),
    ("landscape fix teeth", "landscape"),
    ("portrait fix her hands", "portrait"),
])
def test_a_fix_can_name_the_side_it_means(text, side):
    """Hosted, two slideshows run and neither is the active window, so the side word
    is the only thing that says which picture is being looked at."""
    command = match_voice_command(text)

    assert isinstance(command, SurfaceCommand)
    assert command.side == side


@pytest.mark.parametrize("text, key, side", [
    ("favorites", FAVORITES_KEY, None),
    ("landscape favorites", FAVORITES_KEY, "landscape"),
    ("portrait latest", RECENTS_KEY, "portrait"),
    ("trash", TRASH_KEY, None),
])
def test_a_collection_name_is_an_order_to_play_it(text, key, side):
    command = match_voice_command(text)

    assert command == CollectionCommand(key, side)


def test_the_collection_names_are_the_tree_s_own():
    """Spoken by the label the collection wears, so a rename carries into the
    vocabulary rather than leaving it answering to the old word — "favorites"
    is what the collection says, where the key still says favorited."""
    assert match_voice_command("favorites") == CollectionCommand(FAVORITES_KEY, None)
    assert match_voice_command("starred") is None


@pytest.mark.parametrize("text", [
    "put her in my favorites",       # a prompt edit that mentions one
    "fix the lighting",              # names no part
    "she is standing in the trash",  # ditto, at length
    "",
])
def test_anything_else_is_left_to_the_prompt_rewriter(text):
    assert match_voice_command(text) is None


def test_the_recognizer_is_asked_to_hear_the_whole_vocabulary():
    heard = spoken_phrases()

    for phrase in ("fix teeth", "animate as alpha", "enhance", "start slideshow",
                   "favorites", "latest", "undo", "amp fifty", "mic off"):
        assert phrase in heard


def test_every_phrase_the_recognizer_is_asked_to_hear_means_something():
    assert [phrase for phrase in spoken_phrases()
            if sided_app_command(phrase) is None and match_voice_command(phrase) is None] == []


@pytest.mark.parametrize("text, side", [
    ("start slideshow", None),
    ("landscape start slideshow", "landscape"),
    ("portrait stop slideshow", "portrait"),
])
def test_a_slideshow_command_can_name_the_side_it_means(text, side):
    """The slideshow's own controls take a side too, for the same reason: hosted,
    "stop slideshow" with two up has to say which one."""
    command = match_voice_command(text)

    assert isinstance(command, SlideshowControl)
    assert command.side == side
    assert isinstance(command.command, SlideshowCommand)


@pytest.mark.parametrize("text, side", [
    ("enhance it", None),
    ("landscape enhance", "landscape"),
    ("portrait animate as video alpha", "portrait"),
])
def test_the_other_picture_commands_can_name_the_side_they_mean(text, side):
    """The other picture commands take a side for the same reason a fix does."""
    command = match_voice_command(text)

    assert isinstance(command, SurfaceCommand)
    assert command.side == side


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
