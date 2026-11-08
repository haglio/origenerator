from __future__ import annotations

import json

from origenerator import action_settings
from origenerator.animation_names import item_actions_named
from origenerator.item_actions import stored


def _video(pid, action, created, **params):
    actions, checked = stored(item_actions_named(action)) if action else (None, None)
    return {
        "prompt_id": pid,
        "workflow_name": "wan22_i2v",
        "video_actions": actions,
        "video_checked": checked,
        "positive_prompt": f"an image of something, {pid}",
        "created_at": created,
        "params_json": json.dumps({"positive_prompt": f"an image of something, {pid}",
                                   **params}),
    }


def _loop(pid, action, created, **params):
    return {**_video(pid, action, created, **params), "workflow_name": "wan22_flf2v_loop"}


def test_most_used_video_picks_the_most_used_settings_for_the_action():
    rows = [
        _video("a1", "alpha", "2026-01-01", lora_high="X", steps=20),
        _video("a2", "alpha", "2026-01-02", lora_high="X", steps=20),
        _video("b1", "alpha", "2026-01-03", lora_high="Y", steps=20),
        _video("h1", "beta", "2026-01-09", lora_high="Z", steps=20),
    ]
    assert action_settings.most_used_video("alpha", rows) == "a2"


def test_an_action_no_video_does_has_no_most_used_video():
    rows = [_video("h1", "beta", "2026-01-01", lora_high="Z")]
    assert action_settings.most_used_video("alpha", rows) is None


def test_a_video_launched_as_no_action_counts_toward_none():
    rows = [{**_video("n1", "", "2026-01-01", lora_high="X")},
            _video("a1", "alpha", "2026-01-02", lora_high="X")]
    assert action_settings.most_used_video("alpha", rows) == "a1"
    assert action_settings.available_categories(rows) == {"alpha"}


def test_available_categories_are_those_with_a_video_to_mine_or_pinned_settings():
    rows = [
        _video("h1", "beta", "2026-01-01", lora_high="Z"),
        _video("c1", "alpha + beta + third box", "2026-01-02", lora_high="Z"),
    ]
    assert action_settings.available_categories(rows) == {"beta"}
    assert action_settings.available_categories(rows, checked=("third box",)) == {
        "alpha", "beta", "alpha + beta"}


def test_a_checkbox_with_settings_of_its_own_offers_every_action_with_it():
    assert action_settings.available_categories([]) == set()
    assert action_settings.available_categories([], checked=("third box",)) == {
        "alpha", "beta", "alpha + beta"}



def test_an_action_with_a_checkbox_takes_the_settings_the_overlay_pins_for_the_checkbox():
    spec = action_settings.pinned_settings("alpha + third box")
    assert spec["workflow"] == "wan22_i2v"
    assert spec["params"]["lora_high"] == "example-action-high.safetensors"


def test_pinned_settings_are_none_for_an_unpinned_action():
    assert action_settings.pinned_settings("beta") is None


def test_pinned_settings_are_none_for_a_malformed_entry(monkeypatch):
    monkeypatch.setitem(action_settings._CURATED_BY_INTENT, action_settings.VIDEO,
                        {"beta": "not a dict", "alpha": {"params": {}}})
    assert action_settings.pinned_settings("beta") is None
    assert action_settings.pinned_settings("alpha") is None


def test_most_used_video_groups_ignoring_prompt_seed_and_input_image():
    rows = [
        _video("a1", "alpha", "2026-01-01", lora_high="X", seed=1, noise_seed=9, input_image="i1.png"),
        _video("a2", "alpha", "2026-01-02", lora_high="X", seed=2, noise_seed=8, input_image="i2.png"),
        _video("b1", "alpha", "2026-01-03", lora_high="Y", seed=3, input_image="i3.png"),
    ]
    assert action_settings.most_used_video("alpha", rows) == "a2"


