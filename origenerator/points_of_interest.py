from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping
from itertools import combinations

FILE_KEY = "points_of_interest"
_FORMAT_KEY = "points_of_interest_format"
_FORMAT = 1
_EDGES = ("left", "top", "right", "bottom")
_REPORT_ID = re.compile(r"fix(\d+)_points")
_SIZE, _MASK, _WHOLE = "places_size", "places_mask", "places_whole"


def report_nodes(fix_index: int, segs_ref, original_ref) -> dict:
    joined, each, one, points = (f"fix{fix_index}_{role}" for role in ("places", "each", "one", "points"))
    return {
        _SIZE: {"class_type": "GetImageSize", "inputs": {"image": original_ref}},
        _MASK: {"class_type": "SolidMask",
                "inputs": {"value": 1.0, "width": [_SIZE, 0], "height": [_SIZE, 1]}},
        _WHOLE: {"class_type": "MaskToSEGS",
                 "inputs": {"mask": [_MASK, 0], "combined": True, "crop_factor": 1.0,
                            "bbox_fill": False, "drop_size": 1, "contour_fill": False}},
        joined: {"class_type": "ImpactSEGSConcat",  # never empty: ComfyUI refuses a run over that
                 "inputs": {"segs1": segs_ref, "segs2": [_WHOLE, 0]}},
        each: {"class_type": "ImpactDecomposeSEGS", "inputs": {"segs": [joined, 0]}},
        one: {"class_type": "ImpactFrom_SEG_ELT", "inputs": {"seg_elt": [each, 1]}},
        points: {"class_type": "PreviewAny", "inputs": {"source": [one, 3]}},
    }


def reported(outputs: dict, parts: Mapping | None = None) -> list[dict] | None:
    reports = sorted((int(found[1]), output) for node_id, output in outputs.items()
                     if (found := _REPORT_ID.fullmatch(str(node_id))))
    if not reports:
        return None
    return [place for index, output in reports
            for place in _of_part(_places_in(output), (parts or {}).get(index))]


def _of_part(places: list[dict], part) -> list[dict]:
    if part is None:
        return places
    return [{**place, "part": part.name} for place in places]


def _overlap(one: dict, other: dict) -> bool:
    return (one["left"] < other["right"] and other["left"] < one["right"]
            and one["top"] < other["bottom"] and other["top"] < one["bottom"])


def _union(one: dict, other: dict) -> dict:
    return {"left": min(one["left"], other["left"]), "top": min(one["top"], other["top"]),
            "right": max(one["right"], other["right"]), "bottom": max(one["bottom"], other["bottom"])}


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
    if (isinstance(region, list) and len(region) == len(_EDGES)
            and all(isinstance(edge, (int, float)) for edge in region)):
        return region
    return None


def kept(places: list[dict]) -> dict:
    return {FILE_KEY: places, _FORMAT_KEY: _FORMAT}


def kept_the_current_way(file_entry: dict) -> bool:
    return file_entry.get(_FORMAT_KEY) == _FORMAT


def boxes_of(file_entry: dict, *,
             framed_together: Collection[str]) -> tuple[tuple[float, float, float, float], ...]:
    places = [place for place in file_entry.get(FILE_KEY) or () if _is_a_place(place)]
    return tuple(tuple(place[edge] for edge in _EDGES) for place in _close_ups(places, framed_together))


def _close_ups(places: list[dict], framed_together: Collection[str]) -> list[dict]:
    partners = _partners(places, framed_together)
    close_ups = []
    for index, place in enumerate(places):
        partner = partners.get(index)
        if partner is None:
            close_ups.append(place)
        elif partner > index:
            close_ups.append(_union(place, places[partner]))
    return close_ups


def _partners(places: list[dict], framed_together: Collection[str]) -> dict[int, int]:
    pairs = sorted((_distance(one, other), first, second)
                   for (first, one), (second, other) in combinations(enumerate(places), 2)
                   if one.get("part") in framed_together and other.get("part") == one.get("part")
                   and _overlap(one, other))
    partners: dict[int, int] = {}
    for _, first, second in pairs:
        if first not in partners and second not in partners:
            partners[first], partners[second] = second, first
    return partners


def _distance(one: dict, other: dict) -> float:
    return ((one["left"] + one["right"] - other["left"] - other["right"]) ** 2
            + (one["top"] + one["bottom"] - other["top"] - other["bottom"]) ** 2)


def _is_a_place(place) -> bool:
    return isinstance(place, dict) and all(isinstance(place.get(edge), (int, float)) for edge in _EDGES)
