from __future__ import annotations

import io
import json

import pytest

from origenerator.action_vocabulary import actions_heard_as
from origenerator.voice import hosted
from origenerator.voice.app_commands import AppCommand, match_app_command, spoken_phrases
from origenerator.voice.commands import hosted_phrases
from origenerator.voice.dictation import LEAD_WORDS, request_bias


def _told() -> dict:
    out = io.StringIO()
    hosted.main(out)
    return json.loads(out.getvalue())


def test_a_hosting_session_is_told_the_phrases_the_openers_the_hint_the_lock_and_the_actions():
    assert _told() == {
        "phrases": sorted(hosted_phrases()),
        "openers": list(LEAD_WORDS),
        "speech_hint": request_bias(),
        "lock_phrases": sorted(phrase for phrase in spoken_phrases()
                               if match_app_command(phrase) is AppCommand.LOCK),
        "labels_heard_as": {name: list(forms) for name, forms in actions_heard_as().items()},
    }


def test_the_words_for_the_lock_a_hosting_session_is_told_of_take_in_hold():
    assert {"lock", "hold"} <= set(_told()["lock_phrases"])


def test_a_hosting_session_hears_the_word_that_opens_a_request():
    assert "request" in hosted_phrases()


@pytest.mark.parametrize("phrase", [
    "favorites", "experiments", "start slideshow", "fix hands", "enhance", "undo", "lock",
    "enhanced only", "original only", "enhanced and original", "original and enhanced",
    "clear filter", "populate on",
])
def test_a_hosting_session_hears_what_this_app_answers_while_hosted(phrase):
    assert phrase in hosted_phrases()


@pytest.mark.parametrize("phrase", [
    "speed up", "amp fifty", "max center", "next shape", "human inspired",
    "audio on", "drive off", "osr two control on", "mic off",
])
def test_a_hosting_session_does_not_hear_what_it_answers_itself(phrase):
    assert phrase not in hosted_phrases()


def test_a_hosting_session_is_told_every_action_a_video_can_have_and_how_each_is_heard():
    assert _told()["labels_heard_as"] == {
        "alpha": ["alpha"], "beta": ["beta", "bait a"], "gamma": ["gamma"],
        "first box": ["first box"], "second box": ["second box"], "third box": ["third box", "bird box"]}