def test_settings_grouping_ignores_derived_size_and_length_params():
    rows = [
        _video("a1", "alpha", "2026-01-01", lora_high="X", steps=20,
               width=512, height=768, frame_count=81, start_at_step=10, end_at_step=10000, frame_rate=16.0),
        _video("a2", "alpha", "2026-01-02", lora_high="X", steps=20,
               width=1024, height=576, frame_count=121, start_at_step=10, end_at_step=20, frame_rate=24.0),
        _video("b1", "alpha", "2026-01-03", lora_high="Y", steps=20),
    ]
    assert action_settings.most_used_video("alpha", rows) == "a2"


def test_most_used_video_breaks_count_ties_by_recency():
    rows = [
        _video("a1", "alpha", "2026-01-01", lora_high="X"),
        _video("b1", "alpha", "2026-01-05", lora_high="Y"),
    ]
    assert action_settings.most_used_video("alpha", rows) == "b1"


def test_a_video_with_no_creation_time_counts_as_the_oldest_in_a_tie():
    rows = [
        _video("a1", "alpha", None, lora_high="X"),
        _video("b1", "alpha", "2026-01-01", lora_high="Y"),
    ]
    assert action_settings.most_used_video("alpha", rows) == "b1"


def test_most_used_video_keeps_each_action_to_the_videos_launched_as_it():
    rows = [
        _video("f1", "alpha + beta", "2026-01-01", lora_high="X"),
        _video("c1", "alpha + third box", "2026-01-02", lora_high="Y"),
        _video("d1", "alpha", "2026-01-03", lora_high="Z"),
    ]
    assert action_settings.most_used_video("alpha + beta", rows) == "f1"
    assert action_settings.most_used_video("alpha + third box", rows) == "c1"
    assert action_settings.most_used_video("alpha", rows) == "d1"
    assert action_settings.most_used_video("beta", rows) is None



def test_genau_mines_only_looping_videos():
    rows = [
        _video("v1", "beta", "2026-01-01", lora_high="Z"),
        _loop("l1", "beta", "2026-01-02", lora_high="Z"),
    ]
    assert action_settings.most_used_video("beta", rows) == "l1"
    assert action_settings.most_used_video("beta", rows, action_settings.GENAU) == "l1"

    long_form_only = [_video("v1", "beta", "2026-01-01", lora_high="Z")]
    assert action_settings.most_used_video("beta", long_form_only) == "v1"
    assert action_settings.most_used_video("beta", long_form_only, action_settings.GENAU) is None


def test_genau_available_categories_need_a_loop_or_pinned_settings():
    rows = [
        _video("v1", "alpha", "2026-01-01", lora_high="Z"),
        _loop("l1", "alpha + beta", "2026-01-02", lora_high="Z"),
    ]
    assert action_settings.available_categories(rows, action_settings.GENAU) == {
        "alpha + beta", "beta"}
    assert action_settings.available_categories(rows) == {"alpha", "alpha + beta"}


def test_the_two_curated_tables_are_independent():
    assert action_settings.pinned_settings("alpha + third box")["workflow"] == "wan22_i2v"
    assert action_settings.pinned_settings("alpha + third box", action_settings.GENAU) is None
    assert action_settings.pinned_settings("beta", action_settings.GENAU)["workflow"] == "wan22_flf2v_loop"
    assert action_settings.pinned_settings("beta") is None



def test_an_action_with_no_past_video_says_so_in_its_lanes_own_words(monkeypatch):
    monkeypatch.setattr(action_settings, "genau_flick_word", lambda: "flick")

    assert action_settings.no_past_video("alpha", action_settings.VIDEO) == (
        "no past “alpha” video to take settings from yet")
    assert action_settings.no_past_video("alpha", action_settings.GENAU) == (
        "no past looping “alpha” flick to take settings from yet")


def test_a_line_that_opens_a_sentence_capitalizes_its_first_letter_alone():
    assert action_settings.as_sentence("no past “Alpha” video") == "No past “Alpha” video"
