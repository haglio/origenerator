from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from origenerator.gui import tile_shape
from origenerator.gui.modify_batch_tile import ModifyBatchTile
from origenerator.gui.new_tile import NewTile


def _click(tile):
    QApplication.sendEvent(tile, QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPoint(10, 10).toPointF(),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    ))


def test_the_tile_says_what_it_keeps_and_what_it_changes(qtbot):
    tile = ModifyBatchTile()
    qtbot.addWidget(tile)
    assert tile._caption.text() == "Modify batch (all seeds)"
    assert "seed" in tile.toolTip()


def test_the_tile_wears_the_familys_pencil(qtbot):
    tile = ModifyBatchTile()
    qtbot.addWidget(tile)

    assert tile._glyph.mark == "pencil", (
        "a pencil rather than a plus: the tile beside it makes another one of these, and this one "
        "writes on them")


def test_clicking_the_tile_asks_for_the_rewrite(qtbot):
    tile = ModifyBatchTile()
    qtbot.addWidget(tile)
    with qtbot.waitSignal(tile.clicked):
        _click(tile)


def test_the_tile_is_the_same_size_as_the_one_beside_it(qtbot):
    request, reroll = ModifyBatchTile(), NewTile()
    qtbot.addWidget(request)
    qtbot.addWidget(reroll)
    assert request.size() == reroll.size()
    assert (request.width(), request.height()) == tile_shape.tile_size()
