from __future__ import annotations

import json

import pytest

from origenerator.box_breaks import BOX_BREAK, baselines_for, flowed, prompt_boxes, unboxed
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.base import prompt_conditioning
from tests.graph_reading import read_in_order as _read_in_order

_CLIP = ["1", 1]


def _encodes(nodes: dict) -> dict[str, str]:
    return {node_id: node["inputs"]["text"] for node_id, node in nodes.items()
            if node["class_type"] == "CLIPTextEncode"}


def test_a_prompt_without_a_box_break_is_one_box_exactly_as_stored():
    assert prompt_boxes("a quiet harbor, (boats:1.2)  ") == ["a quiet harbor, (boats:1.2)  "]


def test_a_boxed_prompt_splits_at_each_box_break():
    assert prompt_boxes(f"one, two, {BOX_BREAK}three") == ["one, two, ", "three"]


def test_a_boxed_prompt_read_whole_reads_each_box_break_as_a_space():
    assert unboxed(f"one, two,{BOX_BREAK}three") == "one, two, three"


def test_an_unboxed_prompt_is_encoded_exactly_as_it_always_was():
    assert prompt_conditioning("2", _CLIP, "a quiet harbor") == {
        "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": _CLIP, "text": "a quiet harbor"}}}


def test_each_box_is_encoded_on_its_own_and_joined_in_order_under_the_graphs_node():
    nodes = prompt_conditioning("2", _CLIP, f"one {BOX_BREAK}two {BOX_BREAK}three")

    assert _read_in_order(nodes, "2") == ["one ", "two ", "three"]
    assert all(node["inputs"]["clip"] == _CLIP for node in nodes.values()
               if node["class_type"] == "CLIPTextEncode")


def test_a_fixs_words_go_ahead_of_an_unboxed_prompt_as_they_always_did():
    assert _encodes(prompt_conditioning("fix0_positive", _CLIP, "a harbor", ahead="sharp hands")) == {
        "fix0_positive": "sharp hands, a harbor"}


def test_a_fixs_words_are_their_own_piece_ahead_of_a_boxed_prompts_boxes():
    nodes = prompt_conditioning("fix0_positive", _CLIP, f"one {BOX_BREAK}two", ahead="sharp hands")

    assert _read_in_order(nodes, "fix0_positive") == ["sharp hands", "one ", "two"]


def test_an_empty_box_is_never_read():
    nodes = prompt_conditioning("2", _CLIP, f"one {BOX_BREAK} {BOX_BREAK}two")

    assert _read_in_order(nodes, "2") == ["one ", "two"]


@pytest.mark.parametrize("name", sorted(name for name, workflow in WORKFLOW_REGISTRY.items()
                                        if workflow.generates_here))
def test_no_workflow_hands_comfyui_a_box_break(name):
    workflow = WORKFLOW_REGISTRY[name]
    params = dict(workflow.default_params(), input_image="pick.png",
                  positive_prompt=f"a lantern {BOX_BREAK}on a jetty",
                  negative_prompt=f"blurry {BOX_BREAK}dim")

    assert BOX_BREAK not in json.dumps(workflow.payload_for_comfyui(params))


def _words(text: str) -> int:
    return len(text.split())


def test_a_box_within_its_limit_is_left_as_it_is():
    assert flowed(["a b "], _words, limit=2) == (["a b "], None)


def test_a_word_that_runs_past_a_boxs_end_moves_whole_into_a_new_box():
    assert flowed(["a b c"], _words, limit=2) == (["a b", "c"], None)


def test_words_moved_into_a_full_box_push_its_last_words_on():
    assert flowed(["a b c", "d e"], _words, limit=2) == (["a b", "c d", "e"], None)


def test_with_room_whole_words_flow_back_up_and_an_emptied_box_goes():
    assert flowed(["a", "b c", "d"], _words, limit=2) == (["a b", "c d"], None)


def test_a_box_left_empty_disappears_but_one_box_always_stays():
    assert flowed(["a", "", "b"], _words, limit=2) == (["a b"], None)
    assert flowed([""], _words, limit=2) == ([""], None)


def test_a_weighted_phrase_moves_whole():
    assert flowed(["a (b c:1.2)"], _words, limit=2) == (["a", "(b c:1.2)"], None)


def test_an_escaped_bracket_holds_no_phrase_together():
    assert flowed([r"a \(b c\)"], _words, limit=2) == ([r"a \(b", r"c\)"], None)


def test_a_word_too_long_for_any_box_stays_where_it_is():
    assert flowed(["abcdef"], len, limit=3) == (["abcdef"], None)


def test_a_word_is_never_split_at_its_letters():
    assert flowed(["  ab cd"], _words, limit=1) == (["  ab", "cd"], None)


def test_the_boxes_ahead_of_the_one_edited_only_take_words_back_up():
    assert flowed(["a b c d", "e"], _words, start=1, limit=3) == (["a b c d", "e"], None)
    assert flowed(["a b", "c d"], _words, start=1, limit=3) == (["a b c", "d"], None)


def test_a_box_emptied_ahead_of_the_one_edited_leaves_that_one_flowing():
    assert flowed(["", "a b c"], _words, start=1, limit=2) == (["a b", "c"], None)


def test_the_caret_follows_the_word_it_was_in():
    assert flowed(["a b cd"], _words, caret=(0, 5), limit=2) == (["a b", "cd"], (1, 1))


def test_the_caret_at_a_words_start_goes_with_it():
    assert flowed(["a b cd"], _words, caret=(0, 4), limit=2) == (["a b", "cd"], (1, 0))


def test_the_caret_after_a_words_space_goes_with_it():
    assert flowed(["a b cd "], _words, caret=(0, 7), limit=2) == (["a b", "cd "], (1, 3))


def test_the_caret_stays_put_when_its_word_stays():
    assert flowed(["a b c"], _words, caret=(0, 1), limit=2) == (["a b", "c"], (0, 1))


def test_a_word_flowing_up_to_the_caret_leaves_a_space_on_either_side_of_it():
    assert flowed(["a b ", "d"], _words, caret=(0, 4), limit=3) == (["a b  d"], (0, 4))


def test_the_caret_in_a_box_left_empty_goes_to_the_end_of_the_box_before():
    assert flowed(["a b", "", "c"], _words, start=1, caret=(1, 0), limit=2) == (
        ["a b", "c"], (0, 3))


def test_each_box_is_marked_against_its_own_share_of_the_prompt_it_came_from():
    assert baselines_for("a b c d", ["a b", "c d"]) == ["a b", "c d"]


def test_a_word_that_only_moved_to_another_box_is_no_change_to_either():
    assert baselines_for("a b c", ["a b", "c"]) == ["a b", "c"]
    assert baselines_for(f"a b{BOX_BREAK}c", ["a b c"]) == ["a b c"]


def test_a_word_taken_out_is_marked_in_the_box_it_left():
    assert baselines_for("a b c d", ["a", "c d"]) == ["a b", "c d"]
