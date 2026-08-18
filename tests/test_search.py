"""The gallery search's matching layer, with no Qt and no network in sight."""

import json

import pytest

from origenerator import search


def _row(prompt_id, positive, *, negative="", seed=1, workflow="sdxl_t2i",
         params=None, output=True):
    """One completed generation, as the database hands it over."""
    stored = {"positive_prompt": positive, "negative_prompt": negative, "seed": seed}
    stored.update(params or {})
    return {
        "prompt_id": prompt_id,
        "workflow_name": workflow,
        "positive_prompt": positive,
        "negative_prompt": negative,
        "seed": seed,
        "status": "completed",
        "output_files": json.dumps([f"{prompt_id}.png"]) if output else None,
        "params_json": json.dumps(stored),
    }


def _index(rows):
    index = search.GallerySearch()
    index.update(rows)
    return index


def _hits(index, query, **kwargs):
    return [result.row["prompt_id"] for result in index.search(query, **kwargs).results]


# --- the words a query is taken apart into ---------------------------------


def test_stop_words_are_dropped_from_a_query():
    assert search.query_words("a pair of dolls on the beach") == (
        "pair", "dolls", "beach")


def test_a_query_of_nothing_but_stop_words_keeps_them():
    # Better to search for "the" than to answer a typed query with everything.
    assert search.query_words("the of") == ("the", "of")


def test_a_repeated_word_is_searched_once():
    assert search.query_words("beach beach sunset") == ("beach", "sunset")


@pytest.mark.parametrize("plural, singular", [
    ("dolls", "doll"), ("berries", "berry"), ("dresses", "dress"),
    ("women", "woman"), ("men", "man"), ("children", "child"),
])
def test_a_plural_and_its_singular_are_one_key(plural, singular):
    rows = [_row("g1", f"three {singular} in a garden")]
    assert _hits(_index(rows), plural) == ["g1"]


def test_a_written_number_and_its_digit_are_one_key():
    rows = [_row("g1", "two lamps on a table")]
    assert _hits(_index(rows), "2 lamps") == ["g1"]
    assert _hits(_index([_row("g2", "3 lamps")]), "three lamps") == ["g2"]


# --- what counts as a match -------------------------------------------------


def test_a_synonym_satisfies_a_term_the_prompt_never_used():
    # The failure the whole module exists for: "two women" has to reach a run
    # prompted "two dolls", which a substring filter never would.
    rows = [_row("g1", "two dolls on a couch"),
            _row("g2", "two tall ladies at the beach"),
            _row("g3", "a single lady in the rain"),
            _row("g4", "an empty street at dawn")]
    assert set(_hits(_index(rows), "two women")) == {"g1", "g2"}


def test_every_word_of_the_query_has_to_be_satisfied():
    # A superset of the query matches; a row missing one of its words does not.
    rows = [_row("g1", "a red lamp on a wooden table"),
            _row("g2", "a red lamp")]
    assert _hits(_index(rows), "red lamp table") == ["g1"]


def test_a_word_nothing_reaches_is_named_back():
    rows = [_row("g1", "a red lamp")]
    outcome = _index(rows).search("red aardvark")
    assert outcome.results == ()
    assert outcome.unmatched == ("aardvark",)


def test_a_query_whose_words_are_all_present_but_never_together_names_nothing():
    # Both words are in the gallery, so neither is the one to drop — the pane
    # says so differently, and it needs to be able to tell the two apart.
    rows = [_row("g1", "a red lamp"), _row("g2", "a wooden table")]
    outcome = _index(rows).search("lamp table")
    assert outcome.results == ()
    assert outcome.unmatched == ()


def test_the_negative_prompt_is_not_searched():
    # A negative prompt is the list of things a run was told to keep OUT, so
    # every hit it produces is the opposite of what was asked for. Measured on a
    # real library, three quarters of one query's results came from here.
    rows = [_row("g1", "a quiet street", negative="rain, blur"),
            _row("g2", "rain over a quiet street")]
    assert _hits(_index(rows), "rain") == ["g2"]


def test_a_decimal_is_one_word_not_two():
    # An emphasis weight — (term:1.2) — used to leave a bare "2" behind, and a
    # query's "two" folds to "2": searching for two of something matched every
    # prompt that had ever weighted a term (52% of a real library).
    rows = [_row("g1", "a (red:1.2) lamp"), _row("g2", "two red lamps")]
    assert _hits(_index(rows), "two lamps") == ["g2"]


