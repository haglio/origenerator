from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, QSize, Qt
from PyQt6.QtGui import QColor, QImage, QMovie
from PyQt6.QtWidgets import QProxyStyle, QStyle, QStyleOptionViewItem

from origenerator.gui.recent_videos import RecentVideo, RecentVideos
from origenerator.gui.thumbnail_box import THUMBNAIL_BOX
from tests.thumbnail_rows import looping_video, painted_row, square
from tests.thumbnail_rows import where_the_thumbnail_is as _where_the_thumbnail_is


def _dropdown(qtbot, videos, looping_previews=None):
    dropdown = RecentVideos(lambda: videos, (looping_previews or {}).get)
    qtbot.addWidget(dropdown)
    return dropdown


def test_the_closed_dropdown_reads_recent(qtbot):
    dropdown = _dropdown(qtbot, [])

    assert dropdown.display_text(1000) == "Recent"


def test_each_video_is_a_row_wearing_its_thumbnail_drained_of_color(qtbot, tmp_path):
    dropdown = _dropdown(qtbot, [RecentVideo("vid1", square(tmp_path, "red"))])
    dropdown.showPopup()

    row = painted_row(dropdown, 0)

    middle = row.pixelColor(_where_the_thumbnail_is(row).center())
    assert dropdown.count() == 1
    assert middle.saturation() == 0
    assert middle.lightness() > 0
    dropdown.hidePopup()


def test_a_video_with_no_thumbnail_shows_a_blank_square(qtbot):
    dropdown = _dropdown(qtbot, [RecentVideo("vid1", None)])
    dropdown.showPopup()

    row = painted_row(dropdown, 0)

    assert _where_the_thumbnail_is(row).size() == THUMBNAIL_BOX
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


def test_the_row_under_the_mouse_is_lit_once_all_around_its_thumbnail(qtbot, tmp_path):
    dropdown = _dropdown(qtbot, [RecentVideo("vid1", square(tmp_path, "red"))])
    style = _LitOverWhatItIsHanded("fusion")
    style.setParent(dropdown)  # gone with the view it styles, never before it
    dropdown.view().setStyle(style)
    dropdown.showPopup()

    plain = painted_row(dropdown, 0)
    lit = painted_row(dropdown, 0, under_the_mouse=True)

    middle = plain.height() // 2
    thumbnail = [x for x in range(plain.width()) if QColor(plain.pixel(x, middle)).saturation() == 0
                 and QColor(plain.pixel(x, middle)).lightness() > 60]
    top = [y for y in range(plain.height()) if plain.pixel(thumbnail[0], y) == plain.pixel(
        thumbnail[0], middle)]
    around = ((thumbnail[0] - 1, middle), (thumbnail[-1] + 1, middle), (thumbnail[0], top[0] - 1),
              (thumbnail[0], top[-1] + 1), (plain.width() - 4, middle))
    assert len({lit.pixel(x, y) for x, y in around}) == 1
    assert all(lit.pixel(x, y) != plain.pixel(x, y) for x, y in around)
    dropdown.hidePopup()


def _thumbnail(tmp_path, width, height) -> str:
    path = tmp_path / f"made-{width}x{height}.png"
    thumbnail = QImage(width, height, QImage.Format.Format_RGB32)
    thumbnail.fill(QColor("red"))
    thumbnail.save(str(path))
    return str(path)


def test_a_row_draws_its_thumbnail_the_size_the_drop_box_does(qtbot, tmp_path):
    dropdown = _dropdown(qtbot, [RecentVideo("vid1", _thumbnail(tmp_path, 300, 150))])
    dropdown.showPopup()

    row = painted_row(dropdown, 0)

    assert _where_the_thumbnail_is(row).size() == QSize(300, 150).scaled(
        THUMBNAIL_BOX, Qt.AspectRatioMode.KeepAspectRatio)
    dropdown.hidePopup()


def test_a_tall_thumbnails_row_is_taller_than_a_wide_thumbnails_row(qtbot, tmp_path):
    dropdown = _dropdown(qtbot, [RecentVideo("tall", _thumbnail(tmp_path, 150, 300)),
                                 RecentVideo("wide", _thumbnail(tmp_path, 300, 150))])
    dropdown.showPopup()

    tall, wide = (dropdown.view().visualRect(dropdown.model().index(row, 0)).height()
                  for row in (0, 1))

    assert tall - wide == THUMBNAIL_BOX.height() - THUMBNAIL_BOX.height() // 2
    dropdown.hidePopup()


def test_a_rows_thumbnail_sits_in_the_middle_of_the_row(qtbot, tmp_path):
    dropdown = _dropdown(qtbot, [RecentVideo("vid1", _thumbnail(tmp_path, 150, 300))])
    dropdown.showPopup()

    row = painted_row(dropdown, 0)

    assert abs(_where_the_thumbnail_is(row).center().x() - row.width() // 2) <= 1
    dropdown.hidePopup()


def test_a_videos_thumbnail_plays_in_its_row(qtbot, tmp_path):
    dropdown = _dropdown(qtbot, [RecentVideo("vid1", None)], {"vid1": looping_video(tmp_path)})
    dropdown.showPopup()
    first = painted_row(dropdown, 0)
    middle = _where_the_thumbnail_is(first).center()

    qtbot.waitUntil(lambda: painted_row(dropdown, 0).pixel(middle) != first.pixel(middle),
                    timeout=3000)
    dropdown.hidePopup()


def test_closing_the_list_stops_its_videos(qtbot, tmp_path):
    dropdown = _dropdown(qtbot, [RecentVideo("vid1", None)], {"vid1": looping_video(tmp_path)})
    dropdown.showPopup()
    painted_row(dropdown, 0)

    dropdown.hidePopup()

    assert not [movie for movie in dropdown.findChildren(QMovie)
                if movie.state() == QMovie.MovieState.Running]


class _Redraws(QObject):
    def __init__(self):
        super().__init__()
        self.count = 0

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Paint:
            self.count += 1
        return False


def test_the_open_list_redraws_a_playing_video_by_itself(qtbot, tmp_path):
    dropdown = _dropdown(qtbot, [RecentVideo("vid1", None)], {"vid1": looping_video(tmp_path)})
    dropdown.showPopup()
    painted_row(dropdown, 0)
    qtbot.wait(300)
    redraws = _Redraws()
    dropdown.view().viewport().installEventFilter(redraws)

    qtbot.waitUntil(lambda: redraws.count > 0, timeout=3000)
    dropdown.view().viewport().removeEventFilter(redraws)
    dropdown.hidePopup()
