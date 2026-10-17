"""Reading the enhance settings back off a stored ComfyUI graph.

A row the import scan reconstructed keeps the tail's numbers under the generic
names any sampler has — ``steps`` and ``denoise`` — and says nothing at all about
the upscale, so what it ran at can only be recovered from the graph itself. The
graph is written by an older version of this app, or by ComfyUI, or by hand, so
every step of the read is guarded; these are the guards.
"""
from __future__ import annotations

import json

import pytest

from origenerator.gallery.enhance_graph import graph_level_params

_KEYS = ("checkpoint", "upscale_model", "enhance_scale", "enhance_steps",
         "enhance_denoise", "enhance_controlnet", "enhance_controlnet_strength",
         "enhance_detail_fixes")


def _row(graph):
    return {"workflow_json": json.dumps(graph)}


def _sampler_graph():
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": "example_model_v2.safetensors"}},
        "2": {"class_type": "UpscaleModelLoader",
              "inputs": {"model_name": "example_upscaler_4x.pth"}},
        "3": {"class_type": "ImageScaleBy", "inputs": {"image": ["5", 0], "scale_by": 0.5}},
        "4": {"class_type": "KSampler", "inputs": {"steps": 20, "denoise": 0.15}},
        "5": {"class_type": "ImageUpscaleWithModel",
              "inputs": {"upscale_model": ["2", 0], "image": ["6", 0]}},
        "6": {"class_type": "LoadImage", "inputs": {"image": "sample.png"}},
    }


def _detailer(graph, node_id, part_model, denoise):
    """One detail pass: a detector, the segs it finds, and the pass that redraws
    them — the shape the enhance workflow lays down per named part."""
    graph[str(node_id)] = {"class_type": "UltralyticsDetectorProvider",
                           "inputs": {"model_name": part_model}}
    graph[str(node_id + 1)] = {"class_type": "BboxDetectorSEGS",
                               "inputs": {"bbox_detector": [str(node_id), 0]}}
    graph[str(node_id + 2)] = {"class_type": "DetailerForEach",
                               "inputs": {"segs": [str(node_id + 1), 0],
                                          "denoise": denoise}}
    return graph


def test_a_graph_gives_up_every_setting_the_row_itself_is_vague_about():
    found = graph_level_params(_row(_sampler_graph()), _KEYS)

    assert found["checkpoint"] == "example_model_v2.safetensors"
    assert found["upscale_model"] == "example_upscaler_4x.pth"
    assert found["enhance_steps"] == 20
    assert found["enhance_denoise"] == 0.15


def test_the_scale_is_read_back_through_the_model_s_own_factor():
    # ImageScaleBy holds the fraction of the upscale model's 4x output the
    # result was taken back down to, so the number a reader wants is the product.
    found = graph_level_params(_row(_sampler_graph()), _KEYS)

    assert found["enhance_scale"] == 2.0


def test_a_detail_pass_is_named_by_the_detector_two_nodes_back():
    # Each pass says which part it redrew only by way of the model that found
    # the regions — the pass itself carries nothing but a denoise.
    graph = _detailer(_sampler_graph(), 10, "bbox/face_yolov8m.pt", 0.4)

    fixes = graph_level_params(_row(graph), _KEYS)["enhance_detail_fixes"]

    assert list(fixes.values()) == [0.4]
    assert len(fixes) == 1


def test_the_passes_come_back_in_the_order_they_ran():
    # Sorted by node id, not by the graph's key order, which only happens to
    # agree — a graph is a JSON object and its keys are whatever was written.
    graph = _detailer(_sampler_graph(), 20, "bbox/hand_yolov8s.pt", 0.3)
    graph = _detailer(graph, 10, "bbox/face_yolov8m.pt", 0.5)

    fixes = graph_level_params(_row(graph), _KEYS)["enhance_detail_fixes"]

    assert list(fixes.values()) == [0.5, 0.3]


def test_a_node_id_that_is_not_a_number_sorts_last_rather_than_raising():
    # A hand-authored graph names its nodes; it still has to be readable.
    graph = _detailer(_sampler_graph(), 10, "bbox/face_yolov8m.pt", 0.5)
    graph["late"] = {"class_type": "DetailerForEach",
                     "inputs": {"segs": ["11", 0], "denoise": 0.9}}

    fixes = graph_level_params(_row(graph), _KEYS)["enhance_detail_fixes"]

    assert list(fixes.values())[-1] == 0.9


def test_a_pass_whose_detector_cannot_be_followed_is_left_out():
    # A link is [node_id, output_index]; anything else on that input is a
    # literal, and a literal there names no part.
    graph = _sampler_graph()
    graph["10"] = {"class_type": "DetailerForEach",
                   "inputs": {"segs": "not a link", "denoise": 0.4}}

    assert "enhance_detail_fixes" not in graph_level_params(_row(graph), _KEYS)