def test_bare_numbers_in_a_model_name_are_not_searchable():
    # A model filename is full of version parts, dates and counters, none of
    # them anything anyone searches for, and all of them colliding with the
    # digits a number word folds to. The names themselves stay reachable.
    rows = [_row("g1", "a quiet street", workflow="wan22_i2v", params={
        "unet_high": "example_2.2_high.safetensors",
        "unet_low": "example_2.2_low.safetensors",
    })]
    index = _index(rows)
    assert _hits(index, "two streets") == []   # the "2" of the version doesn't count
    assert _hits(index, "example") == ["g1"]   # the name itself still does


def test_a_model_or_lora_name_is_searchable():
    rows = [_row("g1", "a quiet street", workflow="wan22_i2v", params={
        "unet_high": "example_high.safetensors",
        "unet_low": "example_low.safetensors",
        "lora_high": "driftstyle_high.safetensors",
        "lora_low": "driftstyle_low.safetensors",
    }), _row("g2", "a quiet street")]
    assert _hits(_index(rows), "driftstyle") == ["g1"]


def test_a_seed_lands_on_the_one_generation_carrying_it():
    rows = [_row("g1", "a quiet street", seed=778899),
            _row("g2", "a quiet street", seed=112233)]
    assert _hits(_index(rows), "778899") == ["g1"]


def test_a_search_can_be_held_to_a_set_of_generations():
    # The gallery's tree selection is the scope: standing in a folder asks the
    # question there, and a hit outside it is not an answer.
    rows = [_row("g1", "a red lamp"), _row("g2", "a red lamp")]
    assert _hits(_index(rows), "lamp", within={"g2"}) == ["g2"]


def test_a_word_outside_the_scope_still_counts_as_unmatched():
    # The empty-result message is about the folder being searched, so a word
    # that exists elsewhere in the library but not here has still reached
    # nothing — and naming it is what tells the user to widen the folder.
    rows = [_row("g1", "a red lamp"), _row("g2", "a wooden table")]
    outcome = _index(rows).search("lamp", within={"g2"})
    assert outcome.results == ()
    assert outcome.unmatched == ("lamp",)


def test_an_empty_query_matches_nothing_rather_than_everything():
    rows = [_row("g1", "a quiet street")]
    assert _index(rows).search("   ") == search.SearchOutcome((), ())


# --- the LLM tier only ever widens -----------------------------------------


def test_a_volunteered_word_widens_the_match():
    rows = [_row("g1", "a lone kitten"), _row("g2", "a lone puppy")]
    index = _index(rows)
    assert _hits(index, "cat") == []
    assert _hits(index, "cat", expansions={"cat": ["kitten"]}) == ["g1"]


def test_a_volunteered_word_ranks_below_a_word_actually_written():
    rows = [_row("g1", "a lone kitten"), _row("g2", "a lone cat")]
    outcome = _index(rows).search("cat", expansions={"cat": ["kitten"]})
    by_id = {result.row["prompt_id"]: result.score for result in outcome.results}
    assert by_id["g2"] > by_id["g1"]


def test_an_expansion_for_a_word_not_in_the_query_is_ignored():
    rows = [_row("g1", "a lone kitten")]
    assert _hits(_index(rows), "puppy", expansions={"cat": ["kitten"]}) == []


# --- the index itself -------------------------------------------------------


def test_only_generations_that_produced_something_are_searchable():
    # Search is a way of finding something to look at; a failed or still-running
    # run has nothing to show.
    rows = [_row("g1", "a red lamp"), _row("g2", "a red lamp", output=False)]
    assert _hits(_index(rows), "lamp") == ["g1"]


def test_results_come_back_in_the_order_the_rows_were_given():
    # The view hands them over newest-first and reads them straight out, so the
    # index must not re-order them behind its own scoring.
    rows = [_row("g3", "a red lamp"), _row("g1", "a red lamp"),
            _row("g2", "a red lamp")]
    assert _hits(_index(rows), "lamp") == ["g3", "g1", "g2"]


def test_a_re_index_keeps_the_words_and_takes_the_fresh_row():
    # A poll rewrites every row dict without touching the text in it, which is
    # what makes reusing the tokenized entry safe — and worth doing.
    first = _row("g1", "a red lamp")
    index = _index([first])
    updated = dict(first, starred=1)
    index.update([updated])
    (result,) = index.search("lamp").results
    assert result.row is updated


