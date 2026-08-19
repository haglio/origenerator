"""The card that opens a folder's prompt for a rewrite."""

from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from origenerator.gui import grid_card
from origenerator.gui.folder_request_tile import FolderRequestTile
from origenerator.gui.reroll_tile import RerollTile


def _click(tile):
    QApplication.sendEvent(tile, QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPoint(10, 10).toPointF(),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    ))


def test_the_card_says_what_it_keeps_and_what_it_changes(qtbot):
    tile = FolderRequestTile()
    qtbot.addWidget(tile)
    # The re-roll card next door changes the seed; this one keeps it, and the
    # caption is the only place that difference is stated.
    assert tile._caption.text() == "Request (same seeds)"
    assert "seed" in tile.toolTip()


def test_clicking_the_card_asks_for_the_rewrite(qtbot):
    tile = FolderRequestTile()
    qtbot.addWidget(tile)
    with qtbot.waitSignal(tile.clicked):
        _click(tile)


def test_the_card_is_the_same_size_as_the_one_beside_it(qtbot):
    # They stand shoulder to shoulder in the same flow as the thumbnails, so a
    # card of its own size would break the row.
    request, reroll = FolderRequestTile(), RerollTile()
    qtbot.addWidget(request)
    qtbot.addWidget(reroll)
    assert request.size() == reroll.size()
    assert (request.width(), request.height()) == grid_card.card_size()
