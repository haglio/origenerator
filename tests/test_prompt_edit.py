"""The policy that turns a spoken request into a prompt-pair edit.

Every prompt here is invented — plain photographic vocabulary standing in for
whatever the library's own prompts say, which never appears in this repo.
"""
from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from origenerator.prompt_edit import (
    ADD,
    ADDED,
    ALLOWED,
    DROPPED,
    EXCLUDED,
    PUSHED,
    RAISED,
    REMOVE,
    REWRITTEN,
    apply_request,
    build_match_messages,
    build_rewrite_messages,
    parse_match,
    parse_request,
    rewrite_prompt,
    smart_match,
)
from origenerator.workflows.base import story_of

# --- reading the request ----------------------------------------------------


@pytest.mark.parametrize("request_text, polarity, term", [
    ("no silver earrings", REMOVE, "silver earrings"),
    ("without a hat", REMOVE, "hat"),
    ("remove her sunglasses", REMOVE, "sunglasses"),
    ("get rid of the umbrella", REMOVE, "umbrella"),
    ("more freckles", ADD, "freckles"),
    ("add a red coat", ADD, "red coat"),
    ("give her braided hair", ADD, "braided hair"),
    ("can you please remove the hat, thanks", REMOVE, "hat"),
])
def test_a_spoken_request_reads_as_a_polarity_and_a_term(request_text, polarity, term):
    assert parse_request(request_text) == (polarity, term)


def test_naming_a_thing_is_asking_for_it():
    # No wish word at all: the bare noun phrase is a desire for it.
    assert parse_request("golden hour light") == (ADD, "golden hour light")


def test_the_first_wish_word_decides():
    # "no more X" is a request against X, not for more of it.
    assert parse_request("no more silver earrings") == (REMOVE, "silver earrings")


def test_a_request_naming_nothing_reads_as_nothing():
    assert parse_request("no, please") is None
    assert parse_request("") is None


def test_the_term_keeps_its_own_casing():
    assert parse_request("add a Dutch angle") == (ADD, "Dutch angle")


# --- applying it ------------------------------------------------------------


def test_against_something_in_the_positive_prompt_takes_it_out():
    revision = apply_request("a woman, silver earrings, soft light", "blurry",
                             "no silver earrings")

    assert revision.positive == "a woman, soft light"
    assert revision.negative == "blurry"  # untouched: it was enough to drop it
    assert revision.action == DROPPED


def test_against_something_in_neither_prompt_puts_it_in_the_negative():
    revision = apply_request("a woman, soft light", "blurry", "no silver earrings")

    assert revision.positive == "a woman, soft light"
    assert revision.negative == "blurry, silver earrings"
    assert revision.action == EXCLUDED


def test_against_something_already_excluded_leans_on_it_harder():
    revision = apply_request("a woman", "blurry, silver earrings",
                             "no silver earrings")

    assert revision.negative == "blurry, (silver earrings:1.1)"
    assert revision.action == PUSHED


def test_a_second_push_climbs_from_the_weight_already_there():
    revision = apply_request("a woman", "(freckles:1.2)", "no freckles")

    assert revision.negative == "(freckles:1.3)"


def test_for_something_already_wanted_raises_its_weight():
    revision = apply_request("a woman, freckles, soft light", "", "more freckles")

    assert revision.positive == "a woman, (freckles:1.1), soft light"
    assert revision.action == RAISED


def test_for_something_in_neither_prompt_adds_it():
    revision = apply_request("a woman, soft light", "blurry", "more freckles")

    assert revision.positive == "a woman, soft light, freckles"
    assert revision.action == ADDED


def test_something_in_neither_prompt_is_worked_into_the_whole_prompt_by_the_rewrite():
    # "two women" over a prompt describing one woman: appended, the prompt would
    # ask for both at once, so the local model rewrites what the words contradict.
    asked = []

    def rewrite(positive, negative, words):
        asked.append((positive, negative, words))
        return "two women on a couch", "blurry"

    revision = apply_request("a woman on a couch", "blurry", "two women", rewrite=rewrite)

    assert asked == [("a woman on a couch", "blurry", "two women")]
    assert (revision.positive, revision.negative) == ("two women on a couch", "blurry")
    assert revision.action == REWRITTEN
    assert revision.changed


