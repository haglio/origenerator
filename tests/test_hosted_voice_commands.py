from __future__ import annotations

import io
import json

import pytest

from origenerator.voice import hosted
from origenerator.voice.commands import hosted_phrases
from origenerator.voice.dictation import LEAD_WORDS, request_bias


def test_a_hosting_session_is_told_the_phrases_the_words_that_open_a_request_and_the_hint():
    out = io.StringIO()

    hosted.main(out)

    assert json.loads(out.getvalue()) == {
        "phrases": sorted(hosted_phrases()),
        "openers": list(LEAD_WORDS),
        "speech_hint": request_bias(),
    }


def test_a_hosting_session_hears_the_word_that_opens_a_request():
    assert "request" in hosted_phrases()


@pytest.mark.parametrize("phrase", [
    "favorites", "experiments", "start slideshow", "fix hands", "enhance", "undo", "lock",
    "enhanced only", "clear filter", "auto on",
])
def test_a_hosting_session_hears_what_this_app_answers_while_hosted(phrase):
    assert phrase in hosted_phrases()


@pytest.mark.parametrize("phrase", [
    "speed up", "amp fifty", "max center", "next shape", "human inspired", "offset",
    "audio on", "drive off", "osr two control on", "mic off",
])
def test_a_hosting_session_does_not_hear_what_it_answers_itself(phrase):
    assert phrase not in hosted_phrases()
