from __future__ import annotations

import pytest

from origenerator.action_settings import GENAU, VIDEO
from origenerator.animate_command import (
    AnimateRequest,
    animate_command_phrases,
    animate_command_spelling,
    match_animate_command,
    spoken_actions,
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


def test_an_action_of_several_words_is_heard_whole():
    offered = ("alpha", "theta form")
    assert match_animate_command("animate as theta", offered) is None
    assert match_animate_command("animate as theta form", offered) == AnimateRequest(VIDEO, "theta form")


def test_the_action_may_be_left_out_where_the_image_leaves_no_choice():
    assert match_animate_command("animate as") == AnimateRequest(VIDEO, "")
    assert match_animate_command("animate as genau") == AnimateRequest(GENAU, "")
    assert match_animate_command("animate") == AnimateRequest(VIDEO, "")


def test_an_action_the_app_has_never_heard_of_is_no_command_at_all():
    assert match_animate_command("animate as a painting would") is None
    assert match_animate_command("animate as zeta") is None


def test_a_sentence_that_merely_mentions_animating_is_left_to_the_prompt():
    assert match_animate_command("make the alpha animate as smoothly as you can") is None
    assert match_animate_command("") is None


def test_the_recognizer_is_asked_to_hear_every_action_in_both_lanes():
    heard = animate_command_phrases()

    for phrase in ("animate as", "animate as alpha", "animate as beta",
                   "animate as go now", "animate as go now alpha"):
        assert phrase in heard


def test_a_plus_is_said_as_plus_and_a_checkbox_by_its_name_after_the_action():
    assert match_animate_command("animate as alpha plus beta") == AnimateRequest(
        VIDEO, "alpha + beta")
    assert match_animate_command("animate as alpha plus beta third box") == AnimateRequest(
        VIDEO, "alpha + beta + third box")
    assert "animate as go now alpha third box" in animate_command_phrases()
    assert not any("+" in phrase for phrase in animate_command_phrases())


def test_every_phrase_the_recognizer_is_asked_to_hear_is_a_command():
    assert [said for said in animate_command_phrases()
            if match_animate_command(said) is None] == []


def test_the_app_says_back_what_it_heard_in_its_own_spelling():
    assert animate_command_spelling("animate as gunow alpha") == "animate as Genau alpha"
    assert animate_command_spelling("Animate as Alpha.") == "animate as alpha"
    assert animate_command_spelling("animate as a painting would") is None


_HEARD = {"video_actions": {
    "buttons": {"alpha": ["alpha"], "beta": ["beta"], "alpha + beta": ["alpha", "beta"]},
    "checkboxes": ["Third Box"],
    "heard_as": {"beta": ["bait a", "beater"], "Third Box": ["bird box"]},
    "said_alone": {"Third Box": "alpha"},
}}


@pytest.mark.parametrize(("said", "meant"), [
    ("animate as bait a", "beta"),
    ("animate as beater", "beta"),
    ("animate as alpha plus beater", "alpha + beta"),
    ("animate as beater bird box", "beta + Third Box"),
    ("animate as genau beta bird box", "beta + Third Box"),
])
def test_a_name_is_heard_in_every_form_the_overlay_says_it_is_heard_as(said, meant):
    assert match_animate_command(said, spoken_actions(_HEARD)).action == meant


def test_a_checkbox_said_alone_means_the_button_the_overlay_names_with_it_checked():
    actions = spoken_actions(_HEARD)

    assert match_animate_command("animate as third box", actions).action == "alpha + Third Box"
    assert match_animate_command("animate as bird box", actions).action == "alpha + Third Box"


def test_the_recognizer_is_offered_every_form_a_name_is_heard_as():
    offered = animate_command_phrases(spoken_actions(_HEARD))

    assert {"animate as bait a", "animate as go now beater bird box",
            "animate as bird box", "animate as third box"} <= offered


def test_a_name_heard_in_another_form_is_said_back_as_its_own_name():
    assert animate_command_spelling("animate as genau bait a bird box",
                                    spoken_actions(_HEARD)) == "animate as Genau beta + Third Box"
    assert animate_command_spelling("animate as bird box",
                                    spoken_actions(_HEARD)) == "animate as alpha + Third Box"


def test_an_overlay_with_no_forms_and_no_lone_checkboxes_hears_only_the_names():
    plain = {"video_actions": {"buttons": {"beta": ["beta"]}, "checkboxes": ["Third Box"]}}

    assert spoken_actions(plain) == {"beta": "beta", "beta third box": "beta + Third Box"}