def test_a_rewrite_that_fails_leaves_the_words_appended(caplog):
    def rewrite(positive, negative, words):
        raise OSError("the model is down")

    with caplog.at_level(logging.WARNING):
        revision = apply_request("a woman, soft light", "blurry", "freckles", rewrite=rewrite)

    assert revision.positive == "a woman, soft light, freckles"
    assert revision.action == ADDED


def test_a_term_inside_a_longer_phrase_is_cut_out_of_it_by_the_rewrite():
    # Dropped whole, "a woman wearing a straw hat" would take the woman with it.
    asked = []

    def rewrite(positive, negative, words):
        asked.append(words)
        return "a woman, freckles", "hat"

    revision = apply_request("a woman wearing a straw hat, freckles", "", "no hat",
                             rewrite=rewrite)

    assert asked == ["no hat"]
    assert (revision.positive, revision.negative) == ("a woman, freckles", "hat")


def test_a_rewrite_that_changes_nothing_leaves_the_rules_own_edit():
    revision = apply_request("a woman wearing a straw hat, freckles", "", "no hat",
                             rewrite=lambda positive, negative, words: (positive, negative))

    assert revision.positive == "freckles"
    assert revision.action == DROPPED


def test_a_term_the_rewrite_weights_at_nothing_is_taken_out():
    revision = apply_request("a woman, natural makeup, beach", "blurry", "no makeup",
                             rewrite=lambda positive, negative, words: (
                                 "a woman, (makeup:0.0), beach", "blurry, (glare:0)"))

    assert (revision.positive, revision.negative) == ("a woman, beach", "blurry")


def test_a_rewrite_that_stands_dots_in_for_a_prompt_leaves_that_prompt_as_it_was():
    revision = apply_request("A dog sits on a porch at sunset.", "", "bigger ears",
                             rewrite=lambda positive, negative, words: (
                                 "A dog with big ears sits on a porch at sunset.", "..."))

    assert (revision.positive, revision.negative) == (
        "A dog with big ears sits on a porch at sunset.", "")


def test_a_rewrite_that_leaves_part_of_the_prompt_out_with_dots_is_no_answer():
    revision = apply_request("A dog sits on a porch at sunset, warm light", "", "bigger ears",
                             rewrite=lambda positive, negative, words: (
                                 "A dog with bigger ears ... warm light", ""))

    assert revision.positive == "A dog sits on a porch at sunset, warm light, bigger ears"


def test_a_phrase_that_is_the_whole_term_is_dropped_by_the_rules_alone():
    def rewrite(positive, negative, words):
        raise AssertionError("not asked")

    revision = apply_request("a woman, freckles, beach", "", "no freckles", rewrite=rewrite)

    assert revision.positive == "a woman, beach"
    assert revision.action == DROPPED


def test_an_edit_the_rules_are_sure_of_never_asks_the_rewrite():
    def rewrite(positive, negative, words):
        raise AssertionError("not asked")

    revision = apply_request("a woman", "blurry, freckles", "more freckles", rewrite=rewrite)

    assert revision.action == ALLOWED


def test_for_something_being_excluded_stops_excluding_it():
    # The mirror of dropping it from the positive: the smallest change that
    # answers the request. Asked again it would then be added.
    revision = apply_request("a woman", "blurry, freckles", "more freckles")

    assert revision.negative == "blurry"
    assert revision.positive == "a woman"
    assert revision.action == ALLOWED


def test_a_bracketed_weight_is_read_and_rewritten_explicitly():
    revision = apply_request("a woman, (freckles)", "", "more freckles")

    assert revision.positive == "a woman, (freckles:1.2)"


def test_the_segment_is_the_unit_a_request_acts_on():
    # "small silver earrings" is one thing the image has, so a request about
    # silver earrings takes the whole phrase rather than the two words inside it.
    revision = apply_request("a woman, small silver earrings, soft light", "",
                             "no silver earrings")

    assert revision.positive == "a woman, soft light"


def test_a_comma_inside_a_weighted_group_does_not_split_a_segment():
    revision = apply_request("(a woman, seated:1.2), freckles", "", "no freckles")

    assert revision.positive == "(a woman, seated:1.2)"


def test_dropping_the_only_term_leaves_an_empty_prompt():
    revision = apply_request("silver earrings", "", "no silver earrings")

    assert revision.positive == ""
    assert revision.changed


