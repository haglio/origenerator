"""The policy that turns a spoken request into a prompt-pair edit.

Every prompt here is invented — plain photographic vocabulary standing in for
whatever the library's own prompts say, which never appears in this repo.
"""

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
    apply_request,
    parse_request,
)


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
    assert revision.weight == pytest.approx(1.1)
    assert revision.action == PUSHED


def test_a_second_push_climbs_from_the_weight_already_there():
    revision = apply_request("a woman", "(freckles:1.2)", "no freckles")

    assert revision.negative == "(freckles:1.3)"
    assert revision.weight == pytest.approx(1.3)


def test_for_something_already_wanted_raises_its_weight():
    revision = apply_request("a woman, freckles, soft light", "", "more freckles")

    assert revision.positive == "a woman, (freckles:1.1), soft light"
    assert revision.action == RAISED


def test_for_something_in_neither_prompt_adds_it():
    revision = apply_request("a woman, soft light", "blurry", "more freckles")

    assert revision.positive == "a woman, soft light, freckles"
    assert revision.action == ADDED


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
    # "small silver earrings" is one thing the picture has, so a request about
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
    # What the Requests shelf diffs against, so the record stands alone.
    revision = apply_request("a woman, freckles", "blurry", "no freckles")

    assert revision.old_positive == "a woman, freckles"
    assert revision.old_negative == "blurry"
    assert revision.changed


def test_the_revision_says_what_it_did():
    revision = apply_request("a woman, freckles", "", "no freckles")
    assert "freckles" in revision.describe()


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
        return None

    apply_request("a woman, (silver ear studs:1.2), soft light", "", "no earrings",
                  match=match)

    assert seen[0] == ["a woman", "silver ear studs", "soft light"]


def test_a_completion_names_the_chosen_term():
    from origenerator.prompt_edit import parse_match

    assert parse_match({"choices": [{"message": {"content": '{"choice": 1}'}}]}, 3) == 1


def test_a_completion_refusing_to_choose_reads_as_no_match():
    from origenerator.prompt_edit import parse_match

    assert parse_match({"choices": [{"message": {"content": '{"choice": -1}'}}]}, 3) is None
    assert parse_match({"choices": [{"message": {"content": 'nope'}}]}, 3) is None


def test_the_match_request_offers_the_terms_numbered():
    from origenerator.prompt_edit import build_match_messages

    messages = build_match_messages(["a woman", "silver ear studs"], "earrings", "RULES")

    assert messages[0]["content"] == "RULES"
    assert "0. a woman" in messages[1]["content"]
    assert "1. silver ear studs" in messages[1]["content"]
    assert "earrings" in messages[1]["content"]
