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
