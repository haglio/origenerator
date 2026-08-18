"""Portrait / Landscape sub-shelves: one special folder, split by shape.

The special folders (Recents, Favorites, Experiments) collect generations of
every shape at once, and a mixed set has no one region to play on — a hosting
Fun Time session shows portrait media on the portrait region and landscape on
the landscape one, so "slideshow of Recents" was a routing guess that was
wrong for half the items.  Each shelf therefore breaks down into a Portrait
and a Landscape subfolder: the same listing, filtered by each item's own
shape, so what a subfolder plays is homogeneous and lands on its region.

The shape is read from the item's stored thumbnail (a cheap header read that
preserves the media's aspect), falling back to the media file itself for an
image with no thumbnail.  An item whose shape cannot be read at all files
under Landscape, the roomier region — the same default the region routing
uses for an unmeasurable set.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from origenerator import gallery
from origenerator.config import COMFYUI_OUTPUT_DIR

PORTRAIT = "portrait"
LANDSCAPE = "landscape"
ORIENTATIONS = (PORTRAIT, LANDSCAPE)
ORIENTATION_LABELS = {PORTRAIT: "Portrait", LANDSCAPE: "Landscape"}

_SEPARATOR = "::"


def oriented_key(base_key: str, orientation: str) -> str:
    """The tree key of *base_key*'s *orientation* subfolder."""
    return f"{base_key}{_SEPARATOR}{orientation}"


def split_key(key: str | None) -> tuple[str | None, str | None]:
    """``(base_key, orientation)`` — orientation ``None`` for a plain key."""
    if not key:
        return key, None
    base, _, orientation = key.partition(_SEPARATOR)
    return (base, orientation) if orientation in ORIENTATIONS else (key, None)


def row_orientation(row: dict) -> str:
    """Which region *row*'s media belongs on, by its own shape."""
    for candidate in _probe_candidates(row):
        try:
            with Image.open(candidate) as image:
                width, height = image.size
            return PORTRAIT if height > width else LANDSCAPE
        except (OSError, ValueError):
            continue
    return LANDSCAPE


def _probe_candidates(row: dict) -> list[Path]:
    candidates: list[Path] = []
    thumb = row.get("thumbnail_path")
    if thumb:
        candidates.append(Path(thumb))
    resolved = gallery.resolve_preview(row, COMFYUI_OUTPUT_DIR)
    if resolved is not None and resolved[1] == "image":
        candidates.append(Path(resolved[0]))
    return candidates


def filter_rows(rows, orientation: str | None) -> list[dict]:
    """*rows* narrowed to *orientation* — or as given, for no orientation."""
    if orientation is None:
        return list(rows)
    return [row for row in rows if row_orientation(row) == orientation]
