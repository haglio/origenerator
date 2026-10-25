"""Every thumbnail drawn beside the gallery is the size the Drop a video box draws it.

His rule (2026-10-21): "all thumbnails aside from the ones in the Gallery view
(which are bigger) should be the same size", the size the Combine drop box shows.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QColor, QImage

from origenerator.gallery.enhance import EnhanceLevel
from origenerator.gui.animated_strip import AnimatedVideoStrip
from origenerator.gui.drop_slot import DropSlot
from origenerator.gui.enhance_versions import _LevelRow
from origenerator.gui.source_tile import SourceTile
from origenerator.media import MediaType


def _wide_thumbnail(tmp_path) -> str:
    path = tmp_path / "wide.png"
    thumbnail = QImage(300, 150, QImage.Format.Format_RGB32)
    thumbnail.fill(QColor("red"))
    thumbnail.save(str(path))
    return str(path)


def _as_the_drop_box_draws_it(qtbot, path) -> QSize:
    box = DropSlot(MediaType.IMAGE, lambda pid: pid, lambda pid: (path, None), "Drop an image")
    qtbot.addWidget(box)
    box.set_item("img")
    return box._label.pixmap().size()


def test_a_source_tile_draws_a_thumbnail_the_size_the_drop_box_does(qtbot, tmp_path):
    path = _wide_thumbnail(tmp_path)
    tile = SourceTile()
    qtbot.addWidget(tile)

    tile.show_source("img", path, "a name")

    assert tile._thumb.pixmap().size() == _as_the_drop_box_draws_it(qtbot, path)


def test_the_animated_in_strip_draws_a_thumbnail_the_size_the_drop_box_does(qtbot, tmp_path):
    path = _wide_thumbnail(tmp_path)
    strip = AnimatedVideoStrip()
    qtbot.addWidget(strip)

    strip.show_videos([("vid", None, path)])

    tile = strip._host.layout().itemAt(0).widget()
    assert tile.pixmap().size() == _as_the_drop_box_draws_it(qtbot, path)


def test_an_enhancement_level_draws_a_thumbnail_the_size_the_drop_box_does(qtbot, tmp_path):
    path = _wide_thumbnail(tmp_path)
    row = _LevelRow(EnhanceLevel(1, "Enhance 1", {"filename": "wide.png"}, {}), 1, path)
    qtbot.addWidget(row)

    assert row._thumbnail.pixmap().size() == _as_the_drop_box_draws_it(qtbot, path)
