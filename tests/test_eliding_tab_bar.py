from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QStyle, QTabBar, QTabWidget, QWidget

from origenerator.gallery.item_numbers import widest_item_name
from origenerator.gui.eliding_tab_bar import (
    EDGE,
    MARK,
    MARK_CANVAS,
    ElidingTabBar,
    tab_mark,
)
from origenerator.gui.stylesheet import build_stylesheet


def _tabs_with(qtbot, n, width=600):
    tabs = QTabWidget()
    tabs.setTabBar(ElidingTabBar())
    qtbot.addWidget(tabs)
    for i in range(n):
        tabs.addTab(QWidget(), f"SDXL T2I › prompt {i}")
    tabs.resize(width, 400)
    tabs.show()
    QApplication.processEvents()
    return tabs


def _widest_name(bar) -> str:
    return widest_item_name(bar.fontMetrics().horizontalAdvance)


def test_a_long_title_gets_only_the_room_the_widest_item_name_needs(qtbot):
    bar = ElidingTabBar()
    qtbot.addWidget(bar)
    bar.addTab("SDXL T2I › " + "an extremely long prompt " * 8)
    bar.addTab(_widest_name(bar))
    assert bar.tabSizeHint(0).width() == bar.tabSizeHint(1).width()


def test_short_title_keeps_its_natural_width(qtbot):
    bar = ElidingTabBar()
    qtbot.addWidget(bar)
    bar.addTab("A")
    assert bar.tabSizeHint(0).width() == QTabBar.tabSizeHint(bar, 0).width()


@pytest.mark.parametrize("point_size", [9.0, 13.5, 20.0])
def test_the_widest_name_an_item_can_wear_fits_its_tab_whole(qtbot, point_size):
    bar = ElidingTabBar()
    qtbot.addWidget(bar)
    font = bar.font()
    font.setPointSizeF(point_size)
    bar.setFont(font)
    bar.setTabsClosable(True)
    bar.setIconSize(MARK_CANVAS)
    pixmap = QPixmap(40, 30)
    pixmap.fill(Qt.GlobalColor.gray)
    bar.addTab(tab_mark(QIcon(pixmap)), _widest_name(bar))

    assert bar.tabSizeHint(0).width() == QTabBar.tabSizeHint(bar, 0).width()


def test_labels_elide_with_an_ellipsis(qtbot):
    bar = ElidingTabBar()
    qtbot.addWidget(bar)
    assert bar.elideMode() == Qt.TextElideMode.ElideRight


def test_never_shows_scroll_buttons(qtbot):
    bar = ElidingTabBar()
    qtbot.addWidget(bar)
    assert bar.usesScrollButtons() is False


def test_all_tabs_stay_within_the_bar_when_crowded(qtbot):
    tabs = _tabs_with(qtbot, n=20, width=600)
    bar = tabs.tabBar()
    right_edge = max(bar.tabRect(i).right() for i in range(bar.count()))
    assert right_edge <= bar.width()


def test_a_crowded_row_never_asks_for_more_width_than_it_has(qtbot):
    tabs = _tabs_with(qtbot, n=20, width=600)

    assert tabs.minimumSizeHint().width() <= tabs.width()


def test_tabs_collapse_further_as_more_open(qtbot):
    roomy = _tabs_with(qtbot, n=8, width=600)
    crowded = _tabs_with(qtbot, n=20, width=600)
    assert crowded.tabBar().tabRect(0).width() < roomy.tabBar().tabRect(0).width()


def test_the_row_keeps_its_height_when_the_last_tab_closes(qtbot):
    tabs = _tabs_with(qtbot, n=2)
    full = tabs.tabBar().sizeHint().height()
    assert full > 0
    tabs.removeTab(0)
    tabs.removeTab(0)
    assert tabs.tabBar().count() == 0
    assert tabs.tabBar().sizeHint().height() == full


def test_a_bar_that_never_held_a_tab_asks_for_no_row(qtbot):
    bar = ElidingTabBar()
    qtbot.addWidget(bar)
    assert bar.sizeHint().height() == 0


def _closable_bar(qtbot, count=2):
    bar = ElidingTabBar()
    bar.setTabsClosable(True)
    qtbot.addWidget(bar)
    for i in range(count):
        bar.addTab(f"tab {i}")
    return bar


