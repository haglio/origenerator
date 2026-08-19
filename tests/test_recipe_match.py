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


def _loop(pid, prompt, created, **params):
    """The same row from a looping workflow — the only kind a Genau recipe can
    come from, since a Genau clip has to return to the frame it started on."""
    return {**_video(pid, prompt, created, **params), "workflow_name": "wan22_flf2v_loop"}


def test_best_recipe_picks_the_most_used_recipe_for_the_act():
    rows = [
        _video("a1", "a slow alpha", "2026-01-01", lora_high="X", steps=20),
        _video("a2", "alpha form him off", "2026-01-02", lora_high="X", steps=20),  # same recipe as a1
        _video("b1", "an alpha form scene", "2026-01-03", lora_high="Y", steps=20),    # a rarer recipe
        _video("h1", "a beta", "2026-01-09", lora_high="Z", steps=20),        # a different act
    ]
    # recipe X (used twice) beats recipe Y (once); its most-recent member represents it.
    assert recipe_match.best_recipe("alpha", rows) == "a2"


def test_best_recipe_returns_none_without_a_video_of_that_act():
    rows = [_video("h1", "a beta", "2026-01-01", lora_high="Z")]
    assert recipe_match.best_recipe("alpha", rows) is None


def test_available_categories_are_those_with_a_video_to_mine_or_a_curated_recipe():
    rows = [
        _video("h1", "a beta", "2026-01-01", lora_high="Z"),
        _video("c1", "an epsilon form moment", "2026-01-02", lora_high="Z"),
    ]
    # The acts the gallery can mine a recipe for, plus "gamma" — the example
    # overlay curates a recipe for it, so it needs no past video. The rest have
    # nothing to answer with, so the panel greys them out.
    assert recipe_match.available_categories(rows) == {"beta", "epsilon", "gamma"}


def test_available_categories_offers_only_curated_acts_without_any_video():
    # An empty gallery leaves nothing to mine — only the overlay-curated act stands.
    assert recipe_match.available_categories([]) == {"gamma"}


# --- curated_recipe: the overlay's hand-tuned act recipes ---------------------


def test_curated_recipe_returns_the_overlays_entry():
    spec = recipe_match.curated_recipe("gamma")  # curated in the example overlay
    assert spec["workflow"] == "wan22_i2v"
    assert spec["params"]["lora_high"] == "example-act-high.safetensors"


def test_curated_recipe_is_none_for_an_uncurated_act():
    assert recipe_match.curated_recipe("beta") is None


def test_curated_recipe_is_none_for_a_malformed_entry(monkeypatch):
    # A junk entry must send the caller to mining, never fail the act outright.
    monkeypatch.setitem(recipe_match._CURATED_BY_INTENT, recipe_match.PLAYERS,
                        {"beta": "not a dict", "epsilon": {"params": {}}})
    assert recipe_match.curated_recipe("beta") is None      # not a dict
    assert recipe_match.curated_recipe("epsilon") is None   # names no workflow


def test_best_recipe_groups_ignoring_prompt_seed_and_input_image():
    rows = [
        _video("a1", "alpha one", "2026-01-01", lora_high="X", seed=1, noise_seed=9, input_image="i1.png"),
        _video("a2", "alpha two", "2026-01-02", lora_high="X", seed=2, noise_seed=8, input_image="i2.png"),
        _video("b1", "alpha three", "2026-01-03", lora_high="Y", seed=3, input_image="i3.png"),
    ]
    # a1 and a2 differ only in prompt/seed/frame — one recipe, used twice — so it wins.
    assert recipe_match.best_recipe("alpha", rows) == "a2"


def test_recipe_grouping_ignores_derived_size_and_length_params():
    # Same model+LoRA, but different output size (derived from the input image), clip
    # length, and sampler split points — none of which define the recipe.
    rows = [
        _video("a1", "a alpha", "2026-01-01", lora_high="X", steps=20,
               width=512, height=768, frame_count=81, start_at_step=10, end_at_step=10000, frame_rate=16.0),
        _video("a2", "a alpha", "2026-01-02", lora_high="X", steps=20,
               width=1024, height=576, frame_count=121, start_at_step=10, end_at_step=20, frame_rate=24.0),
        _video("b1", "a alpha", "2026-01-03", lora_high="Y", steps=20),  # a real difference: the LoRA
    ]
    # a1 and a2 are one recipe (used twice) despite differing size/length → it wins,
    # represented by the most recent (a2). Without the exclusions they'd each be a
    # singleton and the newest overall (b1) would win instead.
    assert recipe_match.best_recipe("alpha", rows) == "a2"


