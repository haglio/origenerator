from __future__ import annotations

from collections.abc import Callable, Iterable

from shared_ui.orientation import LANDSCAPE, PORTRAIT
from shared_ui.orientation import ORIENTATIONS as SHAPES

BOTH = "both"
SHAPES_AND_BOTH = (*SHAPES, BOTH)
SHAPE_LABELS = {PORTRAIT: "Portrait", LANDSCAPE: "Landscape", BOTH: "Both"}
SEPARATE = SHAPES
TOGETHER = (BOTH,)

_EVERY_SHAPE = frozenset(SHAPES)
_SHAPES_ON = {
    PORTRAIT: frozenset({PORTRAIT}),
    LANDSCAPE: frozenset({LANDSCAPE}),
    BOTH: _EVERY_SHAPE,
    None: _EVERY_SHAPE,
}


def shape_holds(shape: str | None, of_item: str | None) -> bool:
    return of_item in _SHAPES_ON[shape]


def shape_covers(shape: str | None, other: str | None) -> bool:
    return _SHAPES_ON[other] <= _SHAPES_ON[shape]


def the_one_shape_on(shape: str | None) -> str | None:
    shapes = _SHAPES_ON[shape]
    return next(iter(shapes)) if len(shapes) == 1 else None


def the_shape_of(shapes: Iterable[str]) -> str | None:
    held = frozenset(shapes)
    return next((shape for shape in SHAPES_AND_BOTH if _SHAPES_ON[shape] == held), None)


def shape_holding(of_item: str | None, shapes: Iterable[str]) -> str | None:
    return next((shape for shape in shapes if shape_holds(shape, of_item)), None)


def on_shape(things: Iterable, shape: str | None, shape_of: Callable) -> list:
    shapes = _SHAPES_ON[shape]
    if shapes == _EVERY_SHAPE:
        return list(things)
    return [thing for thing in things if shape_of(thing) in shapes]
