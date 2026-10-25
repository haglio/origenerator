"""Spoken slideshow control — which utterances claim to be a command, and which are
left alone."""
from __future__ import annotations

import pytest

from origenerator.voice.slideshow_commands import (
    SlideshowCommand,
    match_slideshow_command,
    slideshow_command_phrases,
)


@pytest.mark.parametrize("said", ["start slideshow", "open slideshow"])
def test_starting_the_slideshow(said):
    assert match_slideshow_command(said) is SlideshowCommand.START


def test_pausing_the_slideshow():
    assert match_slideshow_command("pause slideshow") is SlideshowCommand.PAUSE


@pytest.mark.parametrize("said", ["stop slideshow", "end slideshow",
                                  "close slideshow"])
def test_stopping_the_slideshow(said):
    assert match_slideshow_command(said) is SlideshowCommand.STOP


def test_whispers_punctuation_and_case_are_ignored():
    assert match_slideshow_command("Start slideshow.") is SlideshowCommand.START


def test_slide_show_as_two_words_still_counts():
    # Whisper splits it about as often as not, and the speaker said one thing.
    assert match_slideshow_command("start the slide show") is SlideshowCommand.START


def test_a_few_filler_words_are_tolerated():
    assert match_slideshow_command("please stop the slideshow") is SlideshowCommand.STOP


def test_a_verb_with_no_slideshow_named_is_not_a_command():
    # "stop" alone could be about anything — the device, the loop, a sentence.
    assert match_slideshow_command("stop") is None
    assert match_slideshow_command("close it") is None


def test_naming_the_slideshow_with_no_verb_is_not_a_command():
    assert match_slideshow_command("the slideshow") is None


def test_a_sentence_that_mentions_a_slideshow_is_no_command():
    # It mentions a slideshow, but it is plainly a sentence.
    said = "a slideshow of her standing by the window in the morning light"
    assert match_slideshow_command(said) is None


def test_an_empty_utterance_asks_for_nothing():
    assert match_slideshow_command("") is None
    assert match_slideshow_command(None) is None


def test_the_recognizer_is_asked_to_hear_each_verb_with_the_slideshow_named_either_way():
    heard = slideshow_command_phrases()
    for phrase in ("start slideshow", "open slideshow", "pause slide show", "stop slideshow",
                   "end slideshow", "close slide show", "play slideshow"):
        assert phrase in heard
    assert [phrase for phrase in heard if match_slideshow_command(phrase) is None] == []
