from __future__ import annotations

from PyQt6.QtCore import QPoint
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
    return box, [tile for tile, in_trash in tiles if in_trash]


def _top_left_in(box, tile):
    return tile.mapTo(box, QPoint())


def test_the_items_in_the_trash_sit_side_by_side_in_their_box_when_there_is_room(qtbot):
    box, trashed = _laid_out(qtbot, 900, kept=1, trashed=3)

    assert len({_top_left_in(box, tile).y() for tile in trashed}) == 1


def test_a_box_too_narrow_for_its_items_grows_down_to_hold_every_one(qtbot):
    box, trashed = _laid_out(qtbot, 260, kept=1, trashed=3)

    assert all(_top_left_in(box, tile).y() + _TILE <= box.height() for tile in trashed)
    assert box.width() <= 260
