from __future__ import annotations

from origenerator.usual_company import UsualCompany, usual_company

_WITH_A_HAT = [
    ("a fisherman, a wide straw hat, frayed brim, harbor", "blurry, bare head, paper hat"),
    ("a farmer, a wide straw hat, frayed brim, a field", "blurry, Bare Head, (paper hat:1.2)"),
    ("a child, a wide straw hat, a beach", "blurry, bare head"),
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


def test_a_part_as_common_without_the_thing_is_no_company_of_it():
    company = usual_company(_WITH_A_HAT + _WITHOUT_ONE, _has_a_hat)

    assert "blurry" not in company.negative


def test_too_few_prompts_with_the_thing_show_no_company():
    assert usual_company(_WITH_A_HAT[:2] + _WITHOUT_ONE, _has_a_hat) == UsualCompany()


def test_with_no_prompt_without_the_thing_the_parts_most_prompts_with_it_have_are_its_company():
    assert usual_company(_WITH_A_HAT, _has_a_hat).negative == ("blurry", "bare head", "paper hat")
