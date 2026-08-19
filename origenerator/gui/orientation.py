"""Two copies of the whole table of contents, one per shape.

A set of mixed-shape media has no one screen to play on.  A hosting Fun Time
session shows portrait media on the portrait region and landscape on the
landscape one, so "slideshow of this folder" was a routing guess that was wrong
for half the items in it — and standalone the same set is routed by a majority
vote, which letterboxes the losing half.  A mixed show is a design space this
app does not want to be in at all.

So the tree has two roots, Portrait and Landscape, and each carries the ENTIRE
table of contents — every shelf, the All row, the media → workflow → model →
LoRA → settings hierarchy, and the folders the user composed — built from that
shape's rows alone.  Whatever you are standing on is one shape by construction,
so its slideshow has exactly one region to go to, and which one is read off the
key rather than measured back out of the items.

The key scheme is what carries the shape: a row's tree key is its folder's own
key with ``::portrait`` or ``::landscape`` appended (:func:`oriented_key`), and
:func:`split_key` takes it apart again.  The *folder's* key is untouched by
this — a star, a custom name, and membership of a folder the user composed all
still hang off the plain key, because those are properties of the folder rather
than of the side it is being looked at from.

The shape is read from the item's stored thumbnail (a cheap header read that
preserves the media's aspect), falling back to the media file itself for an
image with no thumbnail, and then to the size the generation asked for — which
is the only thing an in-flight row has, and without it a running portrait
generation would appear under Landscape and jump sides the moment it landed.
An item that answers none of the three files under Landscape, the roomier
region — the same default the region routing uses for an unmeasurable set.
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

# The two rows the tree is rooted on. Keyed like the synthetic shelves so no
# derived folder key can collide with one, and oriented like everything under
# them so a root comes apart under the same function every other key does.
ROOT_KEY = "__orientation__"

_SEPARATOR = "::"

# Measured shapes, by the file that answered. A rebuild re-reads every row, and
# opening a thumbnail per row per poll is a cost the tree now pays for both
# sides at once; the file a shape was read from never changes its shape, so the
# answer is kept against its path. Only successful reads are kept — a row whose
# file has not landed yet has to be asked again once it has.
_measured: dict[str, str] = {}


def oriented_key(base_key: str, orientation: str) -> str:
    """The tree key of *base_key*'s row on the *orientation* side."""
    return f"{base_key}{_SEPARATOR}{orientation}"


def split_key(key: str | None) -> tuple[str | None, str | None]:
    """``(base_key, orientation)`` — orientation ``None`` for a plain key."""
    if not key:
        return key, None
    base, _, orientation = key.partition(_SEPARATOR)
    return (base, orientation) if orientation in ORIENTATIONS else (key, None)


def base_of(key: str | None) -> str | None:
    """The folder a tree key names, with the side stripped off — what a star, a
    name and a custom folder's membership are all stored under."""
    return split_key(key)[0]


def orientation_of(key: str | None) -> str | None:
    """Which side a tree key is on (``None`` for a key naming no side)."""
    return split_key(key)[1]


def root_key(orientation: str) -> str:
    """The tree key of the *orientation* root — the row a whole side hangs off."""
    return oriented_key(ROOT_KEY, orientation)


def row_orientation(row: dict) -> str:
    """Which region *row*'s media belongs on, by its own shape."""
    for candidate in _probe_candidates(row):
        path = str(candidate)
        remembered = _measured.get(path)
        if remembered is not None:
            return remembered
        try:
            with Image.open(candidate) as image:
                width, height = image.size
        except (OSError, ValueError):
            continue
        _measured[path] = measured = PORTRAIT if height > width else LANDSCAPE
        return measured
    return requested_orientation(gallery.parse_params(row.get("params_json"))) or LANDSCAPE


def _probe_candidates(row: dict) -> list[Path]:
    candidates: list[Path] = []
    thumb = row.get("thumbnail_path")
    if thumb:
        candidates.append(Path(thumb))
    resolved = gallery.resolve_preview(row, COMFYUI_OUTPUT_DIR)
    if resolved is not None and resolved[1] == "image":
        candidates.append(Path(resolved[0]))
    return candidates


def requested_orientation(params: dict) -> str | None:
    """The shape a generation's *params* ask it to come out — ``None`` when they
    don't say.

    What a generation that has produced nothing yet is placed by: its folder
    joins the tree the moment it starts running, and it has to join on the side
    the picture will land on rather than move there once it has.
    """
    try:
        width, height = int(params["width"]), int(params["height"])
    except (KeyError, TypeError, ValueError):
        return None
    return PORTRAIT if height > width else LANDSCAPE


def filter_rows(rows, orientation: str | None) -> list[dict]:
    """*rows* narrowed to *orientation* — or as given, for no orientation."""
    if orientation is None:
        return list(rows)
    return [row for row in rows if row_orientation(row) == orientation]


def split_rows(rows) -> dict[str, list[dict]]:
    """*rows* dealt out to the two sides, each row measured once.

    What the two trees are built from. Two :func:`filter_rows` passes would
    measure every row twice, and the rebuild that calls this runs on every poll.
    """
    dealt: dict[str, list[dict]] = {orientation: [] for orientation in ORIENTATIONS}
    for row in rows:
        dealt[row_orientation(row)].append(row)
    return dealt
