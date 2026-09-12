"""Which thumbnails are picked, with no pane and no Qt around it.

The rule is a file browser's, and it used to be three fields and fourteen lines
among the pane's widgets: the only way to ask what a Shift-click would pick was to
build a pane, draw tiles into it and read the highlights back off them.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import pytest

from origenerator.gui.thumbnail_selection import ThumbnailSelection


@pytest.fixture
def picked():
    def build(*shown):
        selection = ThumbnailSelection()
        for prompt_id in shown:
            selection.note_shown(prompt_id)
        return selection
    return build


def test_a_plain_click_picks_that_one_and_nothing_else(picked):
    selection = picked("a", "b", "c")

    selection.apply("b")

    assert selection.picked == {"b"}


def test_a_second_plain_click_replaces_the_first(picked):
    selection = picked("a", "b", "c")
    selection.apply("a")

    selection.apply("c")

    assert selection.picked == {"c"}


def test_ctrl_adds_one_and_ctrl_again_takes_it_back(picked):
    selection = picked("a", "b", "c")
    selection.apply("a")

    selection.apply("c", ctrl=True)
    assert selection.picked == {"a", "c"}

    selection.apply("c", ctrl=True)
    assert selection.picked == {"a"}


def test_shift_extends_a_contiguous_run_from_the_anchor(picked):
    selection = picked("a", "b", "c", "d")
    selection.apply("b")

    selection.apply("d", shift=True)

    assert selection.picked == {"b", "c", "d"}


def test_a_run_reaches_backwards_just_as_far(picked):
    selection = picked("a", "b", "c", "d")
    selection.apply("d")

    selection.apply("b", shift=True)

    assert selection.picked == {"b", "c", "d"}


def test_ctrl_moves_the_anchor_so_the_next_run_starts_there(picked):
    selection = picked("a", "b", "c", "d")
    selection.apply("a")

    selection.apply("c", ctrl=True)
    selection.apply("d", shift=True)

    assert selection.picked == {"c", "d"}  # the run is from c, not from a


def test_a_shift_click_with_its_anchor_gone_lands_as_a_plain_click(picked):
    # A pane redrawn under the selection, or a shelf paged on, leaves the anchor
    # nowhere on screen: there is no run to measure, and a range from nowhere is
    # worse than the one tile that was actually clicked.
    selection = picked("a", "b")
    selection.apply("a")
    selection.forget_what_was_shown()
    for prompt_id in ("x", "y", "z"):
        selection.note_shown(prompt_id)

    selection.apply("y", shift=True)

    assert selection.picked == {"y"}


def test_a_shift_click_on_a_tile_that_is_not_on_screen_is_a_plain_click_too(picked):
    selection = picked("a", "b", "c")
    selection.apply("a")

    selection.apply("elsewhere", shift=True)

    assert selection.picked == {"elsewhere"}


def test_the_picked_are_reported_in_the_order_the_pane_shows_them(picked):
    # An act on a whole selection runs through them, so it runs in the order the
    # user sees rather than in whatever order a set happens to hold.
    selection = picked("a", "b", "c", "d")
    selection.apply("d")
    selection.apply("b", ctrl=True)

    assert selection.in_shown_order() == ["b", "d"]


def test_a_picked_tile_no_longer_on_screen_drops_out_of_that_order(picked):
    selection = picked("a", "b")
    selection.apply("a")
    selection.apply("b", ctrl=True)
    selection.forget_what_was_shown()
    selection.note_shown("b")

    assert selection.in_shown_order() == ["b"]
    assert selection.picked == {"a", "b"}  # the set itself is cleared separately


def test_clearing_takes_the_run_with_it(picked):
    selection = picked("a", "b", "c")
    selection.apply("a")

    selection.clear()
    selection.apply("c", shift=True)

    assert selection.picked == {"c"}  # no anchor left to measure a run from


def test_what_is_on_screen_is_handed_back_as_a_copy(picked):
    selection = picked("a", "b")

    shown = selection.shown
    shown.append("c")

    assert selection.shown == ["a", "b"]


def test_a_tile_is_asked_whether_it_is_picked_rather_than_reading_the_set(picked):
    selection = picked("a", "b")
    selection.apply("a")

    assert selection.holds("a") is True
    assert selection.holds("b") is False
