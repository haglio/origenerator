from __future__ import annotations

import pytest

from origenerator.box_breaks import BOX_BREAK
from origenerator.prompt_checks import (
    bad_weights,
    duplicate_things,
    tidied,
    unpaired_parentheses,
    unread_emphasis,
)


def _spanned(text: str, spans) -> list[str]:
    return [text[start:end] for start, end in spans]


def test_a_parenthesis_with_no_partner_is_unpaired_wherever_it_stands():
    assert unpaired_parentheses("a (b c") == (2,)
    assert unpaired_parentheses("a b) c") == (3,)
    assert unpaired_parentheses(")a(") == (0, 2)


def test_parentheses_pair_off_however_deep_they_nest():
    assert unpaired_parentheses("(a (b:1.2) c)") == ()
    assert unpaired_parentheses("((a) b") == (0,)
    assert unpaired_parentheses("(a)) b") == (3,)


def test_an_escaped_parenthesis_is_a_plain_character_and_needs_no_partner():
    assert unpaired_parentheses(r"a \(b") == ()
    assert unpaired_parentheses(r"(a \) b") == (0,)


@pytest.mark.parametrize(("text", "bad"), [
    ("a, b:1.2), c", [":1.2)"]),
    ("(a:), b", [":)"]),
    ("(a:high), b", [":high)"]),
    ("(a:1.2.3)", [":1.2.3)"]),
    ("(:1.2)", [":1.2)"]),
    ("a:1.2, b", [":1.2"]),
    ("a, b:1.2", [":1.2"]),
    ("(a):1.2, b", ["):1.2"]),
])
def test_a_badly_formatted_number_at_the_end_of_a_thing_is_found(text, bad):
    assert _spanned(text, bad_weights(text)) == bad


@pytest.mark.parametrize("text", [
    "(a:1.2), b",
    "(a b:.8)",
    "((a:1.2) b:1.1)",
    "a, b",
    "16:9, b",
    "<lora:name:0.8> a",
])
def test_a_well_formed_prompt_has_no_badly_formatted_number(text):
    assert bad_weights(text) == ()


def test_every_copy_of_a_thing_set_apart_by_commas_is_a_duplicate():
    text = "red cat, a dog, red cat"
    assert _spanned(text, duplicate_things(text)) == ["red cat", "red cat"]


def test_duplicates_ignore_capitals_and_the_spaces_around_and_within_a_thing():
    text = "Red  cat ,a dog,  red cat"
    assert _spanned(text, duplicate_things(text)) == ["Red  cat", "red cat"]


def test_words_shared_by_different_things_are_no_duplicate():
    assert duplicate_things("red cat, red dog, ,") == ()


@pytest.mark.parametrize(("messy", "clean"), [
    ("a  b", "a b"),
    ("  a b  ", "a b"),
    ("a , b", "a, b"),
    ("a,b", "a, b"),
    ("a,(b)", "a, (b)"),
    ("1,000 cats", "1,000 cats"),
    ("a,, b", "a, b"),
    ("a, , , b", "a, b"),
    (", a, b,", "a, b"),
    ("a, \nb", "a,\nb"),
    (f"a, b,{BOX_BREAK} c", f"a, b,{BOX_BREAK}c"),
    (f"a,{BOX_BREAK},b", f"a,{BOX_BREAK}b"),
])
def test_tidying_cleans_spaces_and_commas(messy, clean):
    assert tidied(messy) == clean


def test_tidying_a_tidy_prompt_changes_nothing():
    assert tidied("a (b:1.2), c\nd") == "a (b:1.2), c\nd"


@pytest.mark.parametrize(("many", "numeric"), [
    ("((a))", "(a:1.21)"),
    ("(((a b)))", "(a b:1.331)"),
    ("((a:1.2))", "(a:1.2)"),
    ("x, ((a)), y", "x, (a:1.21), y"),
])
def test_stacked_parentheses_become_a_number_where_the_model_reads_numbers(many, numeric):
    assert tidied(many, reads_numbers=True) == numeric


@pytest.mark.parametrize("left_alone", ["(a)", "((a) b)", r"\((a))", "(a:1.2)"])
def test_parentheses_that_are_not_a_plain_stack_are_left_alone(left_alone):
    assert tidied(left_alone, reads_numbers=True) == left_alone


def test_stacked_parentheses_stay_where_the_model_reads_no_numbers():
    assert tidied("((a))") == "((a))"


@pytest.mark.parametrize(("text", "unread"), [
    ("(a:1.2), b", ["(a:1.2)"]),
    ("x, ((a b)), y", ["((a b))"]),
    ("(((a)))", ["(((a)))"]),
    ("((a:1.2))", ["((a:1.2))"]),
    ("((a:1.2) b)", ["(a:1.2)"]),
])
def test_emphasis_a_model_reads_as_plain_text_is_found_whole(text, unread):
    assert _spanned(text, unread_emphasis(text)) == unread


@pytest.mark.parametrize("text", ["a, b", "(a), b", "((a) b)", r"\\((a))", "16:9"])
def test_what_is_no_number_or_stack_of_parentheses_is_not_unread_emphasis(text):
    assert unread_emphasis(text) == ()