def _close_button(bar, index):
    return bar.tabButton(index, QTabBar.ButtonPosition.RightSide)


def test_every_tab_wears_the_bars_own_close_button(qtbot):
    bar = _closable_bar(qtbot)
    assert [_close_button(bar, i).objectName() for i in range(2)] == [
        "tabCloseButton", "tabCloseButton",
    ]


def test_the_close_mark_is_padded_off_the_tabs_edge(qtbot):
    bar = _closable_bar(qtbot)
    button = _close_button(bar, 0)
    mark = bar.style().pixelMetric(QStyle.PixelMetric.PM_TabCloseIndicatorWidth)
    assert button.iconSize().width() == mark
    assert button.width() > mark


def test_the_same_mark_whichever_tab_is_in_front(qtbot):
    bar = _closable_bar(qtbot)
    bar.setCurrentIndex(0)
    front, next_along = _close_button(bar, 0), _close_button(bar, 1)
    size = front.iconSize()
    assert (front.icon().pixmap(size).toImage()
            == next_along.icon().pixmap(size).toImage())


def test_clicking_a_close_button_asks_for_that_tab(qtbot):
    bar = _closable_bar(qtbot, count=3)
    asked = []
    bar.tabCloseRequested.connect(asked.append)

    _close_button(bar, 1).click()

    assert asked == [1]


def test_a_close_button_follows_its_tab_as_neighbors_close(qtbot):
    bar = _closable_bar(qtbot, count=3)
    last = _close_button(bar, 2)
    asked = []
    bar.tabCloseRequested.connect(asked.append)
    bar.removeTab(0)

    last.click()

    assert asked == [1]


def test_a_close_button_follows_its_tab_when_it_is_dragged(qtbot):
    bar = _closable_bar(qtbot, count=3)
    first = _close_button(bar, 0)
    asked = []
    bar.tabCloseRequested.connect(asked.append)
    bar.moveTab(0, 2)

    first.click()

    assert asked == [2]


def _middle_press(qtbot, widget, pos):
    qtbot.mousePress(widget, Qt.MouseButton.MiddleButton, pos=pos)


def test_a_middle_click_asks_for_the_tab_under_it_on_the_press(qtbot):
    bar = _closable_bar(qtbot, count=3)
    asked = []
    bar.tabCloseRequested.connect(asked.append)

    _middle_press(qtbot, bar, bar.tabRect(1).center())

    assert asked == [1]


def test_the_release_ending_a_middle_click_asks_for_nothing_more(qtbot):
    bar = _closable_bar(qtbot, count=3)
    asked = []
    bar.tabCloseRequested.connect(asked.append)
    middle = bar.tabRect(1).center()

    _middle_press(qtbot, bar, middle)
    qtbot.mouseRelease(bar, Qt.MouseButton.MiddleButton, pos=middle)

    assert asked == [1]


def test_a_middle_click_on_the_close_mark_closes_that_tab_too(qtbot):
    bar = _closable_bar(qtbot, count=3)
    bar.resize(bar.sizeHint())
    mark = _close_button(bar, 1)
    asked = []
    bar.tabCloseRequested.connect(asked.append)

    _middle_press(qtbot, mark, mark.rect().center())

    assert asked == [1]


def test_a_middle_click_beside_the_tabs_closes_nothing(qtbot):
    bar = _closable_bar(qtbot, count=2)
    bar.setExpanding(False)
    bar.resize(600, bar.sizeHint().height())
    beside = QPoint(bar.tabRect(1).right() + 40, bar.tabRect(1).center().y())
    assert bar.tabAt(beside) == -1
    asked = []
    bar.tabCloseRequested.connect(asked.append)

    _middle_press(qtbot, bar, beside)

    assert asked == []


def test_a_middle_click_closes_nothing_in_a_row_that_offers_no_close(qtbot):
    bar = ElidingTabBar()
    qtbot.addWidget(bar)
    bar.addTab("tab 0")
    bar.addTab("tab 1")
    asked = []
    bar.tabCloseRequested.connect(asked.append)

    _middle_press(qtbot, bar, bar.tabRect(1).center())

    assert asked == []


def _painted_label_font(bar, index):
    """The font the bar's style would paint tab ``index``'s label with, read at the drawing call: Qt's offscreen platform paints italic and upright text identically."""
    pixmap = QPixmap(400, 60)
    painter = QPainter(pixmap)
    try:
        bar.style().drawItemText(painter, bar.tabRect(index), 0, bar.palette(),
                                 True, bar.tabText(index))
        return painter.font()
    finally:
        painter.end()


