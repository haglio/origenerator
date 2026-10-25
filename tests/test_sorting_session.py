"""Fixture values are fabricated throughout (see CLAUDE.md)."""
from __future__ import annotations

from origenerator.sorting_session import SortingSession


class _Store:
    def __init__(self):
        self.states = {}

    def set_image_state(self, prompt_id, state):
        self.states[prompt_id] = state


def _images(*prompt_ids):
    return [{"prompt_id": prompt_id} for prompt_id in prompt_ids]


def test_a_pick_is_recorded_on_the_image_on_screen_and_the_next_one_comes_up():
    store = _Store()
    session = SortingSession(_images("first", "second"), store)

    session.sort_as("state two")

    assert store.states == {"first": "state two"}
    assert session.current["prompt_id"] == "second"
    assert session.remaining == 1


def test_a_pick_with_nothing_on_screen_does_nothing():
    store = _Store()
    session = SortingSession([], store)

    session.sort_as("state two")

    assert store.states == {}
    assert session.current is None


def test_skipping_sends_the_image_to_the_back_of_the_line_unsorted():
    store = _Store()
    session = SortingSession(_images("first", "second"), store)

    session.skip()

    assert store.states == {}
    assert session.current["prompt_id"] == "second"
    assert session.remaining == 2


def test_undo_takes_the_last_pick_back_and_puts_its_image_on_screen_again():
    store = _Store()
    session = SortingSession(_images("first", "second"), store)
    session.sort_as("state two")

    session.undo()

    assert store.states == {"first": None}
    assert session.current["prompt_id"] == "first"
    assert session.remaining == 2


def test_undo_with_nothing_picked_yet_changes_nothing():
    store = _Store()
    session = SortingSession(_images("first"), store)

    session.undo()

    assert store.states == {}
    assert session.current["prompt_id"] == "first"


def test_same_gives_the_image_on_screen_the_last_state_picked():
    store = _Store()
    session = SortingSession(_images("first", "second", "third"), store)
    session.sort_as("state two")
    session.skip()

    session.same()

    assert store.states == {"first": "state two", "third": "state two"}
    assert session.current["prompt_id"] == "second"


def test_the_session_says_what_the_last_state_picked_was():
    session = SortingSession(_images("first", "second"), _Store())
    assert session.last_state is None

    session.sort_as("state two")
    assert session.last_state == "state two"

    session.undo()
    assert session.last_state is None


def test_the_session_says_whether_there_is_anything_to_undo():
    session = SortingSession(_images("first"), _Store())
    assert session.can_undo is False

    session.sort_as("state one")
    assert session.can_undo is True
