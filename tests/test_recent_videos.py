from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from origenerator.gui.recent_videos import RecentVideo, RecentVideos
from tests.pictured_rows import painted_row, square


def _dropdown(qtbot, videos):
    dropdown = RecentVideos(lambda: videos)
    qtbot.addWidget(dropdown)
    return dropdown


def test_the_closed_dropdown_reads_recent(qtbot):
    dropdown = _dropdown(qtbot, [])

    assert dropdown.display_text(1000) == "Recent"


def test_each_video_is_a_row_wearing_its_picture_drained_of_color(qtbot, tmp_path):
    dropdown = _dropdown(qtbot, [RecentVideo("vid1", square(tmp_path, "red"))])
    dropdown.showPopup()

    row = painted_row(dropdown, 0)

    middle = row.pixelColor(row.height() // 2, row.height() // 2)
    assert dropdown.count() == 1
    assert middle.saturation() == 0 and middle.lightness() > 0
    dropdown.hidePopup()


def test_a_video_with_no_picture_shows_a_blank_square(qtbot):
    dropdown = _dropdown(qtbot, [RecentVideo("vid1", None)])
    dropdown.showPopup()

    row = painted_row(dropdown, 0)

    middle, edge = row.height() // 2, 5
    assert row.pixelColor(edge + 1, middle) != QColor("black")
    assert row.pixelColor(middle, edge + 1) != QColor("black")
    dropdown.hidePopup()


def test_picking_a_video_names_it_and_the_field_reads_recent_again(qtbot):
    dropdown = _dropdown(qtbot, [RecentVideo("vid2", None), RecentVideo("vid1", None)])
    picked = []
    dropdown.picked.connect(picked.append)
    dropdown.showPopup()
    view = dropdown.view()

    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                     pos=view.visualRect(dropdown.model().index(1, 0)).center())

    assert picked == ["vid1"]
    assert dropdown.display_text(1000) == "Recent"


def test_with_no_video_to_list_the_dropdown_is_live_and_empty(qtbot):
    dropdown = _dropdown(qtbot, [])

    dropdown.refresh()

    assert dropdown.isEnabled()
    assert dropdown.count() == 0
