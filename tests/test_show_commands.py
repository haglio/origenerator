"""Spoken show control — which utterances claim to be a command, and which fall
through to prompt steering."""

import pytest

from origenerator.voice.show_commands import (
    ShowCommand,
    match_show_command,
    show_command_bias,
)


@pytest.mark.parametrize("said", ["start slideshow", "open slideshow"])
def test_starting_the_show(said):
    assert match_show_command(said) is ShowCommand.START


def test_pausing_the_show():
    assert match_show_command("pause slideshow") is ShowCommand.PAUSE


@pytest.mark.parametrize("said", ["stop slideshow", "end slideshow",
                                  "close slideshow"])
def test_stopping_the_show(said):
    assert match_show_command(said) is ShowCommand.STOP


def test_whispers_punctuation_and_case_are_ignored():
    assert match_show_command("Start slideshow.") is ShowCommand.START


def test_slide_show_as_two_words_still_counts():
    # Whisper splits it about as often as not, and the speaker said one thing.
    assert match_show_command("start the slide show") is ShowCommand.START


def test_a_few_filler_words_are_tolerated():
    assert match_show_command("please stop the slideshow") is ShowCommand.STOP


def test_a_verb_with_no_slideshow_named_is_not_a_command():
    # "stop" alone could be about anything — the device, the loop, a sentence.
    assert match_show_command("stop") is None
    assert match_show_command("close it") is None


def test_naming_the_slideshow_with_no_verb_is_not_a_command():
    assert match_show_command("the slideshow") is None


def test_a_sentence_shaped_prompt_falls_through_to_steering():
    # It mentions a slideshow, but it is plainly a prompt being dictated.
    said = "a slideshow of her standing by the window in the morning light"
    assert match_show_command(said) is None


def test_an_empty_utterance_asks_for_nothing():
    assert match_show_command("") is None
    assert match_show_command(None) is None


def test_the_bias_hands_whisper_every_word_a_command_may_use():
    bias = show_command_bias()
    for word in ("start", "open", "pause", "stop", "end", "close", "slideshow"):
        assert word in bias
