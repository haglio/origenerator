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

from collections.abc import Callable, Iterable

from shared_ui.orientation import LANDSCAPE, ORIENTATIONS, PORTRAIT

BOTH = "both"
SIDES = (*ORIENTATIONS, BOTH)
SIDE_LABELS = {PORTRAIT: "Portrait", LANDSCAPE: "Landscape", BOTH: "Both"}
SEPARATE = ORIENTATIONS
TOGETHER = (BOTH,)

_EVERY_SHAPE = frozenset(ORIENTATIONS)
_SHAPES_ON = {
    PORTRAIT: frozenset({PORTRAIT}),
    LANDSCAPE: frozenset({LANDSCAPE}),
    BOTH: _EVERY_SHAPE,
    None: _EVERY_SHAPE,  # no side at all, where nothing is narrowing
}


def side_holds(side: str | None, orientation: str | None) -> bool:
    return orientation in _SHAPES_ON[side]


def side_covers(side: str | None, other: str | None) -> bool:
    return _SHAPES_ON[other] <= _SHAPES_ON[side]


def the_one_shape_on(side: str | None) -> str | None:
    shapes = _SHAPES_ON[side]
    return next(iter(shapes)) if len(shapes) == 1 else None


def side_holding(orientation: str | None, sides: Iterable[str]) -> str | None:
    return next((side for side in sides if side_holds(side, orientation)), None)


def on_side(things: Iterable, side: str | None, orientation_of: Callable) -> list:
    shapes = _SHAPES_ON[side]
    if shapes == _EVERY_SHAPE:
        return list(things)
    return [thing for thing in things if orientation_of(thing) in shapes]
