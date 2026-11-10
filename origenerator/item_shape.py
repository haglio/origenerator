from __future__ import annotations

import os
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from PIL import Image
from shared_ui.orientation import orientation_of_size as shape_of_size

from origenerator import gallery
from origenerator.config import OUTPUT_PLACES
from origenerator.gallery.collection import LATEST_KEY, folder_collection
from origenerator.gallery.shapes import LANDSCAPE, SHAPES_AND_BOTH, on_shape
from origenerator.gallery.signatures import canonical_settings
from origenerator.generation_state import GenerationStatus, made_here
from origenerator.media import MediaType
from origenerator.output_files import READINGS_KEPT
from origenerator.workflows.derived_size import resolve_input_image_path

_SEPARATOR = "::"
_INSIDE = ">"

_STILL_BEING_MADE = frozenset({GenerationStatus.PENDING, GenerationStatus.RUNNING})


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


def what_plays_at(key: str | None, rows: list[dict]) -> list[dict]:
    base = base_of(key)
    collection = folder_collection(base)
    whole_library = base == gallery.ALL_KEY or (
        collection is not None and collection.which == LATEST_KEY
        and collection.folder == gallery.ALL_KEY)
    return [row for row in rows if made_here(row)] if whole_library else rows


def together(rows: list[dict], more: list[dict]) -> list[dict]:
    return list({row["prompt_id"]: row for row in (*rows, *more)}.values())


def base_of(key: str | None) -> str | None:
    return split_key(key)[0]


def shape_of(key: str | None) -> str | None:
    return split_key(key)[1]


def row_shape(row: dict) -> str:
    return row.get("shape") or shape_its_files_say(row) or LANDSCAPE


def shape_its_files_say(row: dict) -> str | None:
    return (_asked_shape(row.get("workflow_name"), row.get("params_json"))
            or _measure_any(_own_files(row))
            or _measure_any(_frame_candidate(gallery.parse_params(row.get("params_json")))))


def record_shapes(db) -> int:
    shapes = {row["prompt_id"]: shape for row in db.list_generations()
              if not row.get("shape") and row["status"] not in _STILL_BEING_MADE
              and (shape := shape_its_files_say(row)) is not None}
    db.fill_in("shape", shapes)
    return len(shapes)


@lru_cache(maxsize=READINGS_KEPT)
def _asked_shape(workflow_name: str | None, params_json: str | None) -> str | None:
    return requested_shape(canonical_settings(workflow_name, gallery.parse_params(params_json)))


def _measure_any(candidates) -> str | None:
    return next((shape for candidate in candidates
                 if (shape := _measured(str(candidate), _as_it_stands(candidate))) is not None),
                None)


def _as_it_stands(path) -> tuple[int, int] | None:
    try:
        stat = os.stat(path)
    except (OSError, ValueError):
        return None
    return stat.st_mtime_ns, stat.st_size


@lru_cache(maxsize=READINGS_KEPT)
def _measured(path: str, as_it_stands: tuple[int, int] | None) -> str | None:
    if as_it_stands is None:
        return None
    try:
        with Image.open(path) as image:
            return shape_of_size(*image.size)
    except (OSError, ValueError):
        return None


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
