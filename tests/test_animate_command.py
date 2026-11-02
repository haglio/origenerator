"""The spoken "animate as" — the lane and the act it names, and what it leaves out.

The acts are the committed example overlay's own (alpha, beta, gamma, dancing…),
so nothing here is fixture vocabulary out of the library (see CLAUDE.md).
"""
from __future__ import annotations

import pytest

from origenerator.action_settings import GENAU, VIDEO
from origenerator.animate_command import (
    AnimateRequest,
    animate_command_phrases,
    animate_command_spelling,
    match_animate_command,
)


@pytest.mark.parametrize("said", [
    "animate as alpha",
    "animate as video alpha",
    "Animate as Alpha.",
])
def test_the_video_lane_is_what_an_utterance_that_names_no_lane_asks_for(said):
    assert match_animate_command(said) == AnimateRequest(VIDEO, "alpha")


@pytest.mark.parametrize("said", [
    "animate as genau alpha",
    "animate as go now alpha",
    "animate as gunow alpha",
])
def test_the_loop_lane_is_asked_for_by_the_word_this_family_hears_it_as(said):
    assert match_animate_command(said) == AnimateRequest(GENAU, "alpha")


def test_an_act_of_several_words_is_heard_whole():
    assert match_animate_command("animate as theta form") is None
    assert match_animate_command("animate as dancing") == AnimateRequest(VIDEO, "dancing")


def test_the_act_may_be_left_out_where_the_image_leaves_no_choice():
    assert match_animate_command("animate as") == AnimateRequest(VIDEO, "")
    assert match_animate_command("animate as genau") == AnimateRequest(GENAU, "")
    assert match_animate_command("animate") == AnimateRequest(VIDEO, "")


def test_an_act_the_app_has_never_heard_of_is_no_command_at_all():
    # Everything unmatched falls through to a prompt rewrite, and "animate as a
    # painting would" is one of those.
    assert match_animate_command("animate as a painting would") is None
    assert match_animate_command("animate as zeta") is None


def test_a_sentence_that_merely_mentions_animating_is_left_to_the_prompt():
    assert match_animate_command("make the alpha animate as smoothly as you can") is None
    assert match_animate_command("") is None


def test_the_recognizer_is_asked_to_hear_every_act_in_both_lanes():
    heard = animate_command_phrases()

    for phrase in ("animate as", "animate as alpha", "animate as dancing",
                   "animate as go now", "animate as go now alpha"):
        assert phrase in heard


def test_every_phrase_the_recognizer_is_asked_to_hear_is_a_command():
    assert [said for said in animate_command_phrases()
            if match_animate_command(said) is None] == []


def test_the_app_says_back_what_it_heard_in_its_own_spelling():
    assert animate_command_spelling("animate as gunow alpha") == "animate as Genau alpha"
    assert animate_command_spelling("Animate as Alpha.") == "animate as alpha"
    assert animate_command_spelling("animate as a painting would") is None
