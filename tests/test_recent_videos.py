from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QProxyStyle, QStyle, QStyleOptionViewItem

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


def _unlit(option):
    option = QStyleOptionViewItem(option)
    option.state &= ~QStyle.StateFlag.State_Selected
    return option


class _LitOverWhatItIsHanded(QProxyStyle):
    """Lights an item under the mouse over the whole rect its drawing is handed,
    in a wash that darkens where it is laid twice, as Windows 11's own style does."""

    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PrimitiveElement.PE_PanelItemViewItem:
            option = _unlit(option)
        super().drawPrimitive(element, option, painter, widget)

    def drawControl(self, element, option, painter, widget=None):
        if (element == QStyle.ControlElement.CE_ItemViewItem
                and option.state & QStyle.StateFlag.State_Selected):
            painter.fillRect(option.rect, QColor(0, 0, 255, 128))
            option = _unlit(option)
        super().drawControl(element, option, painter, widget)


def test_the_row_under_the_mouse_is_lit_once_all_around_its_picture(qtbot, tmp_path):
    dropdown = _dropdown(qtbot, [RecentVideo("vid1", square(tmp_path, "red"))])
    style = _LitOverWhatItIsHanded("fusion")
    style.setParent(dropdown)  # gone with the view it styles, never before it
    dropdown.view().setStyle(style)
    dropdown.showPopup()

    plain = painted_row(dropdown, 0)
    lit = painted_row(dropdown, 0, under_the_mouse=True)

    middle = plain.height() // 2
    picture = [x for x in range(plain.width()) if QColor(plain.pixel(x, middle)).saturation() == 0
               and QColor(plain.pixel(x, middle)).lightness() > 60]
    top = [y for y in range(plain.height()) if plain.pixel(picture[0], y) == plain.pixel(
        picture[0], middle)]
    around = ((picture[0] - 1, middle), (picture[-1] + 1, middle), (picture[0], top[0] - 1),
              (picture[0], top[-1] + 1), (plain.width() - 4, middle))
    assert len({lit.pixel(x, y) for x, y in around}) == 1
    assert all(lit.pixel(x, y) != plain.pixel(x, y) for x, y in around)
    dropdown.hidePopup()
