from __future__ import annotations

from origenerator import his_edits
from origenerator.his_edits import Addition, edits_in, the_way_he_adds

_BEACH = "a man on a beach, white sand, blue sea"
_STREET = "a man on a street, tall buildings, wet pavement"
_FOREST = "a man in a forest, tall pines, morning fog"


def _names_a_hat(thing: str) -> bool:
    return "hat" in thing.split()


def _his_prompts() -> list[tuple[str, str]]:
    return [
        (_BEACH, "blurry"),
        ("a man on a beach, a wide straw hat, frayed brim, white sand, blue sea", "blurry, bare head"),
        (_STREET, "blurry"),
        ("a man on a street, a felt hat, tall buildings, wet pavement", "blurry, bare head, cap"),
        (f"{_BEACH}, film grain", "blurry"),
        (f"{_STREET}, film grain", "blurry"),
    ]


def test_an_edit_is_a_prompt_that_holds_an_earlier_one_and_a_few_things_more():
    edits = edits_in(_his_prompts())

    assert [(sorted(edit.added.values()), sorted(edit.kept_out.values())) for edit in edits] == [
        (["a wide straw hat", "frayed brim"], ["bare head"]),
        (["a felt hat"], ["bare head", "cap"]),
        (["film grain"], []),
        (["film grain"], []),
    ]


def test_a_prompt_that_only_reorders_an_earlier_one_is_no_edit():
    assert edits_in([(_BEACH, ""), ("blue sea, white sand, a man on a beach", "")]) == []


def test_a_prompt_with_many_things_more_than_any_earlier_one_is_no_edit():
    much_more = f"{_BEACH}, one, two, three, four, five"

    assert edits_in([(_BEACH, ""), (much_more, "")]) == []


def test_a_thing_goes_in_the_way_his_nearest_edits_added_it_with_what_they_kept_out():
    on_the_beach = the_way_he_adds(_names_a_hat, _his_prompts(), (f"{_BEACH}, soft light", "blurry"))
    on_the_street = the_way_he_adds(_names_a_hat, _his_prompts(), (f"{_STREET}, soft light", "blurry"))

    assert on_the_beach == Addition(("a wide straw hat", "frayed brim"), ("bare head",),
                                    beside="a man on a beach")
    assert on_the_street == Addition(("a felt hat",), ("bare head", "cap"), beside="a man on a street")


def test_what_only_some_of_his_nearest_edits_brought_stays_out():
    prompts = [*_his_prompts(),
               ("a man on a beach, a wide straw hat, white sand, blue sea, film grain", "blurry"),
               ("a man on a beach, a wide straw hat, white sand, blue sea, soft light", "blurry")]

    assert the_way_he_adds(_names_a_hat, prompts, (_BEACH, "blurry")) == Addition(
        ("a wide straw hat",), (), beside="a man on a beach")


def test_what_the_prompt_already_has_is_not_added_again():
    already = (f"{_BEACH}, frayed brim", "blurry, bare head")

    assert the_way_he_adds(_names_a_hat, _his_prompts(), already) == Addition(
        ("a wide straw hat",), (), beside="a man on a beach")


def test_a_thing_he_never_added_by_itself_goes_in_as_his_nearest_prompt_with_it_writes_it():
    prompts = [("a man in a forest, a wool hat, tall pines", "blurry, bare head"),
               ("a dog on a beach, a paper hat, white sand", "blurry")]

    assert the_way_he_adds(_names_a_hat, prompts, (_FOREST, "blurry")) == Addition(("a wool hat",), ())


def test_a_thing_none_of_his_prompts_has_is_not_his_to_add():
    assert the_way_he_adds(lambda thing: "scarf" in thing, _his_prompts(), (_BEACH, "")) is None


def test_reading_his_edits_looks_no_prompt_up_among_all_the_others(monkeypatch):
    read = []
    things_of = his_edits.things_of
    monkeypatch.setattr(his_edits, "things_of", lambda text: read.append(text) or things_of(text))
    prompts = [(f"{_BEACH}, thing {number}", "blurry") for number in range(40)]

    edits_in(prompts)

    assert len(read) == 2 * len(prompts)
