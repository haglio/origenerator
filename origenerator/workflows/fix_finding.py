from __future__ import annotations

import re

from origenerator import points_of_interest
from origenerator.workflows.detail_parts import DetailFixPass, DetailPart, detector_part, finder_of

_DETECTOR_THRESHOLD = 0.5     # how sure the detector must be to call it a face
_DETECTOR_CROP_FACTOR = 3.0   # how much context around the rect the sampler sees
_DETECTOR_DROP_SIZE = 10      # rects smaller than this are noise, not anatomy

_DETECTOR_NODE = re.compile(r"fix(\d+)_detector")


def finding_nodes(index: int, fix: DetailFixPass, image_ref, original_ref) -> tuple[dict, list]:
    provider_id, segs_id = f"fix{index}_detector", f"fix{index}_segs"
    finder = finder_of(fix.part)
    nodes = {
        provider_id: {
            "class_type": "UltralyticsDetectorProvider",
            # The provider's own picker prefixes its detector models
            # this way, and hands out an outline only for a segm/ one.
            "inputs": {"model_name": f"{finder}/{fix.detector}"},
        },
        segs_id: {
            "class_type": f"{finder.capitalize()}DetectorSEGS",
            "inputs": {
                f"{finder}_detector": [provider_id, 1 if fix.part.outline else 0],
                "image": image_ref,
                "threshold": _DETECTOR_THRESHOLD,
                "dilation": fix.part.dilation,
                "crop_factor": _DETECTOR_CROP_FACTOR,
                "drop_size": _DETECTOR_DROP_SIZE,
                "labels": "all",
            },
        },
    }
    nodes.update(points_of_interest.report_nodes(index, [segs_id, 0], original_ref))
    return nodes, [segs_id, 0]


_GRAPH_AT = 2


def parts_found_by(history_data: dict) -> dict[int, DetailPart]:
    run = history_data.get("prompt")
    graph = (run[_GRAPH_AT] if isinstance(run, list | tuple) and len(run) > _GRAPH_AT
             and isinstance(run[_GRAPH_AT], dict) else {})
    return {int(found[1]): part for node_id, node in graph.items()
            if (found := _DETECTOR_NODE.fullmatch(str(node_id))) and isinstance(node, dict)
            and (part := detector_part(str((node.get("inputs") or {}).get("model_name", "")))) is not None}