def test_no_tab_is_the_preview_tab_to_begin_with(qtbot):
    bar = _closable_bar(qtbot)
    assert bar._preview_index == -1
    assert _painted_label_font(bar, 0).italic() is False


def test_the_preview_tabs_label_is_painted_italic(qtbot):
    bar = _closable_bar(qtbot, count=3)
    bar.set_preview_index(1)
    assert _painted_label_font(bar, 1).italic() is True


def test_the_other_tabs_stay_upright(qtbot):
    bar = _closable_bar(qtbot, count=3)
    bar.set_preview_index(1)
    assert _painted_label_font(bar, 0).italic() is False
    assert _painted_label_font(bar, 2).italic() is False


def test_clearing_the_preview_tab_puts_its_label_back_upright(qtbot):
    bar = _closable_bar(qtbot)
    bar.set_preview_index(0)
    bar.set_preview_index(-1)
    assert _painted_label_font(bar, 0).italic() is False


def test_an_index_past_the_last_tab_marks_nothing(qtbot):
    bar = _closable_bar(qtbot, count=2)
    bar.set_preview_index(5)
    assert _painted_label_font(bar, 0).italic() is False
    assert _painted_label_font(bar, 1).italic() is False


def test_the_bars_style_is_owned_by_the_bar(qtbot):
    bar = _closable_bar(qtbot)
    assert bar._preview_style.parent() is bar


def test_the_italic_mark_survives_the_app_being_themed(qtbot):
    app = QApplication.instance()
    prior = app.styleSheet()
    bar = _closable_bar(qtbot)
    bar.set_preview_index(0)
    try:
        app.setStyleSheet(build_stylesheet())
        assert _painted_label_font(bar, 0).italic() is True
    finally:
        app.setStyleSheet(prior)
    assert _painted_label_font(bar, 0).italic() is True


def _icon(width, height, color=Qt.GlobalColor.red) -> QIcon:
    pixmap = QPixmap(width, height)
    pixmap.fill(color)
    return QIcon(pixmap)


@pytest.mark.parametrize("shape", [(256, 144), (144, 256), (200, 200)])
def test_a_mark_is_the_same_width_whatever_shape_the_thumbnail_is(shape):
    mark = tab_mark(_icon(*shape))
    assert mark.actualSize(MARK_CANVAS) == MARK_CANVAS


def test_a_mark_trails_the_gap_its_label_needs(qtbot):
    canvas = tab_mark(_icon(256, 144)).pixmap(MARK_CANVAS).toImage()
    assert canvas.width() == MARK + EDGE - 4
    assert canvas.pixelColor(MARK - 1, MARK // 2).alpha() == 255
    assert canvas.pixelColor(MARK, MARK // 2).alpha() == 0


def test_a_tab_with_nothing_to_show_wears_nothing(qtbot):
    assert tab_mark(QIcon()).isNull()


def test_a_marks_distance_from_the_tab_edge_is_the_apps_own(qtbot):
    app = QApplication.instance()
    prior = app.styleSheet()
    try:
        app.setStyleSheet(build_stylesheet())
        tabs = QTabWidget()
        tabs.setTabBar(ElidingTabBar())
        qtbot.addWidget(tabs)
        tabs.setTabsClosable(True)
        tabs.setIconSize(MARK_CANVAS)
        tabs.addTab(QWidget(), tab_mark(_icon(256, 144)), "a tab")
        tabs.resize(600, 400)
        tabs.show()
        QApplication.processEvents()
        image = tabs.tabBar().grab().toImage()
    finally:
        app.setStyleSheet(prior)

    def is_mark(x, y):
        color = image.pixelColor(x, y)
        return color.red() > 180 and color.green() < 80 and color.blue() < 80

    columns = [x for x in range(image.width())
               if any(is_mark(x, y) for y in range(image.height()))]
    rect = tabs.tabBar().tabRect(0)
    assert columns[0] - rect.left() == EDGE
    assert columns[-1] - columns[0] + 1 == MARK


def test_the_close_button_says_it_closes_this_tab(qtbot):
    bar = _closable_bar(qtbot)
    assert _close_button(bar, 0).toolTip() == "Close this tab"
