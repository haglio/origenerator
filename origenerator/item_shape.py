from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from PIL import Image
from shared_ui.orientation import orientation_of_size as shape_of_size

from origenerator import gallery
from origenerator.config import OUTPUT_PLACES
from origenerator.gallery.shapes import LANDSCAPE, SHAPES_AND_BOTH, on_shape
from origenerator.gallery.signatures import READINGS_KEPT, canonical_settings
from origenerator.media import MediaType
from origenerator.workflows.derived_size import resolve_input_image_path

_SEPARATOR = "::"
_INSIDE = ">"

_MEASURED_LIMIT = 20_000

_measured: OrderedDict[str, str] = OrderedDict()


def shaped_key(base_key: str, shape: str, inside: tuple[str, ...] = ()) -> str:
    return f"{base_key}{_SEPARATOR}{shape}" + "".join(_INSIDE + key for key in inside)


def key_holds(outer: str, inner: str) -> bool:
    outer_base, outer_side = split_key(outer)
    inner_base, inner_side = split_key(inner)
    if outer_side != inner_side or not outer_base or not inner_base:
        return False
    return inner_base == outer_base or inner_base.startswith(outer_base + "/")


def split_key(key: str | None) -> tuple[str | None, str | None]:
    if not key:
        return key, None
    base, _, placed = key.partition(_SEPARATOR)
    shape = placed.partition(_INSIDE)[0]
    return (base, shape) if shape in SHAPES_AND_BOTH else (key, None)


def base_of(key: str | None) -> str | None:
    return split_key(key)[0]


def shape_of(key: str | None) -> str | None:
    return split_key(key)[1]


def row_shape(row: dict) -> str:
    asked = _asked_shape(row.get("workflow_name"), row.get("params_json"))
    if asked is not None:
        return asked
    return (_measure_any(_own_files(row))
            or _measure_any(_frame_candidate(gallery.parse_params(row.get("params_json"))))
            or LANDSCAPE)


@lru_cache(maxsize=READINGS_KEPT)
def _asked_shape(workflow_name: str | None, params_json: str | None) -> str | None:
    return requested_shape(canonical_settings(workflow_name, gallery.parse_params(params_json)))


def _measure_any(candidates) -> str | None:
    for candidate in candidates:
        path = str(candidate)
        remembered = _measured.get(path)
        if remembered is not None:
            _measured.move_to_end(path)
            return remembered
        try:
            with Image.open(candidate) as image:
                measured = shape_of_size(*image.size)
        except (OSError, ValueError):
            continue
        _remember(path, measured)
        return measured
    return None


def _remember(path: str, measured: str) -> None:
    _measured[path] = measured
    if len(_measured) > _MEASURED_LIMIT:
        _measured.popitem(last=False)


def _own_files(row: dict) -> Iterator[Path]:
    thumb = row.get("thumbnail_path")
    if thumb:
        yield Path(thumb)
    resolved = gallery.resolve_preview(row, OUTPUT_PLACES)
    if resolved is not None and resolved[1] == MediaType.IMAGE:
        yield Path(resolved[0])


def _frame_candidate(params: dict) -> list[Path]:
    frame = resolve_input_image_path(params.get("input_image"))
    return [frame] if frame is not None else []


def requested_shape(params: dict) -> str | None:
    try:
        width, height = int(params["width"]), int(params["height"])
    except (KeyError, TypeError, ValueError):
        return None
    return shape_of_size(width, height)


def filter_rows(rows, shape: str | None) -> list[dict]:
    return on_shape(rows, shape, row_shape)
