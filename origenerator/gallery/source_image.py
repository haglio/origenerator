from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cache, partial

from origenerator.gallery.output import (
    frame_names_of,
    input_image_reference,
    media_type_of_row,
)
from origenerator.gallery.signatures import (
    _frame_name,
    _registered,
    parse_params,
    settings_signature,
)
from origenerator.generation_state import GenerationSource, in_sight, made_here, source_of
from origenerator.media import MediaType


@dataclass
class _ImageConfig:
    prompt_id: str
    signature: str
    rebuildable: bool


def source_image_id_for(input_image: str | None, image_rows: list[dict]) -> str | None:
    image = _image_named(input_image, image_rows)
    return image["prompt_id"] if image is not None else None


def _image_named(input_image: str | None, image_rows: list[dict]) -> dict | None:
    if not input_image:
        return None
    target = _frame_name(input_image)
    return next((image for image in image_rows
                 if target in frame_names_of(image.get("output_files"))), None)


def source_image_of(row: dict, image_rows: list[dict]) -> dict | None:
    return _image_named(_start_frame_of(row), image_rows)


def start_images_among(image_rows: list[dict]) -> Callable[[dict], dict | None]:
    named = cache(partial(_image_named, image_rows=image_rows))
    return lambda row: named(_start_frame_of(row))


def rebuildable_source_image(row: dict, image_rows: list[dict]) -> dict | None:
    source = source_image_of(row, image_rows)
    return source if source is not None and _rebuildable(source) else None


def _rebuildable(image: dict) -> bool:
    return _registered(image.get("workflow_name")) is not None


def find_source_image_id(row: dict, image_rows: list[dict]) -> str | None:
    image = source_image_of(row, image_rows)
    return image["prompt_id"] if image is not None else None


def source_image_id_in(row: dict, image_index: dict) -> str | None:
    return source_image_id_of(_start_frame_of(row), image_index)


def source_image_id_of(input_image: str | None, image_index: dict) -> str | None:
    entry = image_index.get(_frame_name(input_image))
    return (entry.prompt_id or None) if entry is not None else None


def rebuildable_source_image_id_in(row: dict, image_index: dict) -> str | None:
    entry = image_index.get(_frame_name(_start_frame_of(row)))
    return (entry.prompt_id or None) if entry is not None and entry.rebuildable else None


def _start_frame_of(row: dict) -> str | None:
    return parse_params(row.get("params_json")).get("input_image")


def image_lent_by(prompt_id: str, row_of: Callable[[str], dict | None],
                  image_index: dict) -> dict | None:
    row = row_of(prompt_id)
    if row is not None and media_type_of_row(row) == MediaType.VIDEO:
        source = source_image_id_in(row, image_index)
        row = row_of(source) if source else None
    return row if input_image_reference(row) is not None else None


def landing_for(prompt_id: str, rows: list[dict], image_index: dict) -> str:
    row = next((r for r in rows if r.get("prompt_id") == prompt_id), None)
    if row is None:
        return prompt_id
    return next((video["prompt_id"] for video in rows
                 if was_taken_from(row, video)
                 and source_image_id_in(video, image_index) == prompt_id), prompt_id)


def image_config_index_of(rows: list[dict]) -> dict:
    return build_image_config_index(
        [row for row in rows if media_type_of_row(row) == MediaType.IMAGE])


def build_image_config_index(image_rows: list[dict]) -> dict[str, _ImageConfig]:
    index: dict[str, _ImageConfig] = {}
    for image in image_rows:
        workflow_name = image.get("workflow_name") or "unknown"
        signature = settings_signature(workflow_name, image.get("params_json"),
                                       workflow_version=image.get("workflow_version"))
        config = _ImageConfig(prompt_id=image.get("prompt_id") or "", signature=signature,
                              rebuildable=_rebuildable(image))
        for name in frame_names_of(image.get("output_files")):
            index.setdefault(name, config)
    return index


def videos_from_source_image(image_row: dict, video_rows: list[dict]) -> list[dict]:
    image_id = image_row.get("prompt_id")
    if image_id is None:
        return []
    return [v for v in video_rows if find_source_image_id(v, [image_row]) == image_id
            and was_made_from(v, image_row)]


def was_made_from(video: dict, image: dict) -> bool:
    return made_here(video) or in_sight(image)


def was_taken_from(frame: dict, video: dict) -> bool:
    return (source_of(frame) == GenerationSource.STARTING_FRAME
            and source_of(video) == GenerationSource.OUTSIDE)