def test_a_generation_that_leaves_the_gallery_leaves_the_index():
    index = _index([_row("g1", "a red lamp"), _row("g2", "a wooden table")])
    index.update([_row("g2", "a wooden table")])
    assert _hits(index, "lamp") == []


# --- grouping the results by the recipe that made them ----------------------


def _lora_row(prompt_id, lora, prompt="a quiet street"):
    return _row(prompt_id, prompt, workflow="wan22_i2v", params={
        "unet_high": "example_high.safetensors",
        "unet_low": "example_low.safetensors",
        "lora_high": f"{lora}_high.safetensors",
        "lora_low": f"{lora}_low.safetensors",
    })


def test_results_group_under_one_heading_per_model_and_lora():
    rows = [_lora_row("g1", "driftstyle"), _lora_row("g2", "driftstyle"),
            _lora_row("g3", "emberstyle")]
    sections = search.group_by_recipe(_index(rows).search("street").results)
    assert [[r.row["prompt_id"] for r in members] for _, members in sections] == [
        ["g1", "g2"], ["g3"]]
    assert "driftstyle" in sections[0][0]
    assert "emberstyle" in sections[1][0]


def test_the_biggest_combination_leads():
    # The recipe you use most is the one you are most likely reading through,
    # and it makes a one-off read as the outlier it is.
    rows = [_lora_row("g1", "emberstyle"), _lora_row("g2", "driftstyle"),
            _lora_row("g3", "driftstyle"), _lora_row("g4", "driftstyle")]
    sections = search.group_by_recipe(_index(rows).search("street").results)
    assert [len(members) for _, members in sections] == [3, 1]


def test_a_heading_names_both_the_model_and_the_lora():
    heading = search.recipe_heading(_lora_row("g1", "driftstyle"))
    assert "example_high" in heading and "driftstyle_high" in heading


# --- the synonym table -------------------------------------------------------


def test_an_overlay_group_extends_a_built_in_one_it_shares_a_word_with():
    synonyms = search._synonym_index((("doll", "marionette"),))
    assert "marionette" in synonyms["woman"]  # reached through the shared "doll"


def test_a_multi_word_overlay_entry_is_dropped_rather_than_shredded():
    # Shredding it would teach that "form" means "alpha"; matching is word by
    # word, so a two-word synonym could never be reached anyway.
    synonyms = search._synonym_index((("alpha", "alpha form"),))
    assert "form" not in synonyms


def test_a_one_word_group_widens_nothing():
    assert "solo" not in search._synonym_index((("solo",),))


# --- talking to the model ----------------------------------------------------


def _completion(content):
    return {"choices": [{"message": {"content": content}}]}


def test_the_widening_request_names_every_word_of_the_query():
    messages = search.build_expansion_messages(("two", "dolls"), "RULES")
    assert messages[0] == {"role": "system", "content": "RULES"}
    assert "- two" in messages[1]["content"] and "- dolls" in messages[1]["content"]


def test_a_widening_reply_is_read_back_per_word():
    parsed = search.parse_expansion(
        _completion('{"women": ["dolls", "ladies"]}'), ("women",))
    assert parsed == {"women": ("dolls", "ladies")}


def test_a_widening_reply_wrapped_in_prose_still_parses():
    parsed = search.parse_expansion(
        _completion('Sure!\n```json\n{"women": ["dolls"]}\n```'), ("women",))
    assert parsed == {"women": ("dolls",)}


def test_a_widening_keeps_only_single_words_that_were_asked_about():
    # A phrase can never be reached, the search word itself adds nothing, and a
    # key of the model's own invention would widen a word nobody typed.
    parsed = search.parse_expansion(
        _completion('{"women": ["dolls", "young women", "women"], '
                    '"boys": ["lads"]}'),
        ("women",),
    )
    assert parsed == {"women": ("dolls",)}


def test_a_widening_that_will_not_parse_leaves_the_table_tier_standing(monkeypatch):
    def explode(*_args, **_kwargs):
        raise ValueError("no JSON here")

    monkeypatch.setattr(search.urllib.request, "urlopen", explode)
    assert search.expand_query(
        "two women", base_url="http://localhost:1", model="m", system_prompt="R"
    ) == {}


def test_a_query_with_no_words_asks_the_model_nothing(monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("should not have called out")

    monkeypatch.setattr(search.urllib.request, "urlopen", explode)
    assert search.expand_query(
        "   ", base_url="http://localhost:1", model="m", system_prompt="R") == {}
