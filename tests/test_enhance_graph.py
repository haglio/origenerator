from __future__ import annotations

import json

from origenerator.gallery.enhance_graph import graph_version_params
from origenerator.workflows import WORKFLOW_REGISTRY, detail_parts

_KEYS = ("checkpoint", "upscale_model", "enhance_scale", "enhance_steps",
         "enhance_denoise", "enhance_detail_fixes")


def _row(graph):
    return {"workflow_json": json.dumps(graph)}


def _sampler_graph():
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": "example_model_v2.safetensors"}},
        "2": {"class_type": "UpscaleModelLoader",
              "inputs": {"model_name": "example_upscaler_4x.pth"}},
        "3": {"class_type": "ImageScaleBy", "inputs": {"scale_by": 0.5}},
        "4": {"class_type": "KSampler", "inputs": {"steps": 20, "denoise": 0.15}},
    }


def _detailer(graph, node_id, part_model, denoise):
    graph[str(node_id)] = {"class_type": "UltralyticsDetectorProvider",
                           "inputs": {"model_name": part_model}}
    graph[str(node_id + 1)] = {"class_type": "BboxDetectorSEGS",
                               "inputs": {"bbox_detector": [str(node_id), 0]}}
    graph[str(node_id + 2)] = {"class_type": "DetailerForEach",
                               "inputs": {"segs": [str(node_id + 1), 0],
                                          "denoise": denoise}}
    return graph


def test_a_graph_gives_up_every_setting_the_row_itself_is_vague_about():
    found = graph_version_params(_row(_sampler_graph()), _KEYS)

    assert found["checkpoint"] == "example_model_v2.safetensors"
    assert found["upscale_model"] == "example_upscaler_4x.pth", (
        "a row the import scan rebuilt keeps the tail's numbers under names any sampler has "
        "and says nothing of the upscale, which would file the version under a blank settings line")
    assert found["enhance_steps"] == 20
    assert found["enhance_denoise"] == 0.15


def test_the_scale_is_read_back_through_the_model_s_own_factor():
    found = graph_version_params(_row(_sampler_graph()), _KEYS)

    assert found["enhance_scale"] == 2.0


def test_a_detail_pass_is_named_by_the_detector_two_nodes_back():
    graph = _detailer(_sampler_graph(), 10, "bbox/face_yolov8m.pt", 0.4)

    fixes = graph_version_params(_row(graph), _KEYS)["enhance_detail_fixes"]

    assert list(fixes.values()) == [0.4]
    assert len(fixes) == 1


def test_the_passes_come_back_in_the_order_they_ran():
    graph = _detailer(_sampler_graph(), 20, "bbox/hand_yolov8s.pt", 0.3)
    graph = _detailer(graph, 10, "bbox/face_yolov8m.pt", 0.5)

    fixes = graph_version_params(_row(graph), _KEYS)["enhance_detail_fixes"]

    assert list(fixes.values()) == [0.5, 0.3], (
        "a graph's keys come in whatever order they were written, "
        "which only happens to agree with the order the passes ran in")


def test_a_node_id_that_is_not_a_number_sorts_last_rather_than_raising():
    graph = _detailer(_sampler_graph(), 10, "bbox/face_yolov8m.pt", 0.5)
    graph["late"] = {"class_type": "DetailerForEach",
                     "inputs": {"segs": ["11", 0], "denoise": 0.9}}

    fixes = graph_version_params(_row(graph), _KEYS)["enhance_detail_fixes"]

    assert list(fixes.values())[-1] == 0.9


def test_a_pass_whose_detector_cannot_be_followed_is_left_out():
    graph = _sampler_graph()
    graph["10"] = {"class_type": "DetailerForEach",
                   "inputs": {"segs": "not a link", "denoise": 0.4}}

    assert "enhance_detail_fixes" not in graph_version_params(_row(graph), _KEYS)


def test_only_the_keys_asked_for_come_back():
    found = graph_version_params(_row(_sampler_graph()), ("enhance_steps",))

    assert found == {"enhance_steps": 20}


def test_a_setting_the_graph_left_empty_is_absent_rather_than_none():
    graph = _sampler_graph()
    graph["4"]["inputs"] = {"steps": 20}

    found = graph_version_params(_row(graph), _KEYS)

    assert "enhance_denoise" not in found
    assert found["enhance_steps"] == 20


def test_a_graph_an_older_version_comfyui_or_a_hand_left_unreadable_gives_up_nothing():
    assert graph_version_params({"workflow_json": "not json"}, _KEYS) == {}
    assert graph_version_params({"workflow_json": "[1, 2]"}, _KEYS) == {}
    assert graph_version_params({"workflow_json": None}, _KEYS) == {}
    assert graph_version_params({}, _KEYS) == {}


def test_a_graph_of_things_that_are_not_nodes_gives_up_nothing():
    assert graph_version_params(_row({"1": "not a node", "2": {"inputs": 7}}),
                              _KEYS) == {}


def test_a_pass_redrawn_inside_an_outline_is_named_by_its_detector_too():
    graph = _sampler_graph()
    graph["10"] = {"class_type": "UltralyticsDetectorProvider",
                   "inputs": {"model_name": "bbox/skin_finder.pt"}}
    graph["11"] = {"class_type": "SegmDetectorSEGS",
                   "inputs": {"segm_detector": ["10", 1]}}
    graph["12"] = {"class_type": "DetailerForEach",
                   "inputs": {"segs": ["11", 0], "denoise": 0.4}}

    fixes = graph_version_params(_row(graph), _KEYS)["enhance_detail_fixes"]

    assert fixes == {"skin": 0.4}


def test_the_passes_the_enhance_workflow_lays_down_are_read_back(monkeypatch):
    monkeypatch.setattr(detail_parts, "list_detector_files", lambda: ["face_finder.pt"])
    enhance = WORKFLOW_REGISTRY["image_enhance"]
    graph = enhance.build_api_payload(dict(enhance.default_params(), input_image="pick.png",
                                           enhance_detail_fixes={"faces": 0.5}))

    assert graph_version_params(_row(graph), _KEYS)["enhance_detail_fixes"] == {"faces": 0.5}