def test_only_the_keys_asked_for_come_back():
    # What a level records is the caller's business; this only reads the graph.
    found = graph_level_params(_row(_sampler_graph()), ("enhance_steps",))

    assert found == {"enhance_steps": 20}


def test_a_setting_the_graph_left_empty_is_absent_rather_than_none():
    graph = _sampler_graph()
    graph["4"]["inputs"] = {"steps": 20}   # a sampler with no denoise on it

    found = graph_level_params(_row(graph), _KEYS)

    assert "enhance_denoise" not in found
    assert found["enhance_steps"] == 20


def test_a_graph_that_cannot_be_read_gives_up_nothing():
    # Guarded at every step, because this reads a graph off a stored row: an
    # older version of this app wrote some of them, and ComfyUI wrote others.
    assert graph_level_params({"workflow_json": "not json"}, _KEYS) == {}
    assert graph_level_params({"workflow_json": "[1, 2]"}, _KEYS) == {}
    assert graph_level_params({"workflow_json": None}, _KEYS) == {}
    assert graph_level_params({}, _KEYS) == {}


def test_a_graph_of_things_that_are_not_nodes_gives_up_nothing():
    assert graph_level_params(_row({"1": "not a node", "2": {"inputs": 7}}),
                              _KEYS) == {}


def _held(graph, node_id, controlnet, strength, *, union):
    """The hold the enhance tail lays down: the ControlNet, through the node
    that picks a union file's head, applied to a depth map of the rescaled
    picture."""
    graph[str(node_id)] = {"class_type": "ControlNetLoader",
                           "inputs": {"control_net_name": controlnet}}
    applied = [str(node_id), 0]
    if union:
        graph[str(node_id + 1)] = {"class_type": "SetUnionControlNetType",
                                   "inputs": {"control_net": applied, "type": "depth"}}
        applied = [str(node_id + 1), 0]
    graph[str(node_id + 2)] = {"class_type": "DownloadAndLoadDepthAnythingV2Model",
                               "inputs": {"model": "example_depth_model.safetensors"}}
    graph[str(node_id + 3)] = {"class_type": "DepthAnything_V2",
                               "inputs": {"da_model": [str(node_id + 2), 0],
                                          "images": ["3", 0]}}
    graph[str(node_id + 4)] = {"class_type": "ControlNetApplyAdvanced",
                               "inputs": {"control_net": applied,
                                          "image": [str(node_id + 3), 0],
                                          "strength": strength}}
    return graph


@pytest.mark.parametrize("union", [True, False])
def test_a_held_graph_gives_up_its_strength_and_the_model_it_was_held_with(union):
    graph = _held(_sampler_graph(), 20, "example_controlnet.safetensors", 0.6, union=union)

    found = graph_level_params(_row(graph), _KEYS)

    assert found["enhance_controlnet_strength"] == 0.6
    assert found["enhance_controlnet"] == "example_controlnet.safetensors"


def test_a_structure_pass_on_a_depth_or_pose_hint_is_not_a_hold():
    graph = _sampler_graph()
    graph["10"] = {"class_type": "ControlNetLoader",
                   "inputs": {"control_net_name": "example_controlnet.safetensors"}}
    graph["11"] = {"class_type": "DepthAnything_V2", "inputs": {"images": ["2", 0]}}
    graph["12"] = {"class_type": "ControlNetApplyAdvanced",
                   "inputs": {"control_net": ["10", 0], "image": ["11", 0],
                              "strength": 0.8}}

    found = graph_level_params(_row(graph), _KEYS)

    assert "enhance_controlnet_strength" not in found
    assert "enhance_controlnet" not in found


def test_a_structure_pass_whose_depth_map_is_of_the_scaled_input_is_not_a_hold():
    graph = _sampler_graph()
    graph["10"] = {"class_type": "ImageScale",
                   "inputs": {"image": ["6", 0], "width": 832, "height": 1216}}
    graph["11"] = {"class_type": "DepthAnything_V2", "inputs": {"images": ["10", 0]}}
    graph["12"] = {"class_type": "ControlNetLoader",
                   "inputs": {"control_net_name": "example_controlnet.safetensors"}}
    graph["13"] = {"class_type": "ControlNetApplyAdvanced",
                   "inputs": {"control_net": ["12", 0], "image": ["11", 0],
                              "strength": 0.8}}

    found = graph_level_params(_row(graph), _KEYS)

    assert "enhance_controlnet_strength" not in found
    assert "enhance_controlnet" not in found
