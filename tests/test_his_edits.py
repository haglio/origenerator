from __future__ import annotations

import pytest

from origenerator import his_edits
from origenerator.his_edits import Addition, edits_in, the_way_he_adds

_BEACH = "a man on a beach, white sand, blue sea"
_STREET = "a man on a street, tall buildings, wet pavement"
_ON_THE_BEACH_IN_A_HAT = ("a man on a beach, a wide straw hat, frayed hat brim, white sand, blue sea",
                          "blurry, torn hat, paper hat")
_ON_THE_STREET_IN_A_HAT = ("a man on a street, a felt hat, tall buildings, wet pavement",
                           "blurry, crushed hat")


@pytest.fixture(autouse=True)
def _a_few_prompts_are_enough(monkeypatch):
    monkeypatch.setattr(his_edits, "_FEWEST_PROMPTS_WITH_IT", 5)


def _names_a_hat(thing: str) -> bool:
    return "hat" in thing.split()


def _his_prompts() -> list[tuple[str, str]]:
    return [(_BEACH, "blurry"), _ON_THE_BEACH_IN_A_HAT, (_STREET, "blurry"), _ON_THE_STREET_IN_A_HAT,
            (f"{_BEACH}, film grain", "blurry")]


def test_an_edit_is_a_prompt_that_holds_an_earlier_one_and_a_few_things_more():
    edits = edits_in(_his_prompts())

    assert [sorted(edit.added.values()) for edit in edits] == [
        ["a wide straw hat", "frayed hat brim"], ["a felt hat"], ["film grain"]]


def test_a_prompt_that_only_reorders_an_earlier_one_is_no_edit():
    assert edits_in([(_BEACH, ""), ("blue sea, white sand, a man on a beach", "")]) == []


def test_a_prompt_with_many_things_more_than_any_earlier_one_is_no_edit():
    much_more = f"{_BEACH}, one, two, three, four, five"

    assert edits_in([(_BEACH, ""), (much_more, "")]) == []


def test_a_thing_goes_in_with_every_part_naming_it_in_his_prompt_most_like_this_one():
    on_the_beach = the_way_he_adds(_names_a_hat, _his_prompts(), (f"{_BEACH}, soft light", "blurry"))
    on_the_street = the_way_he_adds(_names_a_hat, _his_prompts(), (f"{_STREET}, soft light", "blurry"))

    assert on_the_beach == Addition(("a wide straw hat", "frayed hat brim"), ("torn hat", "paper hat"),
                                    beside="a man on a beach")
    assert on_the_street == Addition(("a felt hat",), ("crushed hat",), beside="a man on a street")


def test_of_his_prompts_most_like_this_one_the_one_that_words_it_as_the_others_do_is_followed():
    as_usual = "a man on a beach, a wide straw hat, white sand, blue sea"
    prompts = [(as_usual, ""), ("a man on a beach, a hat taller than a house, white sand, blue sea", ""),
               (as_usual, "")]

    assert the_way_he_adds(_names_a_hat, prompts, (_BEACH, "")).positive == ("a wide straw hat",)


def test_only_his_latest_prompts_with_a_thing_say_how_it_goes_in(monkeypatch):
    monkeypatch.setattr(his_edits, "_HIS_LATEST_PROMPTS_WITH_IT", 1)

    added = the_way_he_adds(_names_a_hat, _his_prompts(), (_BEACH, "blurry"))

    assert added.positive == ("a felt hat",)


def test_what_the_prompt_already_has_is_not_added_again():
    already = (f"{_BEACH}, frayed hat brim", "blurry, torn hat")

    assert the_way_he_adds(_names_a_hat, _his_prompts(), already) == Addition(
        ("a wide straw hat",), ("paper hat",), beside="a man on a beach")


def test_a_thing_none_of_his_prompts_has_is_not_his_to_add():
    assert the_way_he_adds(lambda thing: "scarf" in thing, _his_prompts(), (_BEACH, "")) is None


def test_reading_his_edits_looks_no_prompt_up_among_all_the_others(monkeypatch):
    read = []
    things_of = his_edits.things_of
    monkeypatch.setattr(his_edits, "things_of", lambda text: read.append(text) or things_of(text))
    prompts = [(f"{_BEACH}, thing {number}", "blurry") for number in range(40)]

    edits_in(prompts)

    assert len(read) == len(prompts)


def test_reading_what_is_tied_to_a_thing_reads_each_prompt_a_few_times_at_most(monkeypatch):
    read = []
    things_of = his_edits.things_of
    monkeypatch.setattr(his_edits, "things_of", lambda text: read.append(text) or things_of(text))
    prompts = _prompts_where_a_beard_is_always_a_mans()

    the_way_he_adds(_names_a_beard, prompts, ("a woman, a porch", "blurry"))

    assert len(read) <= 4 * len(prompts) + 3


def _names_a_beard(thing: str) -> bool:
    return "beard" in thing.split()


def _prompts_where_a_beard_is_always_a_mans() -> list[tuple[str, str]]:
    scenes = ("a harbor, fog, gulls", "a field, dusk, crows", "a deck, rain, ropes",
              "a kitchen, steam, copper pans", "a library, dust, tall shelves")
    men = ("a tall man in a wool coat", "an old man", "a tall man in a wool coat", "a man asleep",
           "a tall man in a wool coat")
    return [pair for scene, man in zip(scenes, men, strict=True)
            for pair in ((f"a woman, {scene}, sharp focus", "blurry"),
                         (f"{man}, a gray beard, {scene}, sharp focus", "blurry"))]


def test_a_thing_brings_what_his_prompts_tie_to_it_when_the_prompt_lacks_it():
    added = the_way_he_adds(_names_a_beard, _prompts_where_a_beard_is_always_a_mans(),
                            ("a woman, a porch, snow, sharp focus", "blurry"))

    assert added.positive == ("a tall man in a wool coat", "a gray beard")


def test_what_the_prompt_already_says_in_other_words_is_not_brought_again():
    added = the_way_he_adds(_names_a_beard, _prompts_where_a_beard_is_always_a_mans(),
                            ("a short man, a porch, snow", "blurry"))

    assert added.positive == ("a gray beard",)


def test_what_is_as_common_without_the_thing_is_not_brought_with_it():
    added = the_way_he_adds(_names_a_beard, _prompts_where_a_beard_is_always_a_mans(),
                            ("a short man, a porch, snow", "blurry"))

    assert "sharp focus" not in added.positive


def test_a_thing_too_few_of_his_prompts_have_brings_nothing_with_it():
    added = the_way_he_adds(_names_a_beard, _prompts_where_a_beard_is_always_a_mans()[:6],
                            ("a woman, a porch, snow", "blurry"))

    assert added.positive == ("a gray beard",)
