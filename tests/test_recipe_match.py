"""recipe_match: pick the one best recipe for a dropdown act from the gallery.

Each act maps to a single recipe — the most-used model+params among the user's
videos of that act — resolved fresh from the gallery rows. Pure and Qt-free, so the
grouping and act-membership logic is exercised without a database or a widget.
"""

import json

from origenerator import recipe_match


def _video(pid, prompt, created, **params):
    """A completed i2v row: its prompt (act membership), created_at (recency), and
    the params that define its recipe."""
    return {
        "prompt_id": pid,
        "workflow_name": "wan22_i2v",
        "positive_prompt": prompt,
        "created_at": created,
        "params_json": json.dumps({"positive_prompt": prompt, **params}),
    }


def test_best_recipe_picks_the_most_used_recipe_for_the_act():
    rows = [
        _video("a1", "a slow gamma", "2026-01-01", lora_high="X", steps=20),
        _video("a2", "redacted him off", "2026-01-02", lora_high="X", steps=20),  # same recipe as a1
        _video("b1", "an oral scene", "2026-01-03", lora_high="Y", steps=20),    # a rarer recipe
        _video("h1", "a epsilon", "2026-01-09", lora_high="Z", steps=20),        # a different act
    ]
    # recipe X (used twice) beats recipe Y (once); its most-recent member represents it.
    assert recipe_match.best_recipe("gamma", rows) == "a2"


def test_best_recipe_returns_none_without_a_video_of_that_act():
    rows = [_video("h1", "a epsilon", "2026-01-01", lora_high="Z")]
    assert recipe_match.best_recipe("gamma", rows) is None


def test_best_recipe_groups_ignoring_prompt_seed_and_input_image():
    rows = [
        _video("a1", "gamma one", "2026-01-01", lora_high="X", seed=1, noise_seed=9, input_image="i1.png"),
        _video("a2", "gamma two", "2026-01-02", lora_high="X", seed=2, noise_seed=8, input_image="i2.png"),
        _video("b1", "gamma three", "2026-01-03", lora_high="Y", seed=3, input_image="i3.png"),
    ]
    # a1 and a2 differ only in prompt/seed/frame — one recipe, used twice — so it wins.
    assert recipe_match.best_recipe("gamma", rows) == "a2"


def test_recipe_grouping_ignores_derived_size_and_length_params():
    # Same model+LoRA, but different output size (derived from the input image), clip
    # length, and sampler split points — none of which define the recipe.
    rows = [
        _video("a1", "a gamma", "2026-01-01", lora_high="X", steps=20,
               width=512, height=768, frame_count=81, start_at_step=10, end_at_step=10000, frame_rate=16.0),
        _video("a2", "a gamma", "2026-01-02", lora_high="X", steps=20,
               width=1024, height=576, frame_count=121, start_at_step=10, end_at_step=20, frame_rate=24.0),
        _video("b1", "a gamma", "2026-01-03", lora_high="Y", steps=20),  # a real difference: the LoRA
    ]
    # a1 and a2 are one recipe (used twice) despite differing size/length → it wins,
    # represented by the most recent (a2). Without the exclusions they'd each be a
    # singleton and the newest overall (b1) would win instead.
    assert recipe_match.best_recipe("gamma", rows) == "a2"


def test_best_recipe_breaks_count_ties_by_recency():
    rows = [
        _video("a1", "a gamma", "2026-01-01", lora_high="X"),  # a recipe used once, older
        _video("b1", "oral", "2026-01-05", lora_high="Y"),       # a recipe used once, newer
    ]
    assert recipe_match.best_recipe("gamma", rows) == "b1"


def test_best_recipe_reads_the_act_from_the_prompt_per_category():
    rows = [
        _video("f1", "hardcore redacted, doggy", "2026-01-01", lora_high="X"),
        _video("c1", "a big alpha on her chest", "2026-01-02", lora_high="Y"),
        _video("d1", "she is dancing and twerking", "2026-01-03", lora_high="Z"),
    ]
    assert recipe_match.best_recipe("redacted", rows) == "f1"
    assert recipe_match.best_recipe("alpha", rows) == "c1"
    assert recipe_match.best_recipe("dancing", rows) == "d1"
    assert recipe_match.best_recipe("epsilon", rows) is None  # nothing depicts this act


