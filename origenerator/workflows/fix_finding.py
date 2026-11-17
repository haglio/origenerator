from __future__ import annotations

import re

from origenerator import points_of_interest
from origenerator.workflows.detail_parts import DetailFixPass, DetailPart, detector_part, finder_of

_DETECTOR_MIN_CONFIDENCE = 0.5
_DETECTOR_CONTEXT_AROUND_RECT = 3.0
_DETECTOR_MIN_RECT_SIDE = 10

_DETECTOR_NODE = re.compile(r"fix(\d+)_detector")
_BEFORE_NODE = re.compile(r"fix(\d+)_before")
_BEFORE_FOLDER = "before fixes"


def finding_nodes(index: int, fix: DetailFixPass, image_ref, original_ref) -> tuple[dict, list]:
    provider_id, segs_id = f"fix{index}_detector", f"fix{index}_segs"
    finder = finder_of(fix.part)
    nodes = {
        provider_id: {
            "class_type": "UltralyticsDetectorProvider",
            # ComfyUI's detector provider dropdown prefixes its detector models
            # this way, and hands out an outline only for a segm/ one.
            "inputs": {"model_name": f"{finder}/{fix.detector}"},
        },
        segs_id: {
            "class_type": f"{finder.capitalize()}DetectorSEGS",
            "inputs": {
                f"{finder}_detector": [provider_id, 1 if fix.part.outline else 0],
                "image": image_ref,
                "threshold": _DETECTOR_MIN_CONFIDENCE,
                "dilation": fix.part.dilation,
                "crop_factor": _DETECTOR_CONTEXT_AROUND_RECT,
                "drop_size": _DETECTOR_MIN_RECT_SIDE,
                "labels": "all",
            },
        },
    }
    nodes.update(points_of_interest.report_nodes(index, [segs_id, 0], original_ref))
    return nodes, [segs_id, 0]


def before_save_node(index: int, image_ref) -> dict:
    return {f"fix{index}_before": {
        "class_type": "SaveImage",
        "inputs": {"images": image_ref, "filename_prefix": f"{_BEFORE_FOLDER}/fix{index}"}}}


def saved_before_each_fix(history_data: dict) -> list[dict]:
    saved = sorted((int(found[1]), output) for node_id, output in history_data.get("outputs", {}).items()
                   if (found := _BEFORE_NODE.fullmatch(str(node_id))))
    return [image for _index, output in saved for image in (output.get("images") or [])[:1]]


_GRAPH_AT = 2


def parts_found_by(history_data: dict) -> dict[int, DetailPart]:
    run = history_data.get("prompt")
    graph = (run[_GRAPH_AT] if isinstance(run, list | tuple) and len(run) > _GRAPH_AT
             and isinstance(run[_GRAPH_AT], dict) else {})
    return {int(found[1]): part for node_id, node in graph.items()
            if (found := _DETECTOR_NODE.fullmatch(str(node_id))) and isinstance(node, dict)
            and (part := detector_part(str((node.get("inputs") or {}).get("model_name", "")))) is not None}
