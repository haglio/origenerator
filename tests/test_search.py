from __future__ import annotations

import json

import pytest

from origenerator import gallery, local_llm, search
from origenerator.generation_state import GenerationSource


def _row(prompt_id, positive, **given):
    negative = given.get("negative", "")
    seed = given.get("seed", 1)
    stored = {"positive_prompt": positive, "negative_prompt": negative, "seed": seed}
    stored.update(given.get("params") or {})
    return {
        "prompt_id": prompt_id,
        "workflow_name": given.get("workflow", "sdxl_t2i"),
        "positive_prompt": positive,
        "negative_prompt": negative,
        "seed": seed,
        "status": "completed",
        "output_files": json.dumps([f"{prompt_id}.png"]) if given.get("output", True) else None,
        "params_json": json.dumps(stored),
    }


def _folders_holding(names_by_row):
    return [gallery.NamedFolder(f"{prompt_id} {name}", name, (prompt_id,))
            for prompt_id, names in (names_by_row or {}).items() for name in names]


def _index(rows, folder_names=None):
    index = search.GallerySearch()
    index.update(rows, folders=_folders_holding(folder_names))
    return index


def _hits(index, query, **kwargs):
    return [result.row["prompt_id"] for result in index.search(query, **kwargs).results]



def test_stop_words_are_dropped_from_a_query():
    assert search.query_words("a pair of dolls on the beach") == (
        "pair", "dolls", "beach")


def test_a_query_of_nothing_but_stop_words_keeps_them():
    assert search.query_words("the of") == ("the", "of")


def test_a_repeated_word_is_searched_once():
    assert search.query_words("beach beach sunset") == ("beach", "sunset")


