from __future__ import annotations

import pytest

from origenerator import animation_paths
from origenerator.action_settings import GENAU, VIDEO
from origenerator.content import EXAMPLE_CONTENT, load_content

_PATHS = {"video_actions": {
    "buttons": {"alpha": ["alpha"], "beta": ["beta"], "gamma": ["gamma"]},
    "checkboxes": ["third box"],
    "starts_from": {
        VIDEO: {
            "alpha": ["state one", "state two"],
            "beta": ["state two"],
            "gamma": ["state three"],
        },
        GENAU: {
            "alpha": ["state two"],
        },
    },
}}


@pytest.fixture
def paths(monkeypatch):
    monkeypatch.setattr(animation_paths, "load_content", lambda: _PATHS)


def test_a_state_offers_the_actions_its_row_says_yes_to(paths):
    assert animation_paths.actions_for("state two", VIDEO) == ("alpha", "beta")
    assert animation_paths.actions_for("state two", GENAU) == ("alpha",)


def test_a_state_no_action_answers_offers_nothing(paths):
    assert animation_paths.actions_for("state one", GENAU) == ()
    assert animation_paths.actions_for("a state the table never heard of", VIDEO) == ()


def test_the_table_answers_whether_one_animation_is_on_it(paths):
    assert animation_paths.allows(VIDEO, "alpha", "state one") is True
    assert animation_paths.allows(VIDEO, "alpha", "state three") is False
    assert animation_paths.allows(GENAU, "gamma", "state three") is False


def test_an_action_with_a_checkbox_starts_from_the_images_the_action_alone_does(paths):
    assert animation_paths.allows(VIDEO, "alpha + third box", "state one") is True
    assert animation_paths.allows(VIDEO, "alpha + third box", "state three") is False


def test_every_animation_listed_is_each_action_alone_then_with_each_checkbox(paths):
    assert animation_paths.every_path() == (
        (VIDEO, "alpha", "state one"), (VIDEO, "alpha", "state two"),
        (VIDEO, "alpha + third box", "state one"), (VIDEO, "alpha + third box", "state two"),
        (VIDEO, "beta", "state two"), (VIDEO, "beta + third box", "state two"),
        (VIDEO, "gamma", "state three"), (VIDEO, "gamma + third box", "state three"),
        (GENAU, "alpha", "state two"), (GENAU, "alpha + third box", "state two"))


_COMPOUND = {"video_actions": {
    "buttons": {"one": ["alpha"], "two": ["beta"], "both": ["alpha", "beta"],
                "unlisted": ["alpha", "gamma"], "listed": ["alpha", "beta"]},
    "starts_from": {
        VIDEO: {
            "one": ["state three", "state one", "state two"],
            "two": ["state two", "state four", "state three"],
            "listed": ["state four"],
        },
    },
}}


def test_a_button_of_several_actions_starts_from_the_images_each_of_its_actions_does():
    assert animation_paths.actions_for("state two", VIDEO, content=_COMPOUND) == (
        "one", "two", "both")
    assert animation_paths.actions_for("state one", VIDEO, content=_COMPOUND) == ("one",)
    assert animation_paths.allows(VIDEO, "both", "state three", content=_COMPOUND) is True


def test_the_images_a_button_of_several_actions_starts_from_keep_its_first_actions_order():
    every = animation_paths.every_path(content=_COMPOUND)

    assert [state for lane, name, state in every if name == "both"] == [
        "state three", "state two"]


def test_a_button_of_several_actions_with_a_line_of_its_own_keeps_that_line():
    assert animation_paths.allows(VIDEO, "listed", "state four", content=_COMPOUND) is True
    assert animation_paths.allows(VIDEO, "listed", "state two", content=_COMPOUND) is False


def test_a_button_one_of_whose_actions_has_no_button_of_its_own_starts_from_nothing():
    assert not [path for path in animation_paths.every_path(content=_COMPOUND)
                if path[1] == "unlisted"]


def test_an_overlay_that_predates_the_table_allows_nothing():
    assert animation_paths.actions_for("state one", VIDEO, content={}) == ()
    assert animation_paths.allows(VIDEO, "alpha", "state one", content={}) is False


def test_a_malformed_line_costs_that_line_and_no_more():
    content = {"video_actions": {"starts_from": {
        VIDEO: {"alpha": ["state one", 7, ""], "beta": "state two", "": ["state one"]},
        GENAU: [],
    }}}

    assert animation_paths.actions_for("state one", VIDEO, content=content) == ("alpha",)
    assert animation_paths.actions_for("state two", VIDEO, content=content) == ()
    assert animation_paths.actions_for("state two", GENAU, content=content) == ()


def test_the_example_table_names_only_buttons_the_example_declares():
    example = load_content(EXAMPLE_CONTENT, EXAMPLE_CONTENT)
    actions = set(example["video_actions"]["buttons"])
    states = set(example["image_actions"]["buttons"])
    table = example["video_actions"]["starts_from"]

    assert table
    for lane, written in table.items():
        assert set(written) <= actions, lane
        for action, listed in written.items():
            assert set(listed) <= states, (lane, action)
            assert all(animation_paths.allows(lane, action, state, content=example)
                       for state in listed)