def test_best_recipe_breaks_count_ties_by_recency():
    rows = [
        _video("a1", "a alpha", "2026-01-01", lora_high="X"),  # a recipe used once, older
        _video("b1", "alpha form", "2026-01-05", lora_high="Y"),       # a recipe used once, newer
    ]
    assert recipe_match.best_recipe("alpha", rows) == "b1"


def test_best_recipe_reads_the_act_from_the_prompt_per_category():
    rows = [
        _video("f1", "hardcore delta, delta form", "2026-01-01", lora_high="X"),
        _video("c1", "a big epsilon on her chest", "2026-01-02", lora_high="Y"),
        _video("d1", "she is dancing and twerking", "2026-01-03", lora_high="Z"),
    ]
    assert recipe_match.best_recipe("delta", rows) == "f1"
    assert recipe_match.best_recipe("epsilon", rows) == "c1"
    assert recipe_match.best_recipe("dancing", rows) == "d1"
    assert recipe_match.best_recipe("beta", rows) is None  # nothing depicts this act


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
        _scene_video("x1", "a alpha", "she kneels", "2026-01-01", lora_high="X"),
        _scene_video("x2", "a alpha", "his anchor already in her grip", "2026-01-02", lora_high="X"),
        _scene_video("y1", "a alpha", "she waits, no anchor in frame", "2026-01-03", lora_high="Y"),
    ]
    seen = {}

    def fake_post(base_url, model, messages, timeout):
        seen["user"] = messages[1]["content"]
        return {"choices": [{"message": {"content": '{"choice": 0}'}}]}

    monkeypatch.setattr(recipe_match, "_post_chat", fake_post)
    got = recipe_match.smart_recipe(
        "alpha", "a prominent anchor in the frame", rows,
        base_url="x", model="m", system_prompt="S", timeout=1,
    )
    # recipe X is one option (its most-recent member x2 represents it), recipe Y another.
    assert got == "x2"                                     # choice 0 → recipe X's representative
    assert "his anchor already in her grip" in seen["user"]  # X shown by x2's start scene, not x1's
    assert "she waits, no anchor in frame" in seen["user"]   # Y is offered too


def test_smart_recipe_returns_none_without_a_video_of_the_act(monkeypatch):
    monkeypatch.setattr(recipe_match, "_post_chat",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call the model")))
    rows = [_scene_video("h1", "a beta", "her hand on it", "2026-01-01", lora_high="Z")]
    assert recipe_match.smart_recipe("alpha", "x", rows,
                                     base_url="x", model="m", system_prompt="S", timeout=1) is None


def test_smart_recipe_ignores_members_lacking_a_start_scene(monkeypatch):
    rows = [
        _scene_video("x1", "a alpha", "", "2026-01-01", lora_high="X"),          # no scene to match on
        _scene_video("y1", "a alpha", "anchor in frame", "2026-01-02", lora_high="Y"),
    ]
    monkeypatch.setattr(recipe_match, "_post_chat",
                        lambda *a, **k: {"choices": [{"message": {"content": '{"choice": 0}'}}]})
    assert recipe_match.smart_recipe("alpha", "x", rows,
                                     base_url="x", model="m", system_prompt="S", timeout=1) == "y1"


def test_smart_recipe_returns_none_when_the_llm_finds_no_fit(monkeypatch):
    rows = [_scene_video("x1", "a alpha", "she kneels", "2026-01-01", lora_high="X")]
    monkeypatch.setattr(recipe_match, "_post_chat",
                        lambda *a, **k: {"choices": [{"message": {"content": '{"choice": -1}'}}]})
    assert recipe_match.smart_recipe("alpha", "x", rows,
                                     base_url="x", model="m", system_prompt="S", timeout=1) is None


def test_smart_recipe_returns_none_when_the_llm_errors(monkeypatch):
    rows = [_scene_video("x1", "a alpha", "she kneels", "2026-01-01", lora_high="X")]
    monkeypatch.setattr(recipe_match, "_post_chat",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("model down")))
    assert recipe_match.smart_recipe("alpha", "x", rows,
                                     base_url="x", model="m", system_prompt="S", timeout=1) is None


