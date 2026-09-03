"""The before/after rendering a Requests card shows.

Invented prompts throughout — what is under test is the marking, not any words.
"""

from origenerator.prompt_diff import ADDED, REMOVED, SAME, diff_spans


def _joined(spans, kinds) -> str:
    return "".join(text for kind, text in spans if kind in kinds)


def test_the_spans_rebuild_both_versions():
    before, after = "a woman, freckles, soft light", "a woman, soft light"

    spans = diff_spans(before, after)

    assert _joined(spans, (SAME, REMOVED)) == before
    assert _joined(spans, (SAME, ADDED)) == after


def test_a_dropped_term_is_marked_removed_and_nothing_else_is():
    spans = diff_spans("a woman, freckles, soft light", "a woman, soft light")

    assert [kind for kind, _ in spans] == [SAME, REMOVED, SAME]
    assert "freckles" in _joined(spans, (REMOVED,))


def test_an_added_term_is_marked_added():
    spans = diff_spans("a woman", "a woman, freckles")

    assert _joined(spans, (ADDED,)).strip() == ", freckles"


def test_a_reweighted_term_marks_the_weight_not_the_term():
    # The term itself did not change — the emphasis around it did, and that is
    # what should light up.
    spans = diff_spans("a woman, freckles", "a woman, (freckles:1.1)")

    assert _joined(spans, (REMOVED,)) == ""
    assert _joined(spans, (ADDED,)) == "(:1.1)"
    assert "freckles" in _joined(spans, (SAME,))


def test_identical_prompts_diff_to_one_unchanged_run():
    assert diff_spans("a woman", "a woman") == [(SAME, "a woman")]


def test_a_prompt_arriving_from_nothing_is_all_added():
    assert diff_spans("", "a woman") == [(ADDED, "a woman")]
