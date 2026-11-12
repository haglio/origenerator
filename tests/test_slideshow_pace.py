from __future__ import annotations

from shared_ui.testing import appending_to

from origenerator.gui.slideshow_pace import DEFAULT_S, MAX_S, MIN_S, STEP_S, SlideshowPace


def test_a_pace_starts_at_the_default_unless_handed_a_number_of_seconds():
    assert SlideshowPace().seconds == DEFAULT_S
    assert SlideshowPace(seconds=9).seconds == 9


def test_a_pace_cannot_be_set_past_either_end():
    pace = SlideshowPace()
    pace.set_seconds(MAX_S + 100)
    assert pace.seconds == MAX_S
    pace.set_seconds(MIN_S - 100)
    assert pace.seconds == MIN_S


def test_a_pace_handed_too_many_seconds_at_the_start_is_held_to_the_longest():
    assert SlideshowPace(seconds=MAX_S + 5).seconds == MAX_S


def test_stepping_walks_the_pace_by_the_given_amount_and_stops_at_the_ends():
    pace = SlideshowPace(seconds=MAX_S - STEP_S)
    pace.step(STEP_S)
    pace.step(STEP_S)
    assert pace.seconds == MAX_S


def test_a_change_is_announced_with_the_new_seconds_and_a_repeat_is_not():
    pace = SlideshowPace(seconds=5)
    heard = []
    pace.changed.connect(appending_to(heard))

    pace.set_seconds(7)
    pace.set_seconds(7)

    assert heard == [7]