def test_a_request_naming_nothing_yields_no_revision():
    assert apply_request("a woman", "", "no, please") is None


def test_a_revision_carries_the_prompts_it_started_from():
    # What the tab marks the prompt's change against, so the record stands alone.
    revision = apply_request("a woman, freckles", "blurry", "no freckles")

    assert revision.old_positive == "a woman, freckles"
    assert revision.old_negative == "blurry"
    assert revision.changed


# --- a video told in scenes: the story is one prompt per scene ---------------


def test_a_wish_for_something_new_reaches_every_scene_of_a_story():
    revision = apply_request(story_of(["a dog running", "a dog asleep"]), "blurry",
                             "more grass")

    assert revision.positive == story_of(["a dog running, grass", "a dog asleep, grass"])


def test_each_scene_answers_a_request_against_something_by_its_own_prompts():
    revision = apply_request(story_of(["a woman, beach", "a woman, sea"]), "blurry",
                             "no beach")

    assert revision.positive == story_of(["a woman", "a woman, sea"])
    assert revision.negative == story_of(["blurry", "blurry, beach"])


def test_a_negative_every_scene_shares_stays_one_while_the_scenes_change_it_alike():
    revision = apply_request(story_of(["a dog running", "a dog asleep"]), "blurry", "no hat")

    assert revision.negative == "blurry, hat"


def test_a_storys_revision_names_each_rule_its_scenes_used_once():
    revision = apply_request(story_of(["a woman, beach", "a woman, sea", "beach, dusk"]),
                             "blurry", "no beach")

    assert revision.action == f"{DROPPED}, {EXCLUDED}"


def test_the_model_rewrites_each_scene_from_that_scenes_own_prompts():
    asked = []

    def rewrite(positive, negative, words):
        asked.append((positive, negative, words))
        return f"two of {positive}", negative

    revision = apply_request(story_of(["a man reading", "a man asleep"]), "blurry",
                             "two men", rewrite=rewrite)

    assert asked == [("a man reading", "blurry", "two men"),
                     ("a man asleep", "blurry", "two men")]
    assert revision.positive == story_of(["two of a man reading", "two of a man asleep"])


# --- catching a term the prompt names in its own words ----------------------


def _matcher(pairs):
    """A stand-in for the model: maps a spoken term to the prompt term it means."""
    def match(terms, term):
        wanted = pairs.get(term)
        return terms.index(wanted) if wanted in terms else None
    return match


def test_a_synonym_in_the_positive_prompt_is_dropped_like_the_words_themselves():
    # The failure this exists for: the request said one thing, the prompt says
    # the same thing in its own words, and excluding the spoken words would have
    # changed nothing because the prompt still asks for it.
    revision = apply_request(
        "a woman, silver ear studs, soft light", "blurry", "no earrings",
        match=_matcher({"earrings": "silver ear studs"}),
    )

    assert revision.positive == "a woman, soft light"
    assert revision.action == DROPPED


def test_the_words_themselves_win_over_the_matcher():
    # A prompt that says what the speaker said needs nothing decided, and a
    # model asked anyway could talk itself out of the obvious answer.
    called = []

    def match(terms, term):
        called.append(term)
        return 0

    revision = apply_request("a woman, a hat, soft light", "", "no hat", match=match)

    assert revision.positive == "a woman, soft light"
    assert called == []


def test_a_matcher_that_finds_nothing_leaves_the_words_to_stand_alone():
    revision = apply_request("a woman, soft light", "blurry", "no earrings",
                             match=lambda terms, term: None)

    assert revision.negative == "blurry, earrings"
    assert revision.action == EXCLUDED


def test_only_what_to_take_out_of_the_prompt_is_looked_for_by_meaning():
    # Asked which of "blurry" meant "two women", a model once answered blurry,
    # and the negative prompt lost it. A wish for something is only ever read
    # in the words themselves.
    revision = apply_request("a woman on a couch", "blurry", "two women",
                             match=lambda terms, term: 0)

    assert revision.negative == "blurry"
    assert revision.action == ADDED


def test_a_matcher_answering_out_of_range_is_ignored():
    # A number the model invented is not a term the speaker meant, and acting on
    # it would edit a part of the prompt nobody mentioned.
    revision = apply_request("a woman, soft light", "", "no earrings",
                             match=lambda terms, term: 99)

    assert revision.positive == "a woman, soft light"
    assert revision.action == EXCLUDED


