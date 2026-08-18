"""Linking an image-conditioned video to the image generation that seeded it.

An i2v row references its start frame by filename; these helpers match that back
to the image generation that produced the file, index every image by the
configuration that made it (so a video can find its frame's settings signature and
folder label in O(1)), and invert the relation to list the videos an image was
animated into. The bridge between the Images and Videos trees.
"""

from dataclasses import dataclass

from origenerator.gallery.signatures import (
    _frame_name,
    canonical_settings,
    parse_params,
    settings_signature,
)
from origenerator.gallery.labels import settings_label
from origenerator.gallery.output import row_output_files


@dataclass
class _ImageConfig:
    """How the gallery keys and names an image used as an i2v's start frame."""

    prompt_id: str  # which picture it is — what the source-image tier groups on
    signature: str  # the image's settings signature — what names it below
    label: str      # the image's folder label — names the video's source-image folder


def source_image_id_for(input_image: str | None, image_rows: list[dict]) -> str | None:
    """The prompt_id of the image generation an ``input_image`` value names.

    Image-to-video rows reference their start frame by filename; match it to an
    image generation by basename (through any ``[output]`` annotation). ``None``
    when the value is empty or none of ``image_rows`` produced a file with that
    name. Takes the bare value so the Generate tab — which has the field, not a
    stored row — can resolve it the same way :func:`find_source_image_id` does.
    """
    if not input_image:
        return None
    target = _frame_name(input_image)
    for image in image_rows:
        for f in row_output_files(image):
            if _frame_name(f.get("filename")) == target:
                return image["prompt_id"]
    return None


def find_source_image_id(row: dict, image_rows: list[dict]) -> str | None:
    """Return the prompt_id of the image used as this row's ``input_image``.

    Image-to-video rows reference their start frame by filename; match it to an
    image generation by basename. Returns ``None`` when the row has no input
    image or none of ``image_rows`` produced a file with that name.
    """
    return source_image_id_for(
        parse_params(row.get("params_json")).get("input_image"), image_rows
    )


def build_image_config_index(image_rows: list[dict]) -> dict[str, _ImageConfig]:
    """Map each image's output filename to the generation that produced it.

    Keyed by output basename (lowercased, matching how an ``input_image`` value
    resolves), so an i2v row can look up which picture its start frame is, plus
    that picture's settings signature and folder label, in O(1). Built once per
    tree. Images that produced no file contribute nothing.

    Every file an image row lists points at the same entry, so a picture answers
    as itself under any of its names — which is what keeps a video made from an
    enhanced frame with one made from the frame before it was enhanced.
    """
    index: dict[str, _ImageConfig] = {}
    for image in image_rows:
        workflow_name = image.get("workflow_name")
        params = parse_params(image.get("params_json"))
        config = _ImageConfig(
            prompt_id=image.get("prompt_id") or "",
            signature=settings_signature(workflow_name, image.get("params_json"),
                                         workflow_version=image.get("workflow_version")),
            label=settings_label(canonical_settings(workflow_name, params)),
        )
        for f in row_output_files(image):
            name = _frame_name(f.get("filename"))
            if name:
                index.setdefault(name, config)
    return index


def videos_from_source_image(image_row: dict, video_rows: list[dict]) -> list[dict]:
    """The video rows that used this image as their input — the videos it was
    animated into. The inverse of :func:`find_source_image_id`, for showing an
    image the animations made from it."""
    image_id = image_row.get("prompt_id")
    if image_id is None:
        return []
    return [v for v in video_rows if find_source_image_id(v, [image_row]) == image_id]
