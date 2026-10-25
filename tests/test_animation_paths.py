"""Fixture values are fabricated throughout (see CLAUDE.md)."""
from __future__ import annotations

import pytest

from origenerator import animation_paths
from origenerator.act_settings import GENAU, VIDEO
from origenerator.content import EXAMPLE_CONTENT, load_content
from origenerator.image_states import state_names

# A small stand-in for the overlay's own table: two lanes, three acts, three states.
_PATHS = {
    "animation_paths": {
        VIDEO: {
            "alpha": ["state one", "state two"],
            "beta": ["state two"],
            "gamma": ["state three"],
        },
        GENAU: {
            "alpha": ["state two"],
        },
    },
}


@pytest.fixture
def paths(monkeypatch):
    monkeypatch.setattr(animation_paths, "load_content", lambda: _PATHS)


def test_a_state_offers_the_acts_its_row_says_yes_to(paths):
    assert animation_paths.acts_for("state two", VIDEO) == ("alpha", "beta")
    assert animation_paths.acts_for("state two", GENAU) == ("alpha",)


def test_a_lane_offers_every_act_the_table_gives_it_in_its_own_order(paths):
    """What the Action list carries: the acts his sheet has a row for in that
    lane, in the order they are written down."""
    assert animation_paths.acts(VIDEO) == ("alpha", "beta", "gamma")
    assert animation_paths.acts(GENAU) == ("alpha",)


def test_a_state_no_act_answers_offers_nothing(paths):
    assert animation_paths.acts_for("state one", GENAU) == ()
    assert animation_paths.acts_for("a state the table never heard of", VIDEO) == ()


def test_the_table_answers_whether_one_animation_is_on_it(paths):
    assert animation_paths.allows(VIDEO, "alpha", "state one") is True
    assert animation_paths.allows(VIDEO, "alpha", "state three") is False
    assert animation_paths.allows(GENAU, "gamma", "state three") is False


def test_an_overlay_that_predates_the_table_allows_nothing():
    assert animation_paths.acts_for("state one", VIDEO, content={}) == ()
    assert animation_paths.allows(VIDEO, "alpha", "state one", content={}) is False


def test_a_malformed_line_costs_that_line_and_no_more():
    content = {"animation_paths": {
        VIDEO: {"alpha": ["state one", 7, ""], "beta": "state two", "": ["state one"]},
        GENAU: [],
    }}

    assert animation_paths.acts_for("state one", VIDEO, content=content) == ("alpha",)
    assert animation_paths.acts_for("state two", VIDEO, content=content) == ()
    assert animation_paths.acts_for("state two", GENAU, content=content) == ()


def test_the_example_table_names_only_acts_and_states_the_example_declares():
    """The two vocabularies the table is written in are the overlay's own, so a
    line naming an act or a state nothing declares is a line that can never fire.
    Held over the committed example, which is what documents the shape."""
    example = load_content(EXAMPLE_CONTENT, EXAMPLE_CONTENT)
    acts = set(example["acts"])
    states = set(state_names(example))
    table = example["animation_paths"]

    assert table
    for lane, written in table.items():
        assert set(written) <= acts, lane
        for act, listed in written.items():
            assert set(listed) <= states, (lane, act)
            assert all(animation_paths.allows(lane, act, state, content=example)
                       for state in listed)
