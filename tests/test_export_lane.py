from __future__ import annotations

import dataclasses

from origenerator.content import genau_flick_word
from origenerator.export_lane import GENAU, KINO


def test_the_genau_lane_calls_what_it_sends_by_genaus_word_for_it():
    lane = dataclasses.replace(GENAU, word=lambda: "flick")

    said = [lane.tooltip, lane.unsend_tooltip, lane.withdrawn_tooltip, lane.failure_body("gone")]

    assert all("this flick" in words for words in said), said
    assert not any("clip" in words for words in said), (
        "clip is no word the screen shows: Genau's videos take the word the settings all of "
        "Haglio share give them")


def test_the_genau_lanes_word_is_the_one_haglios_settings_give_genaus_videos():
    assert GENAU.noun == genau_flick_word()


def test_the_kino_lane_calls_what_it_sends_a_video():
    assert KINO.noun == "video"
    assert "this video" in KINO.withdrawn_tooltip


def test_each_send_button_says_it_sends_to_its_app_in_plain_words():
    lane = dataclasses.replace(GENAU, word=lambda: "flick")

    said = [lane.tooltip, lane.withdrawn_tooltip, KINO.tooltip, KINO.withdrawn_tooltip]

    assert (lane.tooltip.startswith("Send this flick to Genau:"),
            KINO.tooltip.startswith("Send this video to Kino:"),
            [words for words in said if "lane" in words]) == (True, True, [])
