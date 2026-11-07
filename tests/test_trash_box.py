from __future__ import annotations

from itertools import groupby

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QImage, QRegion
from PyQt6.QtWidgets import QApplication, QWidget

from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.trash_box import place_tiles

_TILE = 96


def _tile():
    tile = QWidget()
    tile.setFixedSize(_TILE, _TILE)
    return tile


def _laid_out(qtbot, width, kept, trashed):
    host = QWidget()
    qtbot.addWidget(host)
    flow = FlowLayout(host, spacing=8)
    tiles = [(_tile(), False) for _ in range(kept)] + [(_tile(), True) for _ in range(trashed)]
    box = place_tiles(tiles, flow.addWidget)
    host.resize(width, flow.heightForWidth(width))
    host.show()
    QApplication.processEvents()
    return box, [tile for tile, _in_trash in tiles]


def _top_left_in(box, tile):
    return tile.mapTo(box, QPoint())


def test_the_items_in_the_trash_sit_side_by_side_in_their_box_when_there_is_room(qtbot):
    box, tiles = _laid_out(qtbot, 900, kept=1, trashed=3)

    assert len({_top_left_in(box, tile).y() for tile in tiles[1:]}) == 1


def test_the_items_in_the_trash_line_up_with_the_items_beside_their_box(qtbot):
    box, tiles = _laid_out(qtbot, 900, kept=2, trashed=2)

    host = box.parentWidget()
    assert len({tile.mapTo(host, QPoint()).y() for tile in tiles}) == 1


def test_the_box_says_in_the_trash_under_its_items(qtbot):
    box, tiles = _laid_out(qtbot, 900, kept=0, trashed=2)

    assert box.label.text() == "in the Trash"
    assert box.label.mapTo(box, QPoint()).y() >= _top_left_in(box, tiles[0]).y() + _TILE


def _top_edge_runs(box):
    image = QImage(box.size(), QImage.Format.Format_ARGB32)
    image.fill(0)
    box.render(image, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    inked = [image.pixelColor(x, 0).alpha() > 0 for x in range(box.width())]
    return [len(list(run)) for _inked, run in groupby(inked)][2:-2]


def test_the_box_s_edge_is_drawn_in_dashes_ten_pixels_long(qtbot):
    box, _tiles = _laid_out(qtbot, 900, kept=0, trashed=4)

    assert set(_top_edge_runs(box)) == {10}


def test_a_box_too_narrow_for_its_items_grows_down_to_hold_every_one(qtbot):
    box, tiles = _laid_out(qtbot, 260, kept=1, trashed=3)

    assert all(_top_left_in(box, tile).y() + _TILE <= box.height() for tile in tiles[1:])
    assert box.width() <= 260


def test_the_items_beside_the_box_keep_their_place_at_the_left_edge(qtbot):
    box, tiles = _laid_out(qtbot, 900, kept=2, trashed=1)

    assert tiles[0].mapTo(box.parentWidget(), QPoint()).x() == 0
