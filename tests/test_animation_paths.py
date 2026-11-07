from __future__ import annotations

import pytest

from origenerator import animation_paths
from origenerator.action_settings import GENAU, VIDEO
from origenerator.content import EXAMPLE_CONTENT, load_content

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


def test_a_state_offers_the_actions_its_row_says_yes_to(paths):
    assert animation_paths.actions_for("state two", VIDEO) == ("alpha", "beta")
    assert animation_paths.actions_for("state two", GENAU) == ("alpha",)


def test_a_lane_offers_every_action_the_table_gives_it_in_its_own_order(paths):
    assert animation_paths.actions(VIDEO) == ("alpha", "beta", "gamma")
    assert animation_paths.actions(GENAU) == ("alpha",)


def test_a_state_no_action_answers_offers_nothing(paths):
    assert animation_paths.actions_for("state one", GENAU) == ()
    assert animation_paths.actions_for("a state the table never heard of", VIDEO) == ()


def test_the_table_answers_whether_one_animation_is_on_it(paths):
    assert animation_paths.allows(VIDEO, "alpha", "state one") is True
    assert animation_paths.allows(VIDEO, "alpha", "state three") is False
    assert animation_paths.allows(GENAU, "gamma", "state three") is False


def test_an_overlay_that_predates_the_table_allows_nothing():
    assert animation_paths.actions_for("state one", VIDEO, content={}) == ()
    assert animation_paths.allows(VIDEO, "alpha", "state one", content={}) is False


def test_a_malformed_line_costs_that_line_and_no_more():
    content = {"animation_paths": {
        VIDEO: {"alpha": ["state one", 7, ""], "beta": "state two", "": ["state one"]},
        GENAU: [],
    }}

    assert animation_paths.actions_for("state one", VIDEO, content=content) == ("alpha",)
    assert animation_paths.actions_for("state two", VIDEO, content=content) == ()
    assert animation_paths.actions_for("state two", GENAU, content=content) == ()


def test_the_example_table_names_only_actions_and_states_the_example_declares():
    example = load_content(EXAMPLE_CONTENT, EXAMPLE_CONTENT)
    actions = set(example["actions"])
    states = set(example["image_states"])
    table = example["animation_paths"]

    assert table
    for lane, written in table.items():
        assert set(written) <= actions, lane
        for action, listed in written.items():
            assert set(listed) <= states, (lane, action)
            assert all(animation_paths.allows(lane, action, state, content=example)
                       for state in listed)