# --- the two lanes: a full-length video, or one looping stroke ----------------


def test_genau_mines_only_looping_videos():
    rows = [
        _video("v1", "a beta", "2026-01-01", lora_high="Z"),   # long-form: not a loop
        _loop("l1", "a beta", "2026-01-02", lora_high="Z"),
    ]
    # The players' lane sees both and prefers the newer of the one shared recipe;
    # the Genau lane can only use the loop, whatever else the act has behind it.
    assert recipe_match.best_recipe("beta", rows) == "l1"
    assert recipe_match.best_recipe("beta", rows, recipe_match.GENAU) == "l1"

    long_form_only = [_video("v1", "a beta", "2026-01-01", lora_high="Z")]
    assert recipe_match.best_recipe("beta", long_form_only) == "v1"
    assert recipe_match.best_recipe("beta", long_form_only, recipe_match.GENAU) is None


def test_genau_available_categories_need_a_loop_or_a_pinned_recipe():
    rows = [
        _video("v1", "an epsilon form moment", "2026-01-01", lora_high="Z"),
        _loop("l1", "a delta form", "2026-01-02", lora_high="Z"),
    ]
    # epsilon has a video but no loop, so the Genau lane cannot answer it; delta can
    # be mined from the loop; beta is pinned in the example overlay's genau_recipes.
    assert recipe_match.available_categories(rows, recipe_match.GENAU) == {"delta", "beta"}
    # The players' lane is unchanged by any of it — a loop is still a video there.
    assert recipe_match.available_categories(rows) == {"epsilon", "delta", "gamma"}


def test_the_two_curated_tables_are_independent():
    # The same act can be pinned in one lane and mined in the other: one table keyed
    # by act alone could never hold both.
    assert recipe_match.curated_recipe("gamma")["workflow"] == "wan22_i2v"
    assert recipe_match.curated_recipe("gamma", recipe_match.GENAU) is None
    assert recipe_match.curated_recipe("beta", recipe_match.GENAU)["workflow"] == "wan22_flf2v_loop"
    assert recipe_match.curated_recipe("beta") is None


def test_smart_recipe_offers_the_genau_lane_only_loops(monkeypatch):
    seen = {}

    def _fake_post(base_url, model, messages, timeout):
        seen["user"] = messages[1]["content"]
        return {"choices": [{"message": {"content": '{"choice": 0}'}}]}

    monkeypatch.setattr(recipe_match, "_post_chat", _fake_post)
    rows = [
        {**_video("v1", "a beta", "2026-01-01", lora_high="Z"), "start_scene": "a long-form scene"},
        {**_loop("l1", "a beta", "2026-01-02", lora_high="Z"), "start_scene": "a looping scene"},
    ]
    chosen = recipe_match.smart_recipe(
        "beta", "the dropped image", rows,
        base_url="http://localhost", model="m", system_prompt="s",
        intent=recipe_match.GENAU,
    )
    assert chosen == "l1"
    # The long-form recipe was never even shown to the model.
    assert "a long-form scene" not in seen["user"]
    assert "a looping scene" in seen["user"]


# --- category_for_prompt: let the image say what it is ------------------------


def test_category_for_prompt_reads_the_act_off_a_prompt():
    assert recipe_match.category_for_prompt("a beta form, slowly") == "beta"
    assert recipe_match.category_for_prompt("she is dancing on a table") == "dancing"


def test_category_for_prompt_is_none_when_the_prompt_names_no_act():
    assert recipe_match.category_for_prompt("a portrait by a window") is None
    assert recipe_match.category_for_prompt("") is None
    assert recipe_match.category_for_prompt(None) is None


def test_category_for_prompt_prefers_the_more_specific_reading():
    # "beta form" (both acts' keyword lists overlap on the shorter "beta") must not
    # be decided by dict order: the longer, more specific keyword wins.
    assert recipe_match.category_for_prompt("beta form") == "beta"
    # A prompt naming two acts outright resolves to the longer keyword it matched.
    assert recipe_match.category_for_prompt("striptease, then a beta") == "dancing"
