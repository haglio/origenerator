from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from origenerator.gui.gallery_pane import GalleryPaneScrollArea
from origenerator.gui.new_tile import NewTile
from origenerator.gui.stylesheet import build_stylesheet


def test_the_tile_offers_a_new_random_seed(qtbot):
    tile = NewTile()
    qtbot.addWidget(tile)
    assert tile._glyph.mark == "plus"
    assert tile._caption.text() == "New (random seed)"
    assert tile.isEnabled()


def test_a_click_asks_for_a_new_seed(qtbot):
    tile = NewTile()
    qtbot.addWidget(tile)
    clicks = []
    tile.add_requested.connect(lambda: clicks.append(True))
    qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)
    assert clicks == [True]


def test_a_folder_already_making_one_grays_its_plus_out_and_says_why(qtbot):
    tile = NewTile(grayed_because="This folder is already making one")
    qtbot.addWidget(tile)

    assert not tile.isEnabled()
    assert tile.toolTip() == "This folder is already making one"


def test_a_grayed_plus_starts_nothing_on_a_click(qtbot):
    tile = NewTile(grayed_because="This folder is already making one")
    qtbot.addWidget(tile)
    clicks = []
    tile.add_requested.connect(lambda: clicks.append(True))

    qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)

    assert clicks == []


def test_a_press_on_a_grayed_plus_does_not_put_the_picked_items_down(qtbot):
    pane = GalleryPaneScrollArea()
    qtbot.addWidget(pane)
    tile = NewTile(grayed_because="This folder is already making one")
    pane.setWidget(tile)
    let_go = []
    pane.background_clicked.connect(lambda: let_go.append(True))

    qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)

    assert let_go == []


def _red_pixels(widget) -> int:
    image = widget.grab().toImage()
    return sum(1 for y in range(image.height()) for x in range(image.width())
               if (color := image.pixelColor(x, y)).red() - color.green() > 40)


def test_a_grayed_plus_wears_a_red_circle_slash_and_a_lit_one_does_not(qtbot):
    live, grayed = NewTile(), NewTile(grayed_because="This folder is already making one")
    for tile in (live, grayed):
        qtbot.addWidget(tile)

    assert (_red_pixels(live._glyph), _red_pixels(grayed._glyph) > 0) == (0, True)


def test_a_grayed_tile_fades_to_a_third_and_a_lit_one_does_not(qtbot):
    live, grayed = NewTile(), NewTile(grayed_because="This folder is already making one")
    for tile in (live, grayed):
        qtbot.addWidget(tile)

    assert live.graphicsEffect() is None
    assert grayed.graphicsEffect().opacity() == pytest.approx(1 / 3)


def _ink(label):
    palette = label.palette()
    return palette.color(palette.currentColorGroup(), QPalette.ColorRole.WindowText)


def test_a_grayed_plus_is_painted_darker_than_a_live_one(qtbot):
    app = QApplication.instance()
    prior = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        live, grayed = NewTile(), NewTile(grayed_because="This folder is already making one")
        for tile in (live, grayed):
            qtbot.addWidget(tile)
            tile.ensurePolished()

        assert _ink(grayed._glyph).lightness() < _ink(live._glyph).lightness()
        assert _ink(grayed._caption).lightness() < _ink(live._caption).lightness()
    finally:
        app.setStyleSheet(prior)
