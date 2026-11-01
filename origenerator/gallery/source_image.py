"""Linking an image-conditioned video to the image generation that seeded it.

An i2v row references its start frame by filename; these helpers match that back
to the image generation that produced the file, index every image by the
configuration that made it (so a video can find its frame's settings signature and
folder name in O(1)), and invert the relation to list the videos an image was
animated into. The bridge between a video's folders and its start frame's.
"""
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
    """How the gallery keys and names an image used as an i2v's start frame."""

    prompt_id: str  # which image it is — what the source-image tier groups on
    signature: str  # the image's settings signature — what names it below
    rebuildable: bool


def source_image_id_for(input_image: str | None, image_rows: list[dict]) -> str | None:
    """The prompt_id of the image generation an ``input_image`` value names.

    I2V rows reference their start frame by filename; match it to an
    image generation by basename (through any ``[output]`` annotation). ``None``
    when the value is empty or none of ``image_rows`` produced a file with that
    name. Takes the bare value so the Generate tab — which has the field, not a
    stored row — can resolve it the same way :func:`find_source_image_id` does.
    """
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
    """:func:`source_image_of` for many rows over one pool, each start frame
    looked for once however many rows share it."""
    named = cache(partial(_image_named, image_rows=image_rows))
    return lambda row: named(_start_frame_of(row))


def rebuildable_source_image(row: dict, image_rows: list[dict]) -> dict | None:
    source = source_image_of(row, image_rows)
    return source if source is not None and _rebuildable(source) else None


def _rebuildable(image: dict) -> bool:
    return _registered(image.get("workflow_name")) is not None


def find_source_image_id(row: dict, image_rows: list[dict]) -> str | None:
    """Return the prompt_id of the image used as this row's ``input_image``.

    I2V rows reference their start frame by filename; match it to an
    image generation by basename. Returns ``None`` when the row has no input
    image or none of ``image_rows`` produced a file with that name.
    """
    image = source_image_of(row, image_rows)
    return image["prompt_id"] if image is not None else None


def source_image_id_in(row: dict, image_index: dict) -> str | None:
    """The prompt_id of the image ``row``'s start frame is, read off
    ``image_index`` (see :func:`build_image_config_index`) rather than searched
    for: what a walk of the whole library asks of every video in it. ``None``
    for a row with no input image, or one no indexed generation produced."""
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


def build_image_config_index(image_rows: list[dict]) -> dict[str, _ImageConfig]:
    """Map each image's output filename to the generation that produced it.

    Keyed by output basename (lowercased, matching how an ``input_image`` value
    resolves), so an i2v row can look up which image its start frame is, plus
    that image's settings signature and folder name, in O(1). Built once per
    tree. Images that produced no file contribute nothing.

    Every file an image row lists points at the same entry, so an image answers
    as itself under any of its names — which is what keeps a video made from an
    enhanced frame with one made from the frame before it was enhanced.
    """
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
    """The video rows that started from one of this image's files: every video
    whose link back could name it."""
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
