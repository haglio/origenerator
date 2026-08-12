"""Deriving an input-image workflow's output size from that image.

Every workflow that takes an ``input_image`` keeps the image's aspect ratio at
a fixed pixel budget rather than a hardcoded resolution — 0.4 MP for the video
workflows, the SDXL budget for the pose-transfer still. The WAN 2.2 pair and
the pose transfer do this in-graph (``ImageScaleToTotalPixels`` on a /16
stride, then ``GetImageSize``); ATI can't (its ``WanTrackToVideo`` needs the
integer size *and* a track whose coordinates share that space, both built
app-side). This module is the app-side twin of that in-graph scaling: it
replicates ``ImageScaleToTotalPixels`` exactly, so the size it computes for an
image equals what the in-graph path produces for the same image.

It's used two ways: ATI builds its payload size from it, and the Generate form
shows every deriving workflow's size in a locked Dimensions field (measuring
the picked image here rather than waiting for ComfyUI to do it in-graph).

Kept free of any workflow/Qt import so both callers share one implementation.
"""

import math
from pathlib import Path

from PIL import Image

from origenerator.config import COMFYUI_INPUT_DIR, COMFYUI_OUTPUT_DIR

# The default pixel budget (what the video workflows scale to in-graph) and the
# shared stride, matched here so an image yields the same proportions the graph
# will produce. A workflow on a different budget (SDXL's ~1 MP) passes its own.
TARGET_MEGAPIXELS = 0.4
RESOLUTION_STEPS = 16

# ComfyUI's LoadImage annotates a non-input source as "name [output|input|temp]"
# (the same convention gallery/signatures.py strips); an unannotated value names
# a file in the input dir.
_OUTPUT_TAG = "[output]"
_INPUT_TAG = "[input]"


def scale_to_total_pixels(
    src_width: int, src_height: int, megapixels: float = TARGET_MEGAPIXELS,
) -> tuple[int, int]:
    """The output size for a ``src_width``×``src_height`` image, replicating
    ComfyUI's ``ImageScaleToTotalPixels`` (``megapixels``, /16 stride) exactly
    so the size matches what the in-graph derivation produces for the same image.

    Mirrors the node's ``round(dim * sqrt(total / area) / steps) * steps`` (with
    Python's banker's rounding, as ComfyUI uses). The only addition is a floor at
    one stride, so a degenerate aspect ratio can't round a side to zero and crash
    the track node — a no-op for any realistic image.
    """
    total = megapixels * 1024 * 1024
    scale = math.sqrt(total / (src_width * src_height))
    width = round(src_width * scale / RESOLUTION_STEPS) * RESOLUTION_STEPS
    height = round(src_height * scale / RESOLUTION_STEPS) * RESOLUTION_STEPS
    return max(RESOLUTION_STEPS, width), max(RESOLUTION_STEPS, height)


def resolve_input_image_path(input_image: str | None) -> Path | None:
    """The on-disk file a LoadImage value names, or ``None`` when it's empty or
    absent. A ``"name [output]"`` value lives under the ComfyUI output dir and an
    ``"[input]"`` (or unannotated) one under the input dir — matching how
    ComfyUI's LoadImage routes the reference. An absolute path is taken as-is."""
    ref = (input_image or "").strip()
    if not ref:
        return None
    stem, _, tag = ref.rpartition(" ")
    if stem and tag == _OUTPUT_TAG:
        path = COMFYUI_OUTPUT_DIR / stem
    elif stem and tag == _INPUT_TAG:
        path = COMFYUI_INPUT_DIR / stem
    else:
        path = Path(ref)
        if not path.is_absolute():
            path = COMFYUI_INPUT_DIR / ref
    return path if path.is_file() else None


def override_size(params: dict) -> tuple[int, int] | None:
    """The explicit ``(width, height)`` the user set by unlocking the derived
    Dimensions field, or ``None`` when the size should be derived — the usual
    case, where the fields stay locked and ``params`` carry no width/height.

    Both must be present and positive; a lone or non-numeric value is ignored as
    if absent, so a half-filled or malformed override falls back to derivation
    rather than feeding a bad size into the graph.
    """
    try:
        width, height = int(params["width"]), int(params["height"])
    except (KeyError, TypeError, ValueError):
        return None
    return (width, height) if width > 0 and height > 0 else None


def measure_derived_size(
    input_image: str | None, megapixels: float = TARGET_MEGAPIXELS,
) -> tuple[int, int] | None:
    """The output size derived from ``input_image``: its file measured and scaled
    to the ``megapixels`` budget (:func:`scale_to_total_pixels`), or ``None``
    when the image is missing or unreadable — so a caller can fall back (ATI to
    its reference frame, the form to showing no size) rather than crash.
    """
    path = resolve_input_image_path(input_image)
    if path is None:
        return None
    try:
        with Image.open(path) as img:
            return scale_to_total_pixels(*img.size, megapixels=megapixels)
    except (OSError, ValueError):
        return None
