from __future__ import annotations

import math
from pathlib import Path

from PIL import Image

from origenerator.config import COMFYUI_INPUT_DIR, COMFYUI_TEMP_DIR, OUTPUT_PLACES
from origenerator.file_refs import reference_path

TARGET_MEGAPIXELS = 0.4
RESOLUTION_STEPS = 16

def scale_to_total_pixels(
    src_width: int, src_height: int, megapixels: float = TARGET_MEGAPIXELS,
) -> tuple[int, int]:
    """Replicates ComfyUI's ImageScaleToTotalPixels, whose banker's rounding and /16 stride the in-graph size follows, with a floor of one stride."""
    total = megapixels * 1024 * 1024
    scale = math.sqrt(total / (src_width * src_height))
    width = round(src_width * scale / RESOLUTION_STEPS) * RESOLUTION_STEPS
    height = round(src_height * scale / RESOLUTION_STEPS) * RESOLUTION_STEPS
    return max(RESOLUTION_STEPS, width), max(RESOLUTION_STEPS, height)


def resolve_input_image_path(input_image: str | None) -> Path | None:
    return reference_path(input_image, places=OUTPUT_PLACES,
                          input_dir=COMFYUI_INPUT_DIR, temp_dir=COMFYUI_TEMP_DIR)


SIZE_KEYS = ("width", "height")


def without_an_explicit_size(params: dict, workflow) -> dict:
    if not workflow.derives_size_from_input:
        return dict(params)
    return {key: value for key, value in params.items() if key not in SIZE_KEYS}


def override_size(params: dict) -> tuple[int, int] | None:
    try:
        width, height = int(params["width"]), int(params["height"])
    except (KeyError, TypeError, ValueError):
        return None
    return (width, height) if width > 0 and height > 0 else None


def measure_image_size(input_image: str | None) -> tuple[int, int] | None:
    path = resolve_input_image_path(input_image)
    if path is None:
        return None
    try:
        with Image.open(path) as img:
            return img.size
    except (OSError, ValueError):
        return None


def measure_derived_size(
    input_image: str | None, megapixels: float = TARGET_MEGAPIXELS,
) -> tuple[int, int] | None:
    path = resolve_input_image_path(input_image)
    if path is None:
        return None
    try:
        with Image.open(path) as img:
            return scale_to_total_pixels(*img.size, megapixels=megapixels)
    except (OSError, ValueError):
        return None
