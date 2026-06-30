from PyQt6.QtCore import Qt, QPoint, QPointF, QEvent
from PyQt6.QtGui import QColor, QEnterEvent
from PyQt6.QtWidgets import QApplication

from origenerator.gui.stylesheet import build_stylesheet
from origenerator.gui.thumbnail_widget import ThumbnailWidget, _SELECTED_BG


def test_hover_emits_hovered_then_unhovered(qtbot):
    tw = ThumbnailWidget("p1", None, "label")
    qtbot.addWidget(tw)
    seen = []
    tw.hovered.connect(lambda pid: seen.append(("in", pid)))
    tw.unhovered.connect(lambda pid: seen.append(("out", pid)))

    pos = QPointF(1, 1)
    tw.enterEvent(QEnterEvent(pos, pos, pos))
    tw.leaveEvent(QEvent(QEvent.Type.Leave))

    assert seen == [("in", "p1"), ("out", "p1")]


def test_highlight_toggles_and_is_distinct_from_selection(qtbot):
    tw = ThumbnailWidget("p1", None, "label")
    qtbot.addWidget(tw)
    assert tw.is_highlighted() is False
    tw.set_highlighted(True)
    assert tw.is_highlighted() is True
    assert tw.styleSheet() != ""        # a highlight fill is applied
    assert tw.is_selected() is False    # highlight is not selection
    tw.set_highlighted(False)
    assert tw.is_highlighted() is False
    assert tw.styleSheet() == ""


def test_left_click_emits_clicked_but_right_click_does_not(qtbot):
    tw = ThumbnailWidget("p1", None, "label")
    qtbot.addWidget(tw)
    clicks = []
    tw.clicked.connect(clicks.append)

    qtbot.mouseClick(tw, Qt.MouseButton.RightButton)
    assert clicks == []  # right-click is for the menu; it must not re-select

    qtbot.mouseClick(tw, Qt.MouseButton.LeftButton)
    assert clicks == ["p1"]


def test_right_click_requests_a_context_menu_for_this_thumbnail(qtbot):
    tw = ThumbnailWidget("p1", None, "label")
    qtbot.addWidget(tw)
    received = []
    tw.context_requested.connect(lambda pid, pos: received.append(pid))

    # What a right-click on the tile triggers (custom context-menu policy).
    tw.customContextMenuRequested.emit(QPoint(5, 5))

    assert received == ["p1"]


def test_thumbnail_starts_unselected(qtbot):
    tw = ThumbnailWidget("p1", None, "label")
    qtbot.addWidget(tw)
    assert tw.is_selected() is False
    assert tw.styleSheet() == ""  # no selection fill at rest


def test_selecting_lightens_the_whole_tile_behind_image_and_caption(qtbot):
    """The fill must reach behind the image and the caption, not just the margin.

    Rendered with the app stylesheet, which paints bare QLabels opaque — the
    exact reason an earlier fill showed only as a frame. Sampling real pixels
    (not the stylesheet string) is what catches that.
    """
    app = QApplication.instance()
    prior = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        tw = ThumbnailWidget("p1", None, "caption")
        qtbot.addWidget(tw)
        tw.resize(180, 200)
        tw.set_selected(True)
        tw.show()
        qtbot.waitExposed(tw)
        img = tw.grab().toImage()
        fill = QColor(_SELECTED_BG)
        assert img.pixelColor(8, 8) == fill     # behind the image
        assert img.pixelColor(8, 182) == fill    # behind the caption text
    finally:
        app.setStyleSheet(prior)