@pytest.mark.parametrize(("plural", "singular"), [
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


def test_a_prompt_several_generations_share_is_not_taken_apart_per_generation(monkeypatch):
    taken_apart = []
    words = search._words
    monkeypatch.setattr(search, "_words",
                        lambda text: taken_apart.append(text) or words(text))
    prompt = "a vermilion kite on a quay"
    _index([_row(f"g{n}", prompt) for n in range(3)])
    assert taken_apart.count(prompt) <= 1, (
        "every seed of a settings folder repeats its prompt, and taking it apart once per row "
        "was most of what a large library's first draw took")


class _Asked(dict):
    def __init__(self, table):
        super().__init__(table)
        self.about = {}

    def get(self, word, default=None):
        self.about[word] = self.about.get(word, 0) + 1
        return super().get(word, default)


def test_a_word_two_prompts_share_is_not_stemmed_twice(monkeypatch):
    stemmed = _Asked(search._IRREGULAR_PLURALS)
    monkeypatch.setattr(search, "_IRREGULAR_PLURALS", stemmed)
    _index([_row("g1", "a vermilion kite"), _row("g2", "a vermilion hat")])
    assert stemmed.about.get("vermilion", 0) <= 1



def test_a_synonym_satisfies_a_term_the_prompt_never_used():
    rows = [_row("g1", "two dolls on a couch"),
            _row("g2", "two tall ladies at the beach"),
            _row("g3", "a single lady in the rain"),
            _row("g4", "an empty street at dawn")]
    assert set(_hits(_index(rows), "two women")) == {"g1", "g2"}


def test_every_word_of_the_query_has_to_be_satisfied():
    rows = [_row("g1", "a red lamp on a wooden table"),
            _row("g2", "a red lamp")]
    assert _hits(_index(rows), "red lamp table") == ["g1"]


def test_a_word_nothing_reaches_is_named_back():
    rows = [_row("g1", "a red lamp")]
    outcome = _index(rows).search("red aardvark")
    assert outcome.results == ()
    assert outcome.unmatched == ("aardvark",)


def test_a_query_whose_words_are_all_present_but_never_together_names_nothing():
    rows = [_row("g1", "a red lamp"), _row("g2", "a wooden table")]
    outcome = _index(rows).search("lamp table")
    assert outcome.results == ()
    assert outcome.unmatched == ()


def test_the_negative_prompt_is_not_searched():
    rows = [_row("g1", "a quiet street", negative="rain, blur"),
            _row("g2", "rain over a quiet street")]
    assert _hits(_index(rows), "rain") == ["g2"]


def test_a_decimal_is_one_word_not_two():
    rows = [_row("g1", "a (red:1.2) lamp"), _row("g2", "two red lamps")]
    assert _hits(_index(rows), "two lamps") == ["g2"]


def test_bare_numbers_in_a_model_name_are_not_searchable():
    rows = [_row("g1", "a quiet street", workflow="wan22_i2v", params={
        "unet_high": "example_2.2_high.safetensors",
        "unet_low": "example_2.2_low.safetensors",
    })]
    index = _index(rows)
    assert _hits(index, "two streets") == []
    assert _hits(index, "example") == ["g1"]


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


def _made_as(prompt_id, filename, **file):
    return dict(_row(prompt_id, "a quiet street"),
                output_files=json.dumps([{"filename": filename, **file}]))


@pytest.mark.parametrize("typed", [
    "wan_loop_00042_", "wan_loop_00042_.mp4", "WAN_LOOP_00042_.MP4",
    "wan_loop_00042_ (2).mp4", "wan_loop_00042__topaz.mp4", "  wan_loop_00042_  ",
    "wan_loop_00042_-audio.mp4"])
def test_a_file_name_finds_the_item_it_was_made_as_whatever_the_library_did_to_it(typed):
    rows = [_made_as("made", "wan_loop_00042_.mp4"), _made_as("other", "wan_loop_00043_.mp4")]
    assert _hits(_index(rows), typed) == ["made"]


def test_a_file_name_finds_an_item_brought_in_from_the_library():
    rows = [_made_as("brought in", "", library_path="C:/library/videos/an example clip.mp4"),
            _made_as("other", "wan_loop_00043_.mp4")]
    assert _hits(_index(rows), "an example clip") == ["brought in"]


def test_a_file_name_is_never_widened():
    rows = [_made_as("made", "wan_loop_00042_.mp4"), _made_as("other", "wan_loop_00043_.mp4")]
    index = _index(rows)
    assert not index.widens("wan_loop_00042_.mp4")
    assert _hits(index, "wan_loop_00042_.mp4", expansions={"wan": ["street"]}) == ["made"]


def test_the_code_leading_a_name_finds_every_item_of_its_folder():
    rows = [_row("g1", "a quiet street"), _row("g2", "a quiet street"),
            _row("g3", "a quiet street")]
    names = {"g1": "3FA9C0D2 004", "g2": "3FA9C0D2 005", "g3": "77B1E0AA 004"}
    index = search.GallerySearch()
    index.update(rows, item_name=names.get)

    assert _hits(index, "3fa9c0d2") == ["g1", "g2"]


def test_a_whole_name_lands_on_its_item_alone():
    rows = [_row("image", "a quiet street"), _row("made from it", "a quiet street"),
            _row("numbered alike", "a quiet street")]
    names = {"image": "3FA9C0D2 004", "made from it": "77B1E0AA 000",
             "numbered alike": "77B1E0AA 004"}
    folders = {"made from it": ["3FA9C0D2 004"], "numbered alike": ["3FA9C0D2 001"]}
    index = search.GallerySearch()
    index.update(rows, _folders_holding(folders), item_name=names.get)

    assert _hits(index, "3FA9C0D2 004") == ["image"]


def test_the_start_of_a_name_finds_the_items_whose_names_start_that_way():
    rows = [_row("g1", "a quiet street"), _row("g2", "a quiet street"),
            _row("g3", "a quiet street")]
    names = {"g1": "79BB46F1 000", "g2": "79BB0C2A 004", "g3": "3FA9C0D2 004"}
    index = search.GallerySearch()
    index.update(rows, item_name=names.get)

    assert _hits(index, "79BB") == ["g1", "g2"]
    assert _hits(index, "79bb46f1 0") == ["g1"]


def test_a_word_under_four_letters_is_never_taken_for_the_start_of_a_name():
    rows = [_row("g1", "a bed by a window"), _row("g2", "a quiet street")]
    names = {"g1": "11111111 000", "g2": "BED00000 000"}
    index = search.GallerySearch()
    index.update(rows, item_name=names.get)

    assert _hits(index, "bed") == ["g1"]


def test_a_word_that_starts_a_name_still_finds_the_prompts_that_use_it():
    rows = [_row("g1", "a face at a window"), _row("g2", "a quiet street")]
    names = {"g1": "11111111 000", "g2": "FACE0000 000"}
    index = search.GallerySearch()
    index.update(rows, item_name=names.get)

    assert _hits(index, "face") == ["g1", "g2"]


def test_a_word_that_starts_a_name_is_never_widened():
    rows = [_row("g1", "a quiet street"), _row("g2", "a quiet street")]
    names = {"g1": "79BB46F1 000", "g2": "3FA9C0D2 004"}
    index = search.GallerySearch()
    index.update(rows, item_name=names.get)

    assert _hits(index, "79bb", expansions={"79bb": ["street"]}) == ["g1"]
    assert not index.widens("79bb")


def test_quoted_words_find_only_prompts_that_have_them_side_by_side_in_that_order():
    rows = [_row("g1", "two lamps on a bench"), _row("g2", "two cats near some lamps"),
            _row("g3", "lamps, two of them")]

    assert _hits(_index(rows), '"two lamps"') == ["g1"]


def test_quoted_words_bring_in_no_related_words():
    index = _index([_row("g1", "a pair of lamps on a bench")])

    assert _hits(index, "two lamps") == ["g1"]
    assert _hits(index, '"two lamps"') == []


def test_quoted_words_never_reach_across_a_comma():
    assert _hits(_index([_row("g1", "a red, car parked outside")]), '"red car"') == []


def test_a_quote_still_being_typed_runs_to_the_end_of_the_query():
    rows = [_row("g1", "two lamps on a bench"), _row("g2", "two cats near some lamps")]

    assert _hits(_index(rows), '"two lamps') == ["g1"]


def test_words_outside_the_quotes_keep_their_related_words():
    rows = [_row("g1", "two lamps on a couch"), _row("g2", "two lamps on a bench")]

    assert _hits(_index(rows), '"two lamps" sofa') == ["g1"]


def test_quoted_words_find_a_folder_named_with_them():
    index = _index([_row("a", "a cat"), _row("b", "a cat")],
                   {"a": ["Keepers from the beach trip"], "b": ["Trip to the beach"]})

    assert _hits(index, '"beach trip"') == ["a"]


def test_a_search_can_be_held_to_a_set_of_generations():
    rows = [_row("g1", "a red lamp"), _row("g2", "a red lamp")]
    assert _hits(_index(rows), "lamp", within={"g2"}) == ["g2"]


def test_a_word_outside_the_scope_still_counts_as_unmatched():
    rows = [_row("g1", "a red lamp"), _row("g2", "a wooden table")]
    outcome = _index(rows).search("lamp", within={"g2"})
    assert outcome.results == ()
    assert outcome.unmatched == ("lamp",)


def test_an_empty_query_matches_nothing_rather_than_everything():
    rows = [_row("g1", "a quiet street")]
    assert _index(rows).search("   ") == search.SearchOutcome((), ())



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


def test_a_volunteered_word_ranks_below_a_synonym_from_the_table():
    rows = [_row("g1", "a lone kitten"), _row("g2", "a lone couch")]
    index = _index(rows)
    volunteered, = index.search("cat", expansions={"cat": ["kitten"]}).results
    from_the_table, = index.search("sofa").results
    assert from_the_table.score > volunteered.score


def test_what_made_an_item_ranks_below_what_it_shows_and_a_folders_name_ranks_with_that():
    shown = _row("g1", "a harbor at dawn")
    made_with = _row("g2", "a quiet street", params={"checkpoint": "harbor_xl.safetensors"})
    filed = _row("g3", "a quiet street")
    by_id = {result.row["prompt_id"]: result.score for result in _index(
        [shown, made_with, filed], {"g3": ("Harbor",)}).search("harbor").results}
    assert by_id["g1"] > by_id["g2"], \
        "a model's or a LoRA's name answers what made the item, a different question"
    assert by_id["g3"] == by_id["g1"], (
        "a folder's name is the most deliberate word there is: chosen only to find it again")


def test_a_row_handed_over_twice_is_found_once():
    row = _row("g1", "a red lamp")
    assert _hits(_index([row, dict(row)]), "lamp") == ["g1"], \
        "the gallery's rows and the Trash's are handed over together, and may overlap"


def test_part_of_a_seed_finds_nothing():
    rows = [_row("g1", "a quiet street", seed=778899)]
    assert _hits(_index(rows), "7788") == []


def test_every_row_of_a_settings_folder_falls_under_one_model_and_lora_heading():
    one, other = (dict(_row(f"g{seed}", "a quiet street", seed=seed,
                            params={"checkpoint": "sample_xl.safetensors"}),
                       output_files=json.dumps([{"filename": f"g{seed}.png"}]))
                  for seed in (1, 2))
    assert gallery.settings_folder_key(one) == gallery.settings_folder_key(other)
    assert search.model_lora_heading(one) == search.model_lora_heading(other), \
        "a folder's one tile in the results is filed under a heading by one of its rows alone"


def test_an_expansion_for_a_word_not_in_the_query_is_ignored():
    rows = [_row("g1", "a lone kitten")]
    assert _hits(_index(rows), "puppy", expansions={"cat": ["kitten"]}) == []



def test_only_generations_that_produced_something_are_searchable():
    rows = [_row("g1", "a red lamp"), _row("g2", "a red lamp", output=False)]
    assert _hits(_index(rows), "lamp") == ["g1"]


def test_a_hidden_starting_frame_is_never_found():
    rows = [_row("g1", "a red lamp"),
            {**_row("f1", "a red lamp"), "source": GenerationSource.STARTING_FRAME}]
    assert _hits(_index(rows), "lamp") == ["g1"]


def test_results_come_back_in_the_order_the_rows_were_given():
    rows = [_row("g3", "a quiet street", params={"checkpoint": "lamp_xl.safetensors"}),
            _row("g1", "a red lamp"), _row("g2", "a red lamp")]
    assert _hits(_index(rows), "lamp") == ["g3", "g1", "g2"], (
        "the view hands the rows over newest first and reads the results straight out; "
        "in score order they would reshuffle under the user each time the model's words landed")


def test_a_re_index_keeps_the_words_and_takes_the_fresh_row():
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



def _lora_row(prompt_id, lora, prompt="a quiet street"):
    return _row(prompt_id, prompt, workflow="wan22_i2v", params={
        "unet_high": "example_high.safetensors",
        "unet_low": "example_low.safetensors",
        "lora_high": f"{lora}_high.safetensors",
        "lora_low": f"{lora}_low.safetensors",
    })



def test_a_folder_name_finds_what_is_in_it():
    rows = [_row("a", "a cat on a windowsill"), _row("b", "a dog in a field")]
    index = _index(rows, {"a": ["Keepers from the beach trip"]})

    assert _hits(index, "beach trip") == ["a"]
    assert _hits(index, "beach cat") == ["a"]


def test_a_folder_name_reaches_related_words_like_a_prompt_does():
    index = _index([_row("a", "a portrait")], {"a": ["two women"]})

    assert _hits(index, "pair") == ["a"]


def test_renaming_a_folder_is_searchable_at_once():
    rows = [_row("a", "a cat")]
    index = search.GallerySearch()
    index.update(rows, _folders_holding({"a": ["Rejects"]}))
    assert _hits(index, "rejects") == ["a"]

    index.update(rows, _folders_holding({"a": ["Keepers"]}))

    assert _hits(index, "keepers") == ["a"]
    assert _hits(index, "rejects") == []


@pytest.mark.parametrize("query", ["I2V WAN 2.2", "wan_high", "styleA_low"])
def test_a_workflow_model_or_lora_folder_is_found_by_the_name_the_toc_shows(query):
    rows = [_row("v1", "a dance", workflow="wan22_i2v", params={
        "unet_high": "wan_high.safetensors", "unet_low": "wan_low.safetensors",
        "lora_high": "styleA_high.safetensors", "lora_low": "styleA_low.safetensors",
    }), _row("i1", "a dance")]
    for row, made in zip(rows, ("v1.mp4", "i1.png"), strict=True):
        row["output_files"] = json.dumps([{"filename": made}])
    index = search.GallerySearch()
    index.update(rows, folders=gallery.named_folders(gallery.build_gallery_tree(rows), {}))

    assert _hits(index, query) == ["v1"]


def _folders_index(rows, *folders):
    index = search.GallerySearch()
    index.update(rows, folders=[gallery.NamedFolder(*folder) for folder in folders])
    return index


def test_a_folder_whose_own_name_answers_every_word_is_matched_itself():
    rows = [_row("v1", "a dance"), _row("v2", "a walk"), _row("i1", "a dance")]
    index = _folders_index(rows, ("wan", "I2V WAN 2.2", ("v1", "v2")),
                           ("sdxl", "T2I SDXL", ("i1",)))

    assert index.search("I2V WAN 2.2").folders == ("wan",)
    assert _hits(index, "I2V WAN 2.2") == ["v1", "v2"]


def test_a_folder_whose_name_answers_only_some_words_is_not_matched_itself():
    rows = [_row("v1", "a dance"), _row("v2", "a walk")]
    index = _folders_index(rows, ("wan", "I2V WAN 2.2", ("v1", "v2")))

    assert index.search("wan dance").folders == ()
    assert _hits(index, "wan dance") == ["v1"]


def test_a_folder_outside_the_searched_folder_is_not_matched():
    rows = [_row("v1", "a dance"), _row("i1", "a dance")]
    index = _folders_index(rows, ("wan", "I2V WAN 2.2", ("v1",)))

    assert index.search("I2V WAN 2.2", within={"i1"}).folders == ()


def test_matched_folders_come_in_the_order_the_toc_lists_them():
    rows = [_row("v1", "a dance")]
    index = _folders_index(rows, ("wan", "I2V WAN 2.2", ("v1",)),
                           ("high", "WAN high", ("v1",)))

    assert index.search("wan").folders == ("wan", "high")


def test_an_unnamed_folders_row_is_reached_by_no_name():
    index = _index([_row("a", "a cat")])

    assert _hits(index, "keepers") == []


def test_results_group_under_one_heading_per_model_and_lora():
    rows = [_lora_row("g1", "driftstyle"), _lora_row("g2", "driftstyle"),
            _lora_row("g3", "emberstyle")]
    sections = search.group_by_model_lora(_index(rows).search("street").results)
    assert [[r.row["prompt_id"] for r in found] for _, found in sections] == [
        ["g1", "g2"], ["g3"]]
    assert "driftstyle" in sections[0][0]
    assert "emberstyle" in sections[1][0]


def test_the_biggest_combination_leads():
    rows = [_lora_row("g1", "emberstyle"), _lora_row("g2", "driftstyle"),
            _lora_row("g3", "driftstyle"), _lora_row("g4", "driftstyle")]
    sections = search.group_by_model_lora(_index(rows).search("street").results)
    assert [len(found) for _, found in sections] == [3, 1]


def test_a_heading_names_both_the_model_and_the_lora():
    heading = search.model_lora_heading(_lora_row("g1", "driftstyle"))
    assert "example_high" in heading
    assert "driftstyle_high" in heading



def test_an_overlay_group_extends_a_built_in_one_it_shares_a_word_with():
    synonyms = search._synonym_index((("doll", "marionette"),))
    assert "marionette" in synonyms["woman"]


def test_a_multi_word_overlay_entry_is_dropped_rather_than_shredded():
    synonyms = search._synonym_index((("alpha", "alpha form"),))
    assert "form" not in synonyms


def test_a_one_word_group_widens_nothing():
    assert "solo" not in search._synonym_index((("solo",),))



def _completion(content):
    return {"message": {"content": content}}


def test_the_widening_request_names_every_word_of_the_query():
    messages = search.build_expansion_messages(("two", "dolls"), "RULES")
    assert messages[0] == {"role": "system", "content": "RULES"}
    assert "- two" in messages[1]["content"]
    assert "- dolls" in messages[1]["content"]


def test_a_widening_reply_is_read_back_per_word():
    parsed = search.parse_expansion(
        _completion('{"women": ["dolls", "ladies"]}'), ("women",))
    assert parsed == {"women": ("dolls", "ladies")}


def test_a_widening_reply_wrapped_in_prose_still_parses():
    parsed = search.parse_expansion(
        _completion('Sure!\n```json\n{"women": ["dolls"]}\n```'), ("women",))
    assert parsed == {"women": ("dolls",)}


def test_a_widening_keeps_only_single_words_that_were_asked_about():
    parsed = search.parse_expansion(
        _completion('{"women": ["dolls", "young women", "women"], '
                    '"boys": ["lads"]}'),
        ("women",),
    )
    assert parsed == {"women": ("dolls",)}


def test_a_widening_that_will_not_parse_leaves_the_table_tier_standing(monkeypatch):
    def explode(*_args, **_kwargs):
        raise ValueError("no JSON here")

    monkeypatch.setattr(local_llm.urllib.request, "urlopen", explode)
    assert search.expand_query(
        "two women", base_url="http://localhost:1", model="m", system_prompt="R"
    ) == {}


def _calls_to_the_model(monkeypatch):
    calls = []
    monkeypatch.setattr(local_llm.urllib.request, "urlopen",
                        lambda *args, **kwargs: calls.append(args))
    return calls


def test_a_query_with_no_words_asks_the_model_nothing(monkeypatch):
    calls = _calls_to_the_model(monkeypatch)

    assert search.expand_query(
        "   ", base_url="http://localhost:1", model="m", system_prompt="R") == {}
    assert calls == []


def test_an_items_name_is_never_sent_to_the_model_to_widen(monkeypatch):
    calls = _calls_to_the_model(monkeypatch)

    search.expand_query(
        "3FA9C0D2 004", base_url="http://localhost:1", model="m", system_prompt="R")

    assert calls == []


def test_quoted_words_are_never_sent_to_the_model_to_widen(monkeypatch):
    calls = _calls_to_the_model(monkeypatch)

    search.expand_query(
        '"two lamps"', base_url="http://localhost:1", model="m", system_prompt="R")

    assert calls == []


def test_both_is_not_a_count_of_two():
    rows = [_row("g1", "she holds a cup in both hands"), _row("g2", "a pair of cups")]
    assert _hits(_index(rows), "two cups") == ["g2"]


def test_a_prompt_held_only_in_the_params_is_searchable():
    row = _row("g1", "", params={"positive_prompt": "a red lamp"})
    row["positive_prompt"] = None
    assert _hits(_index([row]), "lamp") == ["g1"]


def test_combinations_of_equal_size_are_ordered_alphabetically():
    rows = [_lora_row("g1", "emberstyle"), _lora_row("g2", "driftstyle")]
    sections = search.group_by_model_lora(_index(rows).search("street").results)
    headings = [heading for heading, _ in sections]
    assert headings == sorted(headings)
