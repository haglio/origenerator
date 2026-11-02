from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import QLabel

from origenerator.gui.source_tile import SourceTile


@pytest.fixture
def tile(qtbot):
    t = SourceTile()
    qtbot.addWidget(t)
    return t


def _labels(tile):
    return [lbl.text() for lbl in tile.findChildren(QLabel)]


def test_starts_hidden(tile):
    assert tile.isHidden()


def test_show_source_reveals_the_heading_and_the_items_whole_name(tile):
    widest = "DDDDDDDD 888"
    tile.show_source("img1", None, widest)
    assert not tile.isHidden()
    assert tile._name.text() == widest
    assert tile._name.fontMetrics().horizontalAdvance(widest) <= tile._name.width()
    assert any("source image" in t.lower() for t in _labels(tile))


def test_a_heading_wider_than_the_thumbnail_is_centered_over_it(tile, qtbot):
    with qtbot.waitExposed(tile):
        tile.show_source("vid1", None, "77B2E1A0 012",
                         heading="From a source far wider than any thumbnail is drawn")

    heading, thumb, name = (w.geometry() for w in (tile._heading, tile._thumb, tile._name))
    assert heading.width() > thumb.width()
    assert abs(heading.center().x() - thumb.center().x()) <= 1
    assert abs(name.center().x() - thumb.center().x()) <= 1


def test_clicking_the_tile_emits_activated_with_the_source_id(tile, qtbot):
    tile.show_source("img1", None, "sdxl_img1.png")
    with qtbot.waitExposed(tile):
        tile.show()
    got = []
    tile.activated.connect(got.append)

    qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)

    assert got == ["img1"]


def test_clear_hides_it_and_stops_it_emitting(tile):
    tile.show_source("img1", None, "x.png")
    tile.clear()
    assert tile.isHidden()
    assert tile._prompt_id is None


def test_renders_the_thumbnail_when_the_file_exists(tile, tmp_path):
    thumb = tmp_path / "t.png"
    QPixmap(64, 64).save(str(thumb))

    tile.show_source("img1", str(thumb), "img1.png")

    assert not tile._thumb.pixmap().isNull()


def test_survives_a_missing_thumbnail_file(tile):
    tile.show_source("img1", "C:/does/not/exist.png", "img1.png")
    assert not tile.isHidden()


def test_a_relation_named_for_one_showing_does_not_carry_to_the_next(tile):
    tile.show_source("vid1", None, "cycle.mp4", heading="Trimmed from", media_type="video")

    tile.show_source("img1", None, "start.png")

    assert tile._heading.text() == "From source image"
    assert tile._item_type_icon.media_type == "image"


def test_a_thumbnail_shown_only_for_its_settings_is_drained_of_color_and_the_next_is_not(tile, tmp_path):
    thumb = tmp_path / "red.png"
    red = QPixmap(32, 32)
    red.fill(QColor(220, 20, 20))
    red.save(str(thumb))

    tile.show_source("vid1", str(thumb), "source.mp4", gray=True)
    drained = tile._thumb.pixmap().toImage().pixelColor(16, 16)
    tile.show_source("img1", str(thumb), "start.png")
    kept = tile._thumb.pixmap().toImage().pixelColor(16, 16)

    assert drained.red() == drained.green() == drained.blue()
    assert kept.red() > kept.green()
