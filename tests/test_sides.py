"""What each side of the folder list holds, said in one place.

The list is a side per shape (Separate) or one side of both shapes (Together).
Every part of the app that narrows something to a side asks
:mod:`origenerator.gallery.sides`; the source checks at the bottom keep it the
only place that says what a side holds, since a comparison written by hand when
there were two sides is what left every queued item off Together's Latest.
"""
from __future__ import annotations

import ast
from pathlib import Path

from origenerator.gallery.sides import (
    BOTH,
    LANDSCAPE,
    ORIENTATIONS,
    PORTRAIT,
    SEPARATE,
    SIDES,
    TOGETHER,
    on_side,
    side_covers,
    side_holding,
    side_holds,
)


def test_each_shapes_side_holds_that_shape_and_both_holds_each():
    holds = {side: {shape for shape in ORIENTATIONS if side_holds(side, shape)}
             for side in (*SIDES, None)}

    assert holds == {PORTRAIT: {PORTRAIT}, LANDSCAPE: {LANDSCAPE},
                     BOTH: {PORTRAIT, LANDSCAPE}, None: {PORTRAIT, LANDSCAPE}}


def test_the_lists_two_arrangements_each_draw_every_shape_once():
    for arrangement in (SEPARATE, TOGETHER):
        assert sorted(shape for side in arrangement for shape in ORIENTATIONS
                      if side_holds(side, shape)) == sorted(ORIENTATIONS)


def test_narrowing_to_a_side_keeps_what_it_holds_in_order():
    things = [("one", PORTRAIT), ("two", LANDSCAPE), ("three", PORTRAIT)]

    assert on_side(things, PORTRAIT, lambda thing: thing[1]) == [
        ("one", PORTRAIT), ("three", PORTRAIT)]
    assert on_side(things, LANDSCAPE, lambda thing: thing[1]) == [("two", LANDSCAPE)]


def test_a_side_holding_every_shape_narrows_without_measuring_a_thing():
    """Reading a shape can mean opening a file, and Both is drawn over the
    whole library."""
    def never(_thing):
        raise AssertionError("a shape was read")

    for side in (BOTH, None):
        assert on_side(iter(["one", "two"]), side, never) == ["one", "two"]


def test_a_side_covers_each_side_whose_every_shape_it_holds():
    """What a folder composed on one side is drawn on: there, and on Both."""
    covering = {(side, other) for side in SIDES for other in SIDES
                if side_covers(side, other)}

    assert covering == {(PORTRAIT, PORTRAIT), (LANDSCAPE, LANDSCAPE),
                        (BOTH, PORTRAIT), (BOTH, LANDSCAPE), (BOTH, BOTH)}


def test_a_shape_is_found_on_whichever_drawn_side_holds_it():
    assert side_holding(PORTRAIT, SEPARATE) == PORTRAIT
    assert side_holding(LANDSCAPE, SEPARATE) == LANDSCAPE
    assert side_holding(PORTRAIT, TOGETHER) == BOTH
    assert side_holding(LANDSCAPE, TOGETHER) == BOTH


def test_a_shape_nothing_asked_for_is_on_no_side():
    assert side_holding(None, SEPARATE) is None
    assert side_holding(None, TOGETHER) is None


_PACKAGE = Path(__file__).resolve().parents[1] / "origenerator"
_SIDES_MODULE = _PACKAGE / "gallery" / "sides.py"
_SIDE_WORDS = {"side", "sides"}
_SHAPE_WORDS = {"orientation", "orientations", "shape", "shapes"}


def _names(operand):
    for node in ast.walk(operand):
        if isinstance(node, ast.Name):
            yield node.id
        elif isinstance(node, ast.Attribute):
            yield node.attr


def _words(operand) -> set[str]:
    return {word for name in _names(operand) for word in name.lower().split("_") if word}


def _comparisons_outside_the_sides_module():
    for path in sorted(_PACKAGE.rglob("*.py")):
        if path == _SIDES_MODULE:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Compare):
                yield (f"{path.relative_to(_PACKAGE.parent).as_posix()}:{node.lineno}",
                       [node.left, *node.comparators])


def _names_both(operand) -> bool:
    return (any(name in ("BOTH", "_BOTH") for name in _names(operand))
            or any(isinstance(node, ast.Constant) and node.value == "both"
                   for node in ast.walk(operand)))


def test_only_the_sides_module_says_what_both_holds():
    """Both is the one side holding more than one shape, so code elsewhere that
    tests for it is saying by hand what Both holds: a second copy of the rule."""
    assert [where for where, operands in _comparisons_outside_the_sides_module()
            if any(_names_both(operand) for operand in operands)] == []


def test_no_side_is_compared_with_a_shape():
    """A side holds shapes and is never one. ``item.orientation == side`` read
    right while every side was a shape, and left Together's Latest empty."""
    def pairs_a_side_with_a_shape(operands) -> bool:
        words = [_words(operand) for operand in operands]
        return any(mine & _SIDE_WORDS and theirs & _SHAPE_WORDS
                   for i, mine in enumerate(words)
                   for j, theirs in enumerate(words) if i != j)

    assert [where for where, operands in _comparisons_outside_the_sides_module()
            if pairs_a_side_with_a_shape(operands)] == []
