"""The press grammar, held against the spellings player_core itself emits.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import pytest
from player_core import drive_layout
from player_core.console import OSR2_CONTROL_BUTTONS
from player_core.drive_readout import CONTROL_TIPS, track_command

from origenerator.console_commands import (
    ROBOT_HAND,
    level_asked_for,
    side_press,
    side_spoken_to,
    spelled_for,
)

SIDES = ("portrait", "landscape")


@pytest.mark.parametrize("axis", [drive_layout.AMPLITUDE, drive_layout.CENTER,
                                  drive_layout.SPEED])
def test_a_level_press_is_read_back_as_the_axis_and_level_it_set(axis):
    assert level_asked_for(f"{ROBOT_HAND}{axis}_57") == (axis, 57)


def test_the_level_a_band_posts_is_one_this_side_reads():
    """The spelling is player_core's, so the press it builds is the input."""
    track = drive_layout.tracks(0, 0, 50)[0]
    posted = track_command(track, track.rect[0] + 1, track.rect[1] + 1)
    assert level_asked_for(posted) is not None


def test_every_verb_the_readout_names_is_spelled_the_way_this_side_expects():
    assert all(verb.startswith(ROBOT_HAND) for verb in CONTROL_TIPS)
    assert any(verb.startswith(ROBOT_HAND) for verb in OSR2_CONTROL_BUTTONS.values())


def test_a_press_that_is_not_a_level_is_left_for_the_rest_of_the_router():
    assert level_asked_for(f"{ROBOT_HAND}speed_up") is None
    assert level_asked_for(f"{ROBOT_HAND}amp_") is None
    assert level_asked_for("main_lock") is None
    assert level_asked_for("") is None


def test_a_side_press_is_the_verb_it_asks_and_what_it_carries():
    assert side_press("portrait", "portrait_next") == ("next", "")
    assert side_press("portrait", "portrait_play_video", "C:/x/y.mp4") == (
        "play_video", "C:/x/y.mp4")


def test_the_one_verb_spelled_the_other_way_round_carries_the_row_it_names():
    assert side_press("landscape", "filter_landscape_seeds") == ("filter", "seeds")


def test_a_side_spells_a_verb_the_way_the_press_it_takes_apart_was_spelled():
    assert side_press("portrait", spelled_for("portrait", "trash")) == ("trash", "")


def test_a_verb_names_the_side_it_is_said_to_however_it_is_cased():
    assert side_spoken_to("PORTRAIT_NEXT", SIDES) == "portrait"
    assert side_spoken_to("FILTER_LANDSCAPE_SEEDS", SIDES) == "landscape"
    assert side_spoken_to("landscape_lock", SIDES) == "landscape"
    assert side_spoken_to("OPEN_SHOWS", SIDES) is None
    assert side_spoken_to("PORTRAITS_OF_NOBODY", SIDES) is None
