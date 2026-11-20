from __future__ import annotations

from origenerator.usual_company import UsualCompany, usual_company

_WITH_A_HAT = [
    ("a fisherman, a wide straw hat, frayed brim, harbor", "blurry, bare head, paper hat"),
    ("a farmer, a wide straw hat, frayed brim, a field", "blurry, Bare Head, (paper hat:1.2)"),
    ("a child, a wide straw hat, a beach", "blurry, bare head"),
    ("a sailor, a wide straw hat, frayed brim, a deck", "blurry, bare head"),
]
_WITHOUT_ONE = [
    ("a cat on a sofa", "blurry"),
    ("a dog in a park", "blurry, paper hat"),
    ("a bird, a field", "blurry, paper hat"),
]


def _has_a_hat(positive: str) -> bool:
    return "hat" in positive


def test_the_parts_most_prompts_with_the_thing_have_and_other_prompts_seldom_do_are_its_company():
    assert usual_company(_WITH_A_HAT + _WITHOUT_ONE, _has_a_hat) == UsualCompany(
        positive=("a wide straw hat", "frayed brim"), negative=("bare head",))


def test_a_part_fewer_than_three_prompts_with_the_thing_have_is_no_company_of_it():
    company = usual_company(_WITH_A_HAT + _WITHOUT_ONE, _has_a_hat)

    assert "paper hat" not in company.negative


def test_a_part_a_third_of_the_prompts_with_the_thing_have_is_company_and_a_rarer_one_is_not():
    with_a_hat = ([("a hat, frayed brim", "")] * 3 + [("a hat, a red ribbon", "")] * 3
                  + [("a hat", "")] * 4)

    assert usual_company(with_a_hat + [("a hat, a feather", "")] * 2, _has_a_hat).positive == (
        "a hat",)
    assert usual_company(with_a_hat, _has_a_hat).positive == ("a hat",)
    assert usual_company(with_a_hat[:9], _has_a_hat).positive == (
        "a hat", "frayed brim", "a red ribbon")


def test_prompts_with_no_negative_prompt_say_nothing_about_what_is_usually_kept_out():
    silent = [("a tall hat", "")] * 20

    assert usual_company(_WITH_A_HAT + silent, _has_a_hat).negative == ("blurry", "bare head")


def test_only_his_newest_prompts_with_the_thing_say_what_its_company_is():
    older = [("a felt hat, a feather", "bare head")] * 10
    newer = [("a straw hat, frayed brim", "paper hat")] * 150

    assert usual_company(older + newer, _has_a_hat) == UsualCompany(
        positive=("a straw hat", "frayed brim"), negative=("paper hat",))


def test_a_part_as_common_without_the_thing_is_no_company_of_it():
    company = usual_company(_WITH_A_HAT + _WITHOUT_ONE, _has_a_hat)

    assert "blurry" not in company.negative


def test_too_few_prompts_with_the_thing_show_no_company():
    assert usual_company(_WITH_A_HAT[:2] + _WITHOUT_ONE, _has_a_hat) == UsualCompany()


def test_with_no_prompt_without_the_thing_the_parts_most_prompts_with_it_have_are_its_company():
    assert usual_company(_WITH_A_HAT, _has_a_hat).negative == ("blurry", "bare head")
