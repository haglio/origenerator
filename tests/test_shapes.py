"""What each shape of the folder list holds, said in one place.

The list is a shape per shape (Separate) or one shape of both shapes (Together).
Every part of the app that narrows something to a shape asks
:mod:`origenerator.gallery.shapes`; the source checks at the bottom keep it the
only place that says what a shape holds, since a comparison written by hand when
there were two shapes is what left every queued item off Together's Latest.
"""
from __future__ import annotations

import ast
from pathlib import Path

from origenerator.gallery.shapes import (
    BOTH,
    LANDSCAPE,
    PORTRAIT,
    SEPARATE,
    SHAPES,
    SHAPES_AND_BOTH,
    TOGETHER,
    on_shape,
    shape_covers,
    shape_holding,
    shape_holds,
    the_one_shape_on,
    the_shape_of,
)


def test_each_shapes_side_holds_that_shape_and_both_holds_each():
    holds = {shape: {of_item for of_item in SHAPES if shape_holds(shape, of_item)}
             for shape in (*SHAPES_AND_BOTH, None)}

    assert holds == {PORTRAIT: {PORTRAIT}, LANDSCAPE: {LANDSCAPE},
                     BOTH: {PORTRAIT, LANDSCAPE}, None: {PORTRAIT, LANDSCAPE}}


def test_a_shapes_side_holds_that_one_shape_and_both_holds_no_one_shape():
    assert [the_one_shape_on(shape) for shape in (*SHAPES_AND_BOTH, None)] == [
        PORTRAIT, LANDSCAPE, None, None]


def test_a_set_of_shapes_belongs_to_the_side_that_holds_exactly_those_shapes():
    assert [the_shape_of(shapes) for shapes in (
        [PORTRAIT], [LANDSCAPE, LANDSCAPE], [LANDSCAPE, PORTRAIT], [])] == [
        PORTRAIT, LANDSCAPE, BOTH, None]


def test_the_lists_two_arrangements_each_draw_every_shape_once():
    for arrangement in (SEPARATE, TOGETHER):
        assert sorted(of_item for shape in arrangement for of_item in SHAPES
                      if shape_holds(shape, of_item)) == sorted(SHAPES)


def test_narrowing_to_a_side_keeps_what_it_holds_in_order():
    things = [("one", PORTRAIT), ("two", LANDSCAPE), ("three", PORTRAIT)]

    assert on_shape(things, PORTRAIT, lambda thing: thing[1]) == [
        ("one", PORTRAIT), ("three", PORTRAIT)]
    assert on_shape(things, LANDSCAPE, lambda thing: thing[1]) == [("two", LANDSCAPE)]


def test_a_side_holding_every_shape_narrows_without_measuring_a_thing():
    """Reading a shape can mean opening a file, and Both is drawn over the
    whole library."""
    def never(_thing):
        raise AssertionError("a shape was read")

    for shape in (BOTH, None):
        assert on_shape(iter(["one", "two"]), shape, never) == ["one", "two"]


def test_a_side_covers_each_side_whose_every_shape_it_holds():
    """What a folder composed on one shape is drawn on: there, and on Both."""
    covering = {(shape, other) for shape in SHAPES_AND_BOTH for other in SHAPES_AND_BOTH
                if shape_covers(shape, other)}

    assert covering == {(PORTRAIT, PORTRAIT), (LANDSCAPE, LANDSCAPE),
                        (BOTH, PORTRAIT), (BOTH, LANDSCAPE), (BOTH, BOTH)}


def test_a_shape_is_found_on_whichever_drawn_side_holds_it():
    assert shape_holding(PORTRAIT, SEPARATE) == PORTRAIT
    assert shape_holding(LANDSCAPE, SEPARATE) == LANDSCAPE
    assert shape_holding(PORTRAIT, TOGETHER) == BOTH
    assert shape_holding(LANDSCAPE, TOGETHER) == BOTH


def test_a_shape_nothing_asked_for_is_on_no_list():
    assert shape_holding(None, SEPARATE) is None
    assert shape_holding(None, TOGETHER) is None


_PACKAGE = Path(__file__).resolve().parents[1] / "origenerator"
_SHAPES_MODULE = _PACKAGE / "gallery" / "shapes.py"


def _names(operand):
    for node in ast.walk(operand):
        if isinstance(node, ast.Name):
            yield node.id
        elif isinstance(node, ast.Attribute):
            yield node.attr


def _words(operand) -> set[str]:
    return {word for name in _names(operand) for word in name.lower().split("_") if word}


def _comparisons_outside_the_shapes_module():
    for path in sorted(_PACKAGE.rglob("*.py")):
        if path == _SHAPES_MODULE:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Compare):
                yield (f"{path.relative_to(_PACKAGE.parent).as_posix()}:{node.lineno}",
                       [node.left, *node.comparators])


def _names_both(operand) -> bool:
    return (any(name in ("BOTH", "_BOTH") for name in _names(operand))
            or any(isinstance(node, ast.Constant) and node.value == "both"
                   for node in ast.walk(operand)))


def test_only_the_shapes_module_says_what_both_holds():
    """Both is the one shape holding more than one shape, so code elsewhere that
    tests for it is saying by hand what Both holds: a second copy of the rule."""
    assert [where for where, operands in _comparisons_outside_the_shapes_module()
            if any(_names_both(operand) for operand in operands)] == []
