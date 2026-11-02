from __future__ import annotations

import json

from origenerator.workflows.base import UPSCALE_MODEL_FACTOR
from origenerator.workflows.detail_parts import detector_part_label

_SETTINGS_BY_NODE = {
    "CheckpointLoaderSimple": lambda inputs: {"checkpoint": inputs.get("ckpt_name")},
    "UpscaleModelLoader": lambda inputs: {"upscale_model": inputs.get("model_name")},
    "ImageScaleBy": lambda inputs: (
        {"enhance_scale": inputs["scale_by"] * UPSCALE_MODEL_FACTOR}
        if isinstance(inputs.get("scale_by"), (int, float)) else {}
    ),
    "KSampler": lambda inputs: {"enhance_steps": inputs.get("steps"),
                                "enhance_denoise": inputs.get("denoise")},
}

_DETAIL_PASS = "DetailerForEach"


def graph_version_params(row: dict, keys) -> dict:
    graph = _graph_of(row)
    found = {}
    for _node_id, inputs, node_type in _nodes_of(graph):
        found.update(_SETTINGS_BY_NODE.get(node_type, lambda _inputs: {})(inputs))
    fixes = _detail_fixes(graph)
    if fixes:
        found["enhance_detail_fixes"] = fixes
    return {k: v for k, v in found.items() if v is not None and k in keys}


def _graph_of(row: dict) -> dict:
    try:
        graph = json.loads(row.get("workflow_json") or "{}")
    except (TypeError, ValueError):
        return {}
    return graph if isinstance(graph, dict) else {}


def _nodes_of(graph: dict):
    for node_id, node in graph.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if isinstance(inputs, dict):
            yield node_id, inputs, node.get("class_type")


def _detail_fixes(graph: dict) -> dict:
    passes = sorted(((_node_order(node_id), inputs)
                     for node_id, inputs, node_type in _nodes_of(graph)
                     if node_type == _DETAIL_PASS),
                    key=lambda pair: pair[0])
    fixes = {}
    for _order, inputs in passes:
        segs = _linked_inputs(graph, inputs.get("segs"))
        finder = segs.get("segm_detector") or segs.get("bbox_detector")
        model = _linked_inputs(graph, finder).get("model_name")
        denoise = inputs.get("denoise")
        if isinstance(model, str) and isinstance(denoise, (int, float)):
            fixes[detector_part_label(model.rsplit("/", 1)[-1])] = denoise
    return fixes


def _node_order(node_id) -> int:
    try:
        return int(node_id)
    except (TypeError, ValueError):
        return 1 << 30


def _linked_inputs(graph: dict, ref) -> dict:
    if not (isinstance(ref, (list, tuple)) and ref and isinstance(ref[0], (str, int))):
        return {}
    node = graph.get(str(ref[0]))
    inputs = node.get("inputs") if isinstance(node, dict) else None
    return inputs if isinstance(inputs, dict) else {}
