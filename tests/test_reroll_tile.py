from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QApplication

from origenerator.gui.browser_pane import BrowserScrollArea
from origenerator.gui.reroll_tile import RerollTile
from origenerator.gui.stylesheet import build_stylesheet


def test_the_tile_offers_a_new_random_seed(qtbot):
    tile = RerollTile()
    qtbot.addWidget(tile)
    assert tile._glyph.text() == "+"
    assert tile._caption.text() == "New (random seed)"
    assert tile.isEnabled()


def test_a_click_asks_for_a_new_seed(qtbot):
    tile = RerollTile()
    qtbot.addWidget(tile)
    clicks = []
    tile.add_requested.connect(lambda: clicks.append(True))
    qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)
    assert clicks == [True]


def test_a_folder_already_making_one_grays_its_plus_out_and_says_why(qtbot):
    tile = RerollTile(making_one=True)
    qtbot.addWidget(tile)

    assert not tile.isEnabled()
    assert tile.toolTip() == "This folder is already making one"


def test_a_grayed_plus_starts_nothing_on_a_click(qtbot):
    tile = RerollTile(making_one=True)
    qtbot.addWidget(tile)
    clicks = []
    tile.add_requested.connect(lambda: clicks.append(True))

    qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)

    assert clicks == []


def test_a_press_on_a_grayed_plus_does_not_put_the_picked_pictures_down(qtbot):
    # The pane takes a press nothing kept for a press on the space between the
    # pictures, and answers it by putting the picked ones down.
    pane = BrowserScrollArea()
    qtbot.addWidget(pane)
    tile = RerollTile(making_one=True)
    pane.setWidget(tile)
    let_go = []
    pane.background_clicked.connect(lambda: let_go.append(True))

    qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)

    assert let_go == []


def _ink(label):
    """The color a label's text is painted in, in the state it is in."""
    palette = label.palette()
    return palette.color(palette.currentColorGroup(), QPalette.ColorRole.WindowText)


def test_a_grayed_plus_is_painted_darker_than_a_live_one(qtbot):
    app = QApplication.instance()
    prior = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        live, grayed = RerollTile(), RerollTile(making_one=True)
        for tile in (live, grayed):
            qtbot.addWidget(tile)
            tile.ensurePolished()

        assert _ink(grayed._glyph).lightness() < _ink(live._glyph).lightness()
        assert _ink(grayed._caption).lightness() < _ink(live._caption).lightness()
    finally:
        app.setStyleSheet(prior)
