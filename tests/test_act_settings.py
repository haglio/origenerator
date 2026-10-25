"""act_settings: pick the one best set of settings for a dropdown act from the gallery.

Each act maps to one set of settings — the most-used model+params among the user's
videos of that act — resolved fresh from the gallery rows. Which act a video is
of is the one picked for it when it was launched, never a reading of its prompt.
Pure and Qt-free, so the grouping and act-matching logic is exercised without a
database or a widget.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json

from origenerator import act_settings


def _video(pid, act, created, **params):
    """A completed i2v row: the act it was launched as, created_at (recency), and
    the params that define its settings."""
    return {
        "prompt_id": pid,
        "workflow_name": "wan22_i2v",
        "act": act,
        "positive_prompt": f"a picture of something, {pid}",
        "created_at": created,
        "params_json": json.dumps({"positive_prompt": f"a picture of something, {pid}",
                                   **params}),
    }


def _loop(pid, act, created, **params):
    """The same row from a looping workflow — the only kind Genau settings can
    come from, since a Genau clip has to return to the frame it started on."""
    return {**_video(pid, act, created, **params), "workflow_name": "wan22_flf2v_loop"}


def test_most_used_video_picks_the_most_used_settings_for_the_act():
    rows = [
        _video("a1", "alpha", "2026-01-01", lora_high="X", steps=20),
        _video("a2", "alpha", "2026-01-02", lora_high="X", steps=20),  # same settings as a1
        _video("b1", "alpha", "2026-01-03", lora_high="Y", steps=20),  # rarer settings
        _video("h1", "beta", "2026-01-09", lora_high="Z", steps=20),   # a different act
    ]
    # settings X (used twice) beat settings Y (once); its most-recent row represents it.
    assert act_settings.most_used_video("alpha", rows) == "a2"


def test_an_act_no_video_does_has_no_most_used_video():
    rows = [_video("h1", "beta", "2026-01-01", lora_high="Z")]
    assert act_settings.most_used_video("alpha", rows) is None


def test_a_video_launched_as_no_act_counts_toward_none():
    rows = [{**_video("n1", "", "2026-01-01", lora_high="X")},
            _video("a1", "alpha", "2026-01-02", lora_high="X")]
    assert act_settings.most_used_video("alpha", rows) == "a1"
    assert act_settings.available_categories(rows) == {"alpha", "gamma"}


def test_available_categories_are_those_with_a_video_to_mine_or_pinned_settings():
    rows = [
        _video("h1", "beta", "2026-01-01", lora_high="Z"),
        _video("c1", "epsilon", "2026-01-02", lora_high="Z"),
    ]
    # The acts the gallery can mine settings for, plus "gamma" — the example
    # overlay pins settings for it, so it needs no past video. The rest have
    # nothing to answer with, so the panel greys them out.
    assert act_settings.available_categories(rows) == {"beta", "epsilon", "gamma"}


def test_available_categories_offers_only_curated_acts_without_any_video():
    # An empty gallery leaves nothing to mine — only the overlay-curated act stands.
    assert act_settings.available_categories([]) == {"gamma"}


# --- pinned_settings: the overlay's hand-tuned act settings --------------------


def test_a_curated_act_takes_the_settings_the_overlay_names():
    spec = act_settings.pinned_settings("gamma")  # curated in the example overlay
    assert spec["workflow"] == "wan22_i2v"
    assert spec["params"]["lora_high"] == "example-act-high.safetensors"


def test_pinned_settings_are_none_for_an_unpinned_act():
    assert act_settings.pinned_settings("beta") is None


def test_pinned_settings_are_none_for_a_malformed_entry(monkeypatch):
    # A bad entry must send the caller to mining, never fail the act outright.
    monkeypatch.setitem(act_settings._CURATED_BY_INTENT, act_settings.VIDEO,
                        {"beta": "not a dict", "epsilon": {"params": {}}})
    assert act_settings.pinned_settings("beta") is None      # not a dict
    assert act_settings.pinned_settings("epsilon") is None   # names no workflow


def test_most_used_video_groups_ignoring_prompt_seed_and_input_image():
    rows = [
        _video("a1", "alpha", "2026-01-01", lora_high="X", seed=1, noise_seed=9, input_image="i1.png"),
        _video("a2", "alpha", "2026-01-02", lora_high="X", seed=2, noise_seed=8, input_image="i2.png"),
        _video("b1", "alpha", "2026-01-03", lora_high="Y", seed=3, input_image="i3.png"),
    ]
    # a1 and a2 differ only in prompt/seed/frame — one set of settings, used twice — so it wins.
    assert act_settings.most_used_video("alpha", rows) == "a2"


def test_settings_grouping_ignores_derived_size_and_length_params():
    # Same model+LoRA, but different output size (derived from the input image), clip
    # length, and sampler split points — none of which define the settings.
    rows = [
        _video("a1", "alpha", "2026-01-01", lora_high="X", steps=20,
               width=512, height=768, frame_count=81, start_at_step=10, end_at_step=10000, frame_rate=16.0),
        _video("a2", "alpha", "2026-01-02", lora_high="X", steps=20,
               width=1024, height=576, frame_count=121, start_at_step=10, end_at_step=20, frame_rate=24.0),
        _video("b1", "alpha", "2026-01-03", lora_high="Y", steps=20),  # a real difference: the LoRA
    ]
    # a1 and a2 are one set of settings (used twice) despite differing size/length → it wins,
    # represented by the most recent (a2). Without the exclusions they'd each be a
    # singleton and the newest overall (b1) would win instead.
    assert act_settings.most_used_video("alpha", rows) == "a2"


def test_most_used_video_breaks_count_ties_by_recency():
    rows = [
        _video("a1", "alpha", "2026-01-01", lora_high="X"),  # settings used once, older
        _video("b1", "alpha", "2026-01-05", lora_high="Y"),  # settings used once, newer
    ]
    assert act_settings.most_used_video("alpha", rows) == "b1"


def test_most_used_video_keeps_each_act_to_the_videos_launched_as_it():
    rows = [
        _video("f1", "delta", "2026-01-01", lora_high="X"),
        _video("c1", "epsilon", "2026-01-02", lora_high="Y"),
        _video("d1", "dancing", "2026-01-03", lora_high="Z"),
    ]
    assert act_settings.most_used_video("delta", rows) == "f1"
    assert act_settings.most_used_video("epsilon", rows) == "c1"
    assert act_settings.most_used_video("dancing", rows) == "d1"
    assert act_settings.most_used_video("beta", rows) is None  # nothing was made as this act


# --- scene_matched_video: LLM picks the situation-fitting variant within an act ------


def _scene_video(pid, act, start_scene, created, **params):
    """An act video plus the starting scene it's made for (its input image's prompt)."""
    return {**_video(pid, act, created, **params), "start_scene": start_scene}


def test_the_model_is_offered_one_video_per_settings_group_and_its_pick_is_used(monkeypatch):
    rows = [
        _scene_video("x1", "alpha", "she kneels", "2026-01-01", lora_high="X"),
        _scene_video("x2", "alpha", "his anchor already in her grip", "2026-01-02", lora_high="X"),
        _scene_video("y1", "alpha", "she waits, no anchor in frame", "2026-01-03", lora_high="Y"),
    ]
    seen = {}

    def fake_post(base_url, model, messages, timeout):
        seen["user"] = messages[1]["content"]
        return {"choices": [{"message": {"content": '{"choice": 0}'}}]}

    monkeypatch.setattr(act_settings, "_post_chat", fake_post)
    got = act_settings.scene_matched_video(
        "alpha", "a prominent anchor in the frame", rows,
        base_url="x", model="m", system_prompt="S", timeout=1,
    )
    # settings X are one option (their most-recent row x2 represents them), settings Y another.
    assert got == "x2"                                     # choice 0 → settings X's representative
    assert "his anchor already in her grip" in seen["user"]  # X shown by x2's start scene, not x1's
    assert "she waits, no anchor in frame" in seen["user"]   # Y is offered too


def test_an_act_no_video_does_is_not_put_to_the_model_at_all(monkeypatch):
    monkeypatch.setattr(act_settings, "_post_chat",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call the model")))
    rows = [_scene_video("h1", "beta", "her hand on it", "2026-01-01", lora_high="Z")]
    assert act_settings.scene_matched_video("alpha", "x", rows,
                                            base_url="x", model="m", system_prompt="S", timeout=1) is None


def test_scene_matched_video_ignores_rows_lacking_a_start_scene(monkeypatch):
    rows = [
        _scene_video("x1", "alpha", "", "2026-01-01", lora_high="X"),          # no scene to match on
        _scene_video("y1", "alpha", "anchor in frame", "2026-01-02", lora_high="Y"),
    ]
    monkeypatch.setattr(act_settings, "_post_chat",
                        lambda *a, **k: {"choices": [{"message": {"content": '{"choice": 0}'}}]})
    assert act_settings.scene_matched_video("alpha", "x", rows,
                                            base_url="x", model="m", system_prompt="S", timeout=1) == "y1"


def test_a_model_that_finds_no_fit_leaves_the_video_unchosen(monkeypatch):
    rows = [_scene_video("x1", "alpha", "she kneels", "2026-01-01", lora_high="X")]
    monkeypatch.setattr(act_settings, "_post_chat",
                        lambda *a, **k: {"choices": [{"message": {"content": '{"choice": -1}'}}]})
    assert act_settings.scene_matched_video("alpha", "x", rows,
                                            base_url="x", model="m", system_prompt="S", timeout=1) is None


def test_a_model_that_fails_leaves_the_video_unchosen(monkeypatch):
    rows = [_scene_video("x1", "alpha", "she kneels", "2026-01-01", lora_high="X")]
    monkeypatch.setattr(act_settings, "_post_chat",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("model down")))
    assert act_settings.scene_matched_video("alpha", "x", rows,
                                            base_url="x", model="m", system_prompt="S", timeout=1) is None


# --- the two lanes: a full-length video, or one looping cycle ----------------


def test_genau_mines_only_looping_videos():
    rows = [
        _video("v1", "beta", "2026-01-01", lora_high="Z"),   # long-form: not a loop
        _loop("l1", "beta", "2026-01-02", lora_high="Z"),
    ]
    # The video lane sees both and prefers the newer of the one shared set of settings;
    # the Genau lane can only use the loop, whatever else the act has under it.
    assert act_settings.most_used_video("beta", rows) == "l1"
    assert act_settings.most_used_video("beta", rows, act_settings.GENAU) == "l1"

    long_form_only = [_video("v1", "beta", "2026-01-01", lora_high="Z")]
    assert act_settings.most_used_video("beta", long_form_only) == "v1"
    assert act_settings.most_used_video("beta", long_form_only, act_settings.GENAU) is None


def test_genau_available_categories_need_a_loop_or_pinned_settings():
    rows = [
        _video("v1", "epsilon", "2026-01-01", lora_high="Z"),
        _loop("l1", "delta", "2026-01-02", lora_high="Z"),
    ]
    # epsilon has a video but no loop, so the Genau lane cannot answer it; delta can
    # be mined from the loop; beta is pinned in the example overlay's pinned_genau_settings.
    assert act_settings.available_categories(rows, act_settings.GENAU) == {"delta", "beta"}
    # The video lane is unchanged by any of it — a loop is still a video there.
    assert act_settings.available_categories(rows) == {"epsilon", "delta", "gamma"}


def test_the_two_curated_tables_are_independent():
    # The same act can be pinned in one lane and mined in the other: one table keyed
    # by act alone could never hold both.
    assert act_settings.pinned_settings("gamma")["workflow"] == "wan22_i2v"
    assert act_settings.pinned_settings("gamma", act_settings.GENAU) is None
    assert act_settings.pinned_settings("beta", act_settings.GENAU)["workflow"] == "wan22_flf2v_loop"
    assert act_settings.pinned_settings("beta") is None


def test_scene_matched_video_offers_the_genau_lane_only_loops(monkeypatch):
    seen = {}

    def _fake_post(base_url, model, messages, timeout):
        seen["user"] = messages[1]["content"]
        return {"choices": [{"message": {"content": '{"choice": 0}'}}]}

    monkeypatch.setattr(act_settings, "_post_chat", _fake_post)
    rows = [
        _scene_video("v1", "beta", "a long-form scene", "2026-01-01", lora_high="Z"),
        {**_loop("l1", "beta", "2026-01-02", lora_high="Z"), "start_scene": "a looping scene"},
    ]
    chosen = act_settings.scene_matched_video(
        "beta", "the dropped image", rows,
        base_url="http://localhost", model="m", system_prompt="s",
        intent=act_settings.GENAU,
    )
    assert chosen == "l1"
    # The long-form video was never even shown to the model.
    assert "a long-form scene" not in seen["user"]
    assert "a looping scene" in seen["user"]


# --- act_of: what a generation shows -------------------------------------------


def test_a_generation_shows_the_act_picked_for_it_in_combine():
    row = {"act": "beta", "positive_prompt": "she is dancing on a table"}

    assert act_settings.act_of(row) == "beta"


def test_a_picture_shows_the_action_it_was_sorted_as():
    assert act_settings.act_of({"picture_state": "state two"}) == "state two"


def test_a_generation_nobody_has_said_an_act_for_shows_none():
    assert act_settings.act_of({"positive_prompt": "a beta form, slowly"}) == ""
    assert act_settings.act_of({}) == ""


def test_an_act_with_no_past_video_says_so_in_its_lanes_own_words(monkeypatch):
    monkeypatch.setattr(act_settings, "genau_flick_word", lambda: "flick")

    assert act_settings.no_past_video("alpha", act_settings.VIDEO) == (
        "no past “alpha” video to take settings from yet")
    assert act_settings.no_past_video("alpha", act_settings.GENAU) == (
        "no past looping “alpha” flick to take settings from yet")


def test_a_line_that_opens_a_sentence_capitalizes_its_first_letter_alone():
    assert act_settings.as_sentence("no past “Alpha” video") == "No past “Alpha” video"
