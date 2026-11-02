from __future__ import annotations

import pytest

from origenerator.gallery.collection import (
    FAVORITES_KEY,
    LATEST_KEY,
)
from origenerator.gallery.voice_commands import ENHANCE_COMMAND
from origenerator.voice.app_commands import AppCommand, BarSetting
from origenerator.voice.commands import (
    CollectionCommand,
    SlideshowControl,
    SurfaceCommand,
    match_voice_command,
    shaped_app_command,
    split_shape,
    spoken_phrases,
)
from origenerator.voice.slideshow_commands import SlideshowCommand


@pytest.mark.parametrize(("text", "shape"), [
    ("fix teeth", None),
    ("landscape fix teeth", "landscape"),
    ("portrait fix her hands", "portrait"),
])
def test_a_fix_can_name_the_side_it_means(text, shape):
    command = match_voice_command(text)

    assert isinstance(command, SurfaceCommand)
    assert command.shape == shape


@pytest.mark.parametrize(("text", "key", "shape"), [
    ("favorites", FAVORITES_KEY, None),
    ("landscape favorites", FAVORITES_KEY, "landscape"),
    ("portrait latest", LATEST_KEY, "portrait"),
])
def test_a_collection_name_is_an_order_to_play_it(text, key, shape):
    command = match_voice_command(text)

    assert command == CollectionCommand(key, shape)


def test_the_collection_names_are_the_tree_s_own():
    assert match_voice_command("favorites") == CollectionCommand(FAVORITES_KEY, None)
    assert match_voice_command("starred") is None


def test_saying_enhanced_enhances_the_image_on_screen_rather_than_opening_enhanced():
    assert match_voice_command("enhanced") == SurfaceCommand(ENHANCE_COMMAND)


@pytest.mark.parametrize("text", [
    "put her in my favorites",
    "fix the lighting",
    "she is standing in the trash",
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
            if shaped_app_command(phrase) is None and match_voice_command(phrase) is None] == []


@pytest.mark.parametrize(("text", "shape"), [
    ("start slideshow", None),
    ("landscape start slideshow", "landscape"),
    ("portrait stop slideshow", "portrait"),
])
def test_a_slideshow_command_can_name_the_side_it_means(text, shape):
    command = match_voice_command(text)

    assert isinstance(command, SlideshowControl)
    assert command.shape == shape
    assert isinstance(command.command, SlideshowCommand)


@pytest.mark.parametrize(("text", "shape"), [
    ("enhance it", None),
    ("landscape enhance", "landscape"),
    ("portrait animate as video alpha", "portrait"),
])
def test_the_other_image_commands_can_name_the_side_they_mean(text, shape):
    command = match_voice_command(text)

    assert isinstance(command, SurfaceCommand)
    assert command.shape == shape


@pytest.mark.parametrize(("text", "shape", "rest"), [
    ("landscape request no feet", "landscape", "request no feet"),
    ("portrait fix teeth", "portrait", "fix teeth"),
    ("request no feet", None, "request no feet"),
    ("", None, ""),
])
def test_the_side_splits_off_from_the_rest_of_what_was_said(text, shape, rest):
    assert split_shape(text) == (shape, rest)


def test_a_side_word_alone_is_a_side_and_nothing_else():
    assert split_shape("portrait") == ("portrait", "")


def test_a_shape_leading_a_bar_setting_leaves_its_number_to_set():
    assert shaped_app_command("landscape amp 50") == SurfaceCommand(BarSetting("amp", 50), "landscape")


def test_a_shape_leading_a_bare_app_command_names_the_side_it_means():
    assert shaped_app_command("landscape lock") == SurfaceCommand(AppCommand.LOCK, "landscape")


def test_a_bare_app_command_with_no_shape_comes_back_bare():
    assert shaped_app_command("lock") is AppCommand.LOCK
