from __future__ import annotations

import json

import pytest

from origenerator.box_breaks import BOX_BREAK, prompt_boxes, unboxed
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
