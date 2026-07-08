import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QLabel

from origenerator.gui.source_image_tile import SourceImageTile


@pytest.fixture
def tile(qtbot):
    t = SourceImageTile()
    qtbot.addWidget(t)
    return t


def _labels(tile):
    return [lbl.text() for lbl in tile.findChildren(QLabel)]


def test_starts_hidden(tile):
    assert tile.isHidden()


def test_show_source_reveals_the_heading_and_filename(tile):
    tile.show_source("img1", None, "a_rather_long_source_filename.png")
    assert not tile.isHidden()
    # The caption may middle-elide to fit the tile, but the full name is the tooltip.
    assert tile._filename.toolTip() == "a_rather_long_source_filename.png"
    assert any("source image" in t.lower() for t in _labels(tile))  # the heading


def test_clicking_the_tile_emits_activated_with_the_source_id(tile, qtbot):
    tile.show_source("img1", None, "sdxl_img1.png")
    tile.show()
    qtbot.waitExposed(tile)
    got = []
    tile.activated.connect(got.append)

    qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)

    assert got == ["img1"]


def test_clear_hides_it_and_stops_it_emitting(tile):
    tile.show_source("img1", None, "x.png")
    tile.clear()
    assert tile.isHidden()
    assert tile._prompt_id is None   # a click after clear has nothing to navigate to


def test_renders_the_thumbnail_when_the_file_exists(tile, tmp_path):
    thumb = tmp_path / "t.png"
    QPixmap(64, 64).save(str(thumb))

    tile.show_source("img1", str(thumb), "img1.png")

    assert not tile._thumb.pixmap().isNull()


def test_survives_a_missing_thumbnail_file(tile):
    tile.show_source("img1", "C:/does/not/exist.png", "img1.png")  # must not raise
    assert not tile.isHidden()
