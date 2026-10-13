"""The sides the table of contents can be drawn over: the two shapes, and both.

A Fun Time session plays portrait media on one screen and landscape on the
other, so every folder is looked at from one shape or the other. On its own this
app has one screen, where either shape fits, so the list can also be drawn once
over the whole library — the side a mixed slideshow is started from.

These words are what a tree key is built from, so they are data the same way a
collection key is: stored expansions, bookmarks and navigation history are written
with them, and a changed value would orphan every one.
"""
from __future__ import annotations

PORTRAIT = "portrait"
LANDSCAPE = "landscape"
BOTH = "both"
ORIENTATIONS = (PORTRAIT, LANDSCAPE)
SIDES = (*ORIENTATIONS, BOTH)
SIDE_LABELS = {PORTRAIT: "Portrait", LANDSCAPE: "Landscape", BOTH: "Both"}


def orientation_of_size(width: int, height: int) -> str:
    return PORTRAIT if height > width else LANDSCAPE


def side_holds(side: str | None, orientation: str) -> bool:
    """Whether media of *orientation* belongs on *side* — every shape for Both,
    and for no side at all (``None``, where nothing is narrowing)."""
    return side is None or side in (BOTH, orientation)
