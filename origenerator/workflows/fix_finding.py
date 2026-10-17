"""What a Fix finds before it redraws anything: one part's detector run over a picture, and the
places it reports.

An enhancement runs this ahead of each part's redraw; a picture enhanced before the places were
kept runs it alone (:mod:`origenerator.places_backfill`). The node ids are what tells a run's
history which part each report came from (:func:`parts_found_by`)."""
from __future__ import annotations

import re

from origenerator import points_of_interest
from origenerator.workflows.detail_parts import DetailPart, detector_part

# The detector node's own defaults, kept as named constants rather than as settings: every one of
# these is a value the user's answer would be a guess at.
_DETECTOR_THRESHOLD = 0.5     # how sure the detector must be to call it a face
_DETECTOR_DILATION = 10       # pixels grown around each rect, so edges are inside
_DETECTOR_CROP_FACTOR = 3.0   # how much context around the rect the sampler sees
_DETECTOR_DROP_SIZE = 10      # rects smaller than this are noise, not anatomy

_DETECTOR_NODE = re.compile(r"fix(\d+)_detector")


def finding_nodes(index: int, detector: str, image_ref, picture_ref) -> tuple[dict, list]:
    provider_id, segs_id = f"fix{index}_detector", f"fix{index}_segs"
    nodes = {
        provider_id: {
            "class_type": "UltralyticsDetectorProvider",
            # The provider's own picker prefixes its detector models
            # this way, and the value is matched against that list.
            "inputs": {"model_name": f"bbox/{detector}"},
        },
        segs_id: {
            "class_type": "BboxDetectorSEGS",
            "inputs": {
                "bbox_detector": [provider_id, 0],
                "image": image_ref,
                "threshold": _DETECTOR_THRESHOLD,
                "dilation": _DETECTOR_DILATION,
                "crop_factor": _DETECTOR_CROP_FACTOR,
                "drop_size": _DETECTOR_DROP_SIZE,
                "labels": "all",
            },
        },
    }
    nodes.update(points_of_interest.report_nodes(index, [segs_id, 0], picture_ref))
    return nodes, [segs_id, 0]


def parts_found_by(history_data: dict) -> dict[int, DetailPart]:
    run = history_data.get("prompt")
    graph = run[2] if isinstance(run, list | tuple) and len(run) > 2 and isinstance(run[2], dict) else {}
    return {int(found[1]): part for node_id, node in graph.items()
            if (found := _DETECTOR_NODE.fullmatch(str(node_id))) and isinstance(node, dict)
            and (part := detector_part(str((node.get("inputs") or {}).get("model_name", "")))) is not None}
