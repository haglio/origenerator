from __future__ import annotations

import pytest
from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import QLabel

from origenerator.gui.looping_preview import what_plays_in
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
    tile.show_source({"prompt_id": "img1", "thumbnail_path": None}, widest)
    assert not tile.isHidden()
    assert tile._name.text() == widest
    assert tile._name.fontMetrics().horizontalAdvance(widest) <= tile._name.width()
    assert any("source image" in t.lower() for t in _labels(tile))


def test_a_heading_wider_than_the_thumbnail_is_centered_over_it(tile, qtbot):
    with qtbot.waitExposed(tile):
        tile.show_source({"prompt_id": "vid1", "thumbnail_path": None}, "77B2E1A0 012",
                         heading="From a source far wider than any thumbnail is drawn")

    heading, thumb, name = (w.geometry() for w in (tile._heading, tile._thumb, tile._name))
    assert heading.width() > thumb.width()
    assert abs(heading.center().x() - thumb.center().x()) <= 1
    assert abs(name.center().x() - thumb.center().x()) <= 1


def test_clicking_the_tile_emits_activated_with_the_source_id(tile, qtbot):
    tile.show_source({"prompt_id": "img1", "thumbnail_path": None}, "sdxl_img1.png")
    with qtbot.waitExposed(tile):
        tile.show()
    got = []
    tile.activated.connect(got.append)

    qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)

    assert got == ["img1"]


def test_clear_hides_it_and_stops_it_emitting(tile):
    tile.show_source({"prompt_id": "img1", "thumbnail_path": None}, "x.png")
    tile.clear()
    assert tile.isHidden()
    assert tile._prompt_id is None


def test_renders_the_thumbnail_when_the_file_exists(tile, tmp_path):
    thumb = tmp_path / "t.png"
    QPixmap(64, 64).save(str(thumb))

    tile.show_source({"prompt_id": "img1", "thumbnail_path": str(thumb)}, "img1.png")

    assert not tile._thumb.pixmap().isNull()


def test_survives_a_missing_thumbnail_file(tile):
    tile.show_source({"prompt_id": "img1", "thumbnail_path": "C:/does/not/exist.png"}, "img1.png")
    assert not tile.isHidden()


def test_a_relation_named_for_one_showing_does_not_carry_to_the_next(tile):
    tile.show_source({"prompt_id": "vid1", "thumbnail_path": None}, "cycle.mp4", heading="Trimmed from", media_type="video")

    tile.show_source({"prompt_id": "img1", "thumbnail_path": None}, "start.png")

    assert tile.heading == "From source image"
    assert tile._item_type_icon.media_type == "image"


def test_a_heading_of_more_than_three_words_takes_two_lines_and_a_shorter_one_takes_one(tile):
    tile.show_source({"prompt_id": "vid1", "thumbnail_path": None}, "77B2E1A0 012",
                     heading="Animated using video settings of")
    long_lines = tile._heading.text().split("\n")
    tile.show_source({"prompt_id": "vid1", "thumbnail_path": None}, "77B2E1A0 012",
                     heading="Animated from")

    assert len(long_lines) == 2
    assert " ".join(long_lines) == "Animated using video settings of"
    assert tile.heading == "Animated from"


def test_thumbnails_under_one_and_two_line_headings_sit_at_one_height(qtbot):
    tiles = []
    for heading in ("Animated from", "Video settings used for animation of"):
        tile = SourceTile()
        qtbot.addWidget(tile)
        tile.show_source({"prompt_id": "vid1", "thumbnail_path": None}, "77B2E1A0 012",
                         heading=heading)
        tile.layout().activate()
        tiles.append(tile)

    assert tiles[0]._thumb.y() == tiles[1]._thumb.y()


def _red_thumb(tmp_path):
    thumb = tmp_path / "red.png"
    red = QPixmap(32, 32)
    red.fill(QColor(220, 20, 20))
    red.save(str(thumb))
    return str(thumb)


def test_a_thumbnail_shown_only_for_its_settings_is_drained_of_color_and_the_next_is_not(tile, tmp_path):
    thumb = _red_thumb(tmp_path)

    tile.show_source({"prompt_id": "vid1", "thumbnail_path": thumb}, "source.mp4", gray=True)
    drained = tile._thumb.pixmap().toImage().pixelColor(16, 16)
    tile.show_source({"prompt_id": "img1", "thumbnail_path": thumb}, "start.png")
    kept = tile._thumb.pixmap().toImage().pixelColor(16, 16)

    assert drained.red() == drained.green() == drained.blue()
    assert kept.red() > kept.green()


def _red_movie(path):
    frames = [Image.new("RGB", (16, 12), (220, 20 + i * 10, 20)) for i in range(2)]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=80, loop=0)
    return str(path)


def test_a_video_shown_only_for_its_settings_plays_drained_of_color(tile, tmp_path):
    tile.show_source({"prompt_id": "vid1", "thumbnail_path": None}, "77B2E1A0 012",
                     movie=_red_movie(tmp_path / "vid1.gif"), gray=True)

    shown = tile._thumb.pixmap().toImage().pixelColor(8, 6)
    assert what_plays_in(tile._thumb) is not None
    assert shown.red() == shown.green() == shown.blue()


def test_a_video_stops_playing_when_the_tile_shows_a_still(tile, tmp_path):
    tile.show_source({"prompt_id": "vid1", "thumbnail_path": None}, "77B2E1A0 012",
                     movie=_red_movie(tmp_path / "vid1.gif"), gray=True)
    tile.show_source({"prompt_id": "img1", "thumbnail_path": _red_thumb(tmp_path)}, "start.png")

    assert what_plays_in(tile._thumb) is None