# --- smart_recipe: LLM picks the situation-fitting variant within an act ------


def _scene_video(pid, prompt, start_scene, created, **params):
    """An act video plus the starting scene it's made for (its input image's prompt)."""
    return {
        "prompt_id": pid,
        "workflow_name": "wan22_i2v",
        "positive_prompt": prompt,
        "start_scene": start_scene,
        "created_at": created,
        "params_json": json.dumps({"positive_prompt": prompt, **params}),
    }


def test_smart_recipe_offers_one_representative_per_recipe_and_returns_the_llms_pick(monkeypatch):
    rows = [
        _scene_video("x1", "a gamma", "she kneels", "2026-01-01", lora_high="X"),
        _scene_video("x2", "a gamma", "his anchor already at her lips", "2026-01-02", lora_high="X"),
        _scene_video("y1", "a gamma", "she waits, no anchor in frame", "2026-01-03", lora_high="Y"),
    ]
    seen = {}

    def fake_post(base_url, model, messages, timeout):
        seen["user"] = messages[1]["content"]
        return {"choices": [{"message": {"content": '{"choice": 0}'}}]}

    monkeypatch.setattr(recipe_match, "_post_chat", fake_post)
    got = recipe_match.smart_recipe(
        "gamma", "an redacted anchor in the frame", rows,
        base_url="x", model="m", system_prompt="S", timeout=1,
    )
    # recipe X is one option (its most-recent member x2 represents it), recipe Y another.
    assert got == "x2"                                     # choice 0 → recipe X's representative
    assert "his anchor already at her lips" in seen["user"]  # X shown by x2's start scene, not x1's
    assert "she waits, no anchor in frame" in seen["user"]   # Y is offered too


def test_smart_recipe_returns_none_without_a_video_of_the_act(monkeypatch):
    monkeypatch.setattr(recipe_match, "_post_chat",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call the model")))
    rows = [_scene_video("h1", "a epsilon", "her hand on it", "2026-01-01", lora_high="Z")]
    assert recipe_match.smart_recipe("gamma", "x", rows,
                                     base_url="x", model="m", system_prompt="S", timeout=1) is None


def test_smart_recipe_ignores_members_lacking_a_start_scene(monkeypatch):
    rows = [
        _scene_video("x1", "a gamma", "", "2026-01-01", lora_high="X"),          # no scene to match on
        _scene_video("y1", "a gamma", "anchor in frame", "2026-01-02", lora_high="Y"),
    ]
    monkeypatch.setattr(recipe_match, "_post_chat",
                        lambda *a, **k: {"choices": [{"message": {"content": '{"choice": 0}'}}]})
    assert recipe_match.smart_recipe("gamma", "x", rows,
                                     base_url="x", model="m", system_prompt="S", timeout=1) == "y1"


def test_smart_recipe_returns_none_when_the_llm_finds_no_fit(monkeypatch):
    rows = [_scene_video("x1", "a gamma", "she kneels", "2026-01-01", lora_high="X")]
    monkeypatch.setattr(recipe_match, "_post_chat",
                        lambda *a, **k: {"choices": [{"message": {"content": '{"choice": -1}'}}]})
    assert recipe_match.smart_recipe("gamma", "x", rows,
                                     base_url="x", model="m", system_prompt="S", timeout=1) is None


def test_smart_recipe_returns_none_when_the_llm_errors(monkeypatch):
    rows = [_scene_video("x1", "a gamma", "she kneels", "2026-01-01", lora_high="X")]
    monkeypatch.setattr(recipe_match, "_post_chat",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("model down")))
    assert recipe_match.smart_recipe("gamma", "x", rows,
                                     base_url="x", model="m", system_prompt="S", timeout=1) is None
