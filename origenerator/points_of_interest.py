"""Where an enhancement's fixes found what they redrew, asked of nodes ComfyUI already has.

The whole picture follows each pass's regions: it says how big the picture is, and ComfyUI
runs a node handed an empty list with no arguments, which would refuse the enhancement."""
from __future__ import annotations

import json
import re

FILE_KEY = "points_of_interest"
_EDGES = ("left", "top", "right", "bottom")
_REPORT_ID = re.compile(r"fix(\d+)_points")
_SIZE, _MASK, _WHOLE = "places_size", "places_mask", "places_whole"


def report_nodes(fix_index: int, segs_ref, picture_ref) -> dict:
    joined, each, one, points = (f"fix{fix_index}_{role}" for role in ("places", "each", "one", "points"))
    return {
        _SIZE: {"class_type": "GetImageSize", "inputs": {"image": picture_ref}},
        _MASK: {"class_type": "SolidMask",
                "inputs": {"value": 1.0, "width": [_SIZE, 0], "height": [_SIZE, 1]}},
        _WHOLE: {"class_type": "MaskToSEGS",
                 "inputs": {"mask": [_MASK, 0], "combined": True, "crop_factor": 1.0,
                            "bbox_fill": False, "drop_size": 1, "contour_fill": False}},
        joined: {"class_type": "ImpactSEGSConcat", "inputs": {"segs1": segs_ref, "segs2": [_WHOLE, 0]}},
        each: {"class_type": "ImpactDecomposeSEGS", "inputs": {"segs": [joined, 0]}},
        one: {"class_type": "ImpactFrom_SEG_ELT", "inputs": {"seg_elt": [each, 1]}},
        points: {"class_type": "PreviewAny", "inputs": {"source": [one, 3]}},
    }


def reported(outputs: dict) -> list[dict]:
    reports = sorted((int(found[1]), output) for node_id, output in outputs.items()
                     if (found := _REPORT_ID.fullmatch(str(node_id))))
    return [place for _order, output in reports for place in _places_in(output)]


def _places_in(output) -> list[dict]:
    regions = [region for text in (output.get("text") or () if isinstance(output, dict) else ())
               if (region := _region(text)) is not None]
    if not regions:
        return []
    *found, (_left, _top, width, height) = regions
    if width <= 0 or height <= 0:
        return []
    return [dict(zip(_EDGES, (left / width, top / height, right / width, bottom / height), strict=True))
            for left, top, right, bottom in found]


def _region(text):
    try:
        region = json.loads(text)
    except (TypeError, ValueError):
        return None
    if (isinstance(region, list) and len(region) == 4
            and all(isinstance(edge, (int, float)) for edge in region)):
        return region
    return None


def boxes_of(file_entry: dict) -> tuple[tuple[float, float, float, float], ...]:
    return tuple(tuple(place[edge] for edge in _EDGES)
                 for place in file_entry.get(FILE_KEY) or () if _is_a_place(place))


def _is_a_place(place) -> bool:
    return isinstance(place, dict) and all(isinstance(place.get(edge), (int, float)) for edge in _EDGES)
