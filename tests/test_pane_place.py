"""Where the browser pane stands, and the scroll that brings a picture into view.

No gallery here: a scroll area with a tall column of plain widgets is all these
answers need, and it is the only place the arithmetic can be read on its own.
The gallery's own tests say what a person sees -- the picture picked, in view,
clear of the pane's edge -- and cannot pin the margin to the pixel, because the
pane's furniture takes a few of them when a page lands and a scroll bar appears.
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from origenerator.gui.pane_place import REVEAL_MARGIN, bring_into_view

_TILE = 100
_VIEWPORT = 500


@pytest.fixture
def pane(qtbot):
    """A scroll area of twenty stacked 100-tall widgets, 500 of them in view."""
    scroll = QScrollArea()
    content = QWidget()
    column = QVBoxLayout(content)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(0)
    tiles = []
    for _ in range(20):
        tile = QWidget()
        tile.setFixedSize(200, _TILE)
        column.addWidget(tile)
        tiles.append(tile)
    scroll.setWidget(content)
    scroll.setWidgetResizable(True)
    scroll.setVerticalScrollBarPolicy(scroll.verticalScrollBarPolicy())
    qtbot.addWidget(scroll)
    scroll.resize(230, _VIEWPORT)
    scroll.show()
    qtbot.waitExposed(scroll)
    return scroll, tiles


def _room_over(scroll, tile) -> int:
    return tile.mapTo(scroll.viewport(), QPoint(0, 0)).y()


def _room_under(scroll, tile) -> int:
    return (scroll.viewport().rect().height()
            - _room_over(scroll, tile) - tile.size().height())


def test_a_picture_under_the_view_comes_up_with_the_margin_under_it(pane, qtbot):
    scroll, tiles = pane
    assert scroll.verticalScrollBar().value() == 0

    bring_into_view(scroll, tiles[15])

    assert _room_under(scroll, tiles[15]) == REVEAL_MARGIN


def test_a_picture_over_the_view_comes_down_with_the_margin_over_it(pane, qtbot):
    scroll, tiles = pane
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())

    bring_into_view(scroll, tiles[2])

    assert _room_over(scroll, tiles[2]) == REVEAL_MARGIN


def test_a_picture_already_clear_of_both_edges_is_left_where_it_is(pane, qtbot):
    scroll, tiles = pane
    scroll.verticalScrollBar().setValue(200)

    bring_into_view(scroll, tiles[3])

    assert scroll.verticalScrollBar().value() == 200


def test_a_pane_too_short_for_the_margins_shares_out_what_room_it_has(pane, qtbot):
    scroll, tiles = pane
    scroll.resize(230, _TILE + 20)
    qtbot.wait(1)

    bring_into_view(scroll, tiles[15])

    half_of_what_is_left = (scroll.viewport().rect().height() - _TILE) // 2
    assert half_of_what_is_left < REVEAL_MARGIN
    assert _room_over(scroll, tiles[15]) == half_of_what_is_left
    assert _room_under(scroll, tiles[15]) == half_of_what_is_left
