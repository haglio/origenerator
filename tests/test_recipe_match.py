"""recipe_match: category-driven routing of a dropped image to an exemplar recipe.

Pure (Qt-free, no live LLM): the HTTP boundary is one seam the tests stub, so
candidate-building, prefiltering, message-building, response parsing and the
deterministic fallback are all exercised without a server.
"""

import pytest

from origenerator import recipe_match


def _row(pid, prompt, **extra):
    return {"prompt_id": pid, "positive_prompt": prompt, **extra}


def _completion(content):
    """A minimal OpenAI-style chat completion carrying ``content``."""
    return {"choices": [{"message": {"content": content}}]}


def test_build_candidates_reads_id_and_prompt_dropping_useless_rows():
    rows = [
        _row("v1", "she gives a slow gamma"),
        _row("v2", ""),                    # empty prompt: nothing to match on
        _row("v3", None),                  # no prompt at all
        {"positive_prompt": "orphan"},     # no id: cannot be launched
    ]
    cands = recipe_match.build_candidates(rows)
    assert [(c.prompt_id, c.prompt) for c in cands] == [("v1", "she gives a slow gamma")]


def test_deterministic_choice_picks_category_match_with_best_overlap():
    image = "a woman kneeling, anchor near her mouth, blue room"
    cands = recipe_match.build_candidates([
        _row("bj_far", "gamma, plain background"),                                 # right act, no scene overlap
        _row("bj_near", "gamma, woman kneeling, anchor near mouth, blue room"),     # right act + best scene match
        _row("hj", "epsilon, woman kneeling, anchor, blue room"),                     # high overlap but wrong act
    ])
    assert recipe_match.deterministic_choice("gamma", image, cands) == "bj_near"


def test_deterministic_choice_returns_none_without_a_category_match():
    cands = recipe_match.build_candidates([_row("hj", "a epsilon scene, anchor near mouth")])
    assert recipe_match.deterministic_choice("gamma", "anchor near mouth", cands) is None


def test_prefilter_floats_category_matches_up_and_caps_at_k():
    image = "anchor near her mouth"
    cands = recipe_match.build_candidates([
        _row("other1", "a mountain landscape"),
        _row("bj1", "gamma, anchor near mouth"),   # act match + best overlap
        _row("other2", "a sleeping cat"),
        _row("bj2", "gamma, standing"),            # act match, no scene overlap
    ])
    top = recipe_match.prefilter("gamma", image, cands, 3)
    assert [c.prompt_id for c in top[:2]] == ["bj1", "bj2"]  # act matches first, best overlap leads
    assert len(top) == 3                                     # capped at k, padded with the rest


def test_build_messages_carries_category_image_and_numbered_candidates():
    cands = [recipe_match.Candidate("v0", "gamma A"), recipe_match.Candidate("v1", "gamma B")]
    msgs = recipe_match.build_messages("gamma", "anchor near mouth", cands, "SYSTEM RULES")
    assert msgs[0] == {"role": "system", "content": "SYSTEM RULES"}
    assert msgs[1]["role"] == "user"
    user = msgs[1]["content"]
    assert "gamma" in user                       # the desired act
    assert "anchor near mouth" in user              # the image description to match against
    assert "0" in user and "gamma A" in user     # candidates numbered from 0 (the choice index)
    assert "1" in user and "gamma B" in user
    assert "choice" in user                        # the JSON reply contract


def test_parse_choice_maps_index_to_prompt_id():
    cands = [recipe_match.Candidate("v0", "a"), recipe_match.Candidate("v1", "b")]
    assert recipe_match.parse_choice(_completion('{"choice": 1}'), cands) == "v1"


def test_parse_choice_none_for_negative_or_out_of_range():
    cands = [recipe_match.Candidate("v0", "a")]
    assert recipe_match.parse_choice(_completion('{"choice": -1}'), cands) is None  # "none fit"
    assert recipe_match.parse_choice(_completion('{"choice": 9}'), cands) is None   # hallucinated index


def test_parse_choice_tolerates_fenced_json():
    cands = [recipe_match.Candidate("v0", "a"), recipe_match.Candidate("v1", "b")]
    reply = 'Sure!\n```json\n{"choice": 0}\n```'
    assert recipe_match.parse_choice(_completion(reply), cands) == "v0"


def test_parse_choice_raises_on_unusable_reply():
    # No JSON at all: the caller catches this and falls back to the deterministic pick.
    with pytest.raises(Exception):
        recipe_match.parse_choice(_completion("I couldn't decide"), [recipe_match.Candidate("v0", "a")])


def test_choose_recipe_returns_the_llms_pick(monkeypatch):
    rows = [_row("bj1", "gamma, anchor near mouth"), _row("hj1", "epsilon scene")]
    seen = {}

    def fake_post(base_url, model, messages, timeout):
        seen["messages"] = messages
        return _completion('{"choice": 0}')  # index into the prefiltered list (bj1 leads)

    monkeypatch.setattr(recipe_match, "_post_chat", fake_post)
    got = recipe_match.choose_recipe(
        "gamma", "anchor near mouth", rows,
        base_url="http://x", model="m", system_prompt="SYS", timeout=1,
    )
    assert got == "bj1"
    assert "anchor near mouth" in seen["messages"][1]["content"]  # it really consulted the model


def test_choose_recipe_falls_back_to_deterministic_when_the_model_errors(monkeypatch):
    rows = [_row("bj_near", "gamma, anchor near mouth"), _row("bj_far", "gamma, standing")]

    def boom(*a, **k):
        raise OSError("model down")

    monkeypatch.setattr(recipe_match, "_post_chat", boom)
    got = recipe_match.choose_recipe(
        "gamma", "anchor near mouth", rows,
        base_url="http://x", model="m", system_prompt="SYS", timeout=1,
    )
    assert got == "bj_near"  # deterministic: the act match with the best scene overlap


def test_choose_recipe_none_when_no_candidates(monkeypatch):
    def must_not_call(*a, **k):
        raise AssertionError("no candidates: must not hit the model")

    monkeypatch.setattr(recipe_match, "_post_chat", must_not_call)
    assert recipe_match.choose_recipe(
        "gamma", "anything", [],
        base_url="http://x", model="m", system_prompt="SYS", timeout=1,
    ) is None