def test_the_matcher_is_shown_the_prompts_own_terms_unweighted():
    seen = []

    def match(terms, term):
        seen.append(list(terms))

    apply_request("a woman, (silver ear studs:1.2), soft light", "", "no earrings",
                  match=match)

    assert seen[0] == ["a woman", "silver ear studs", "soft light"]


def test_a_completion_names_the_chosen_term():
    assert parse_match({"choices": [{"message": {"content": '{"choice": 1}'}}]}, 3) == 1


def test_a_completion_refusing_to_choose_reads_as_no_match():
    assert parse_match({"choices": [{"message": {"content": '{"choice": -1}'}}]}, 3) is None
    assert parse_match({"choices": [{"message": {"content": 'nope'}}]}, 3) is None


def _model_answering(content):
    response = MagicMock()
    response.read.return_value = json.dumps(
        {"choices": [{"message": {"content": content}}]}).encode()
    response.__enter__ = lambda self: self
    response.__exit__ = MagicMock(return_value=False)
    return patch("urllib.request.urlopen", return_value=response)


def test_a_match_is_logged_by_where_the_term_stands_never_by_its_words(caplog):
    with _model_answering('{"choice": 1}'), \
            caplog.at_level(logging.INFO, logger="origenerator.prompt_edit"):
        chosen = smart_match(["gamma form", "an example lantern", "soft light"], "lamp",
                             base_url="http://model.invalid", model="m",
                             system_prompt="RULES")

    assert chosen == 1
    assert caplog.messages == ["prompt_edit: the request matched index 1 of the prompt's 3 terms"]


def test_a_match_that_fails_says_why_and_never_what_was_asked(caplog):
    with patch("urllib.request.urlopen", side_effect=OSError("model down")), \
            caplog.at_level(logging.INFO, logger="origenerator.prompt_edit"):
        chosen = smart_match(["gamma form", "an example lantern"], "lamp",
                             base_url="http://model.invalid", model="m",
                             system_prompt="RULES")

    assert chosen is None
    assert caplog.messages == [
        "prompt_edit: could not match the request against the prompt's 2 terms (model down)"]


def test_the_match_request_offers_the_terms_numbered():
    messages = build_match_messages(["a woman", "silver ear studs"], "earrings", "RULES")

    assert messages[0]["content"] == "RULES"
    assert "0. a woman" in messages[1]["content"]
    assert "1. silver ear studs" in messages[1]["content"]
    assert "earrings" in messages[1]["content"]


# --- the rewrite: a term in neither prompt worked into the whole pair ---------


def test_build_rewrite_messages_carries_both_prompts_and_the_instruction():
    messages = build_rewrite_messages("a woman, tan", "blurry", "no tan lines", "SYSTEM")
    assert messages[0] == {"role": "system", "content": "SYSTEM"}
    content = messages[1]["content"]
    assert "a woman, tan" in content and "blurry" in content and "no tan lines" in content


def test_the_answer_asked_for_shows_no_dots_a_model_could_copy_back_as_a_prompt():
    content = build_rewrite_messages("a woman, tan", "", "no tan lines", "SYSTEM")[1]["content"]

    assert "..." not in content and "…" not in content


def test_a_rewrite_sends_both_prompts_and_answers_with_both():
    with _model_answering('{"positive": "a woman", "negative": "tan lines"}') as urlopen:
        result = rewrite_prompt(
            "a woman, tan", "", "no tan lines",
            base_url="http://localhost:11434/v1", model="dolphin", system_prompt="SYSTEM",
        )

    (request,), _ = urlopen.call_args
    body = json.loads(request.data)
    assert result == ("a woman", "tan lines")
    assert request.full_url == "http://localhost:11434/v1/chat/completions"
    assert body["model"] == "dolphin"
    assert body["response_format"] == {"type": "json_object"}
    assert "a woman, tan" in body["messages"][1]["content"]


def test_rewrite_prompt_keeps_a_field_the_model_omits():
    with _model_answering('{"positive": "a man"}'):
        positive, negative = rewrite_prompt(
            "a woman", "existing negative", "make her a man",
            base_url="http://x/v1", model="m", system_prompt="S",
        )

    assert positive == "a man" and negative == "existing negative"  # negative preserved
