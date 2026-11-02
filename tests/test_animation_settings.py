"""Fixture values are fabricated throughout (see CLAUDE.md)."""
from __future__ import annotations

import pytest

from origenerator import animation_settings
from origenerator.action_settings import GENAU, VIDEO


@pytest.fixture
def held(tmp_path):
    return tmp_path / "animation_settings.json"


def test_nothing_is_accepted_before_anything_has_been(held):
    assert animation_settings.settings_for(VIDEO, "alpha", "state one", path=held) is None
    assert animation_settings.accepted(path=held) == set()


def test_an_accepted_animation_reads_back_as_settings(held):
    animation_settings.remember(VIDEO, "alpha", "state one",
                                workflow="wan22_i2v", params={"steps": 8}, path=held)

    assert animation_settings.settings_for(VIDEO, "alpha", "state one", path=held) == {
        "workflow": "wan22_i2v", "params": {"steps": 8}}
    assert animation_settings.accepted(path=held) == {(VIDEO, "alpha", "state one")}


def test_the_same_act_in_another_state_or_lane_is_another_animation(held):
    animation_settings.remember(VIDEO, "alpha", "state one",
                                workflow="wan22_i2v", params={"steps": 8}, path=held)

    assert animation_settings.settings_for(VIDEO, "alpha", "state two", path=held) is None
    assert animation_settings.settings_for(GENAU, "alpha", "state one", path=held) is None


def test_accepting_again_replaces_what_the_animation_had(held):
    animation_settings.remember(VIDEO, "alpha", "state one",
                                workflow="wan22_i2v", params={"steps": 8}, path=held)
    animation_settings.remember(VIDEO, "alpha", "state one",
                                workflow="wan22_i2v", params={"steps": 20}, path=held)

    assert animation_settings.settings_for(
        VIDEO, "alpha", "state one", path=held)["params"] == {"steps": 20}


def test_taking_an_animation_back_leaves_the_rest_alone(held):
    for state in ("state one", "state two"):
        animation_settings.remember(VIDEO, "alpha", state,
                                    workflow="wan22_i2v", params={}, path=held)

    animation_settings.forget(VIDEO, "alpha", "state one", path=held)

    assert animation_settings.accepted(path=held) == {(VIDEO, "alpha", "state two")}


def test_taking_back_one_nobody_accepted_changes_nothing(held):
    animation_settings.forget(VIDEO, "alpha", "state one", path=held)

    assert not held.exists()


def test_an_entry_naming_no_workflow_is_no_settings(held):
    held.write_text('{"video": {"alpha": {"state one": {"params": {}}}}}',
                    encoding="utf-8")

    assert animation_settings.settings_for(VIDEO, "alpha", "state one", path=held) is None


def test_a_file_that_will_not_parse_starts_empty_rather_than_refusing_to_open(held):
    held.write_text("{not json at all", encoding="utf-8")

    assert animation_settings.settings_for(VIDEO, "alpha", "state one", path=held) is None
    assert animation_settings.accepted(path=held) == set()


def test_a_reader_never_meets_a_half_written_file(held):
    animation_settings.remember(VIDEO, "alpha", "state one",
                                workflow="wan22_i2v", params={}, path=held)

    assert held.is_file()
    assert not held.with_suffix(".partial.json").exists()


def test_an_animation_answered_by_prompts_alone_is_still_answered(held):
    """An animation with no kept video has no workflow to copy, so what he types
    is all there is -- and reading it back is what makes Assign mean anything."""
    animation_settings.remember(VIDEO, "alpha", "state one", workflow="",
                                params={"positive_prompt": "a scene"}, path=held)

    assert animation_settings.settings_for(VIDEO, "alpha", "state one", path=held) == {
        "workflow": "", "params": {"positive_prompt": "a scene"}}


def test_the_accepted_settings_are_kept_in_the_file_every_copy_already_reads():
    assert animation_settings.SETTINGS_PATH.name == "animation_recipes.json"
