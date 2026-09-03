import pytest
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QApplication, QTabWidget, QWidget

from origenerator.gui.eliding_tab_bar import (
    EDGE, MARK, MARK_CANVAS, ElidingTabBar, tab_mark,
)


def _tabs_with(qtbot, n, width=600):
    """A shown, laid-out tab widget holding ``n`` long-titled tabs at a fixed width."""
    tabs = QTabWidget()
    tabs.setTabBar(ElidingTabBar())
    qtbot.addWidget(tabs)
    for i in range(n):
        tabs.addTab(QWidget(), f"SDXL Text-to-Image › prompt {i}")
    tabs.resize(width, 400)
    tabs.show()
    QApplication.processEvents()
    return tabs


def test_long_title_is_capped_at_max_width(qtbot):
    # A very long tab label must not stretch its tab past the cap — it elides.
    bar = ElidingTabBar()
    qtbot.addWidget(bar)
    bar.addTab("SDXL Text-to-Image › " + "an extremely long prompt " * 8)
    assert bar.tabSizeHint(0).width() == ElidingTabBar.MAX_TAB_WIDTH


def test_short_title_keeps_its_natural_width(qtbot):
    # The cap is a ceiling, not a fixed size — a short label stays compact.
    bar = ElidingTabBar()
    qtbot.addWidget(bar)
    bar.addTab("A")
    assert bar.tabSizeHint(0).width() < ElidingTabBar.MAX_TAB_WIDTH


def test_labels_elide_with_an_ellipsis(qtbot):
    # A capped tab shows its label truncated with "…" rather than hard-clipped.
    bar = ElidingTabBar()
    qtbot.addWidget(bar)
    assert bar.elideMode() == Qt.TextElideMode.ElideRight


def test_never_shows_scroll_buttons(qtbot):
    # Overflow collapses the tabs instead of hiding them behind scroll arrows,
    # so every tab stays on screen.
    bar = ElidingTabBar()
    qtbot.addWidget(bar)
    assert bar.usesScrollButtons() is False


def test_all_tabs_stay_within_the_bar_when_crowded(qtbot):
    # Twenty tabs in a 600px bar: they collapse to fit rather than overflow, so
    # none is pushed off the edge and out of reach.
    tabs = _tabs_with(qtbot, n=20, width=600)
    bar = tabs.tabBar()
    right_edge = max(bar.tabRect(i).right() for i in range(bar.count()))
    assert right_edge <= bar.width()


def test_tabs_collapse_further_as_more_open(qtbot):
    # The more tabs share the row, the narrower each one gets.
    roomy = _tabs_with(qtbot, n=8, width=600)
    crowded = _tabs_with(qtbot, n=20, width=600)
    assert crowded.tabBar().tabRect(0).width() < roomy.tabBar().tabRect(0).width()


def test_the_row_keeps_its_height_when_the_last_tab_closes(qtbot):
    # A stock empty bar is zero pixels tall, so a bar that momentarily empties —
    # a pane rebuilding its tabs from a saved session — would collapse the row it
    # stands in and everything laid out beside it. The row holds the height it had.
    tabs = _tabs_with(qtbot, n=2)
    full = tabs.tabBar().sizeHint().height()
    assert full > 0
    tabs.removeTab(0)
    tabs.removeTab(0)
    assert tabs.tabBar().count() == 0
    assert tabs.tabBar().sizeHint().height() == full


def test_a_bar_that_never_held_a_tab_asks_for_no_row(qtbot):
    # Nothing to reserve a row for until a tab has shown what one measures.
    bar = ElidingTabBar()
    qtbot.addWidget(bar)
    assert bar.sizeHint().height() == 0


# --- each tab's own close button ---------------------------------------------

def _closable_bar(qtbot, count=2):
    bar = ElidingTabBar()
    bar.setTabsClosable(True)
    qtbot.addWidget(bar)
    for i in range(count):
        bar.addTab(f"tab {i}")
    return bar


def _close_button(bar, index):
    from PyQt6.QtWidgets import QTabBar
    return bar.tabButton(index, QTabBar.ButtonPosition.RightSide)


def test_every_tab_wears_the_bars_own_close_button(qtbot):
    # The stock one is painted red by the platform style on the tab in front, and
    # pushed flush against the tab's right edge.
    bar = _closable_bar(qtbot)
    assert [_close_button(bar, i).objectName() for i in range(2)] == [
        "tabCloseButton", "tabCloseButton",
    ]


def test_the_close_mark_is_padded_off_the_tabs_edge(qtbot):
    from PyQt6.QtWidgets import QStyle

    bar = _closable_bar(qtbot)
    button = _close_button(bar, 0)
    mark = bar.style().pixelMetric(QStyle.PixelMetric.PM_TabCloseIndicatorWidth)
    assert button.iconSize().width() == mark
    assert button.width() > mark  # room either side of the mark


def test_the_same_mark_whichever_tab_is_in_front(qtbot):
    bar = _closable_bar(qtbot)
    bar.setCurrentIndex(0)
    front, behind = _close_button(bar, 0), _close_button(bar, 1)
    size = front.iconSize()
    assert (front.icon().pixmap(size).toImage()
            == behind.icon().pixmap(size).toImage())


def test_clicking_a_close_button_asks_for_that_tab(qtbot):
    bar = _closable_bar(qtbot, count=3)
    asked = []
    bar.tabCloseRequested.connect(asked.append)

    _close_button(bar, 1).click()

    assert asked == [1]


def test_a_close_button_follows_its_tab_as_neighbors_close(qtbot):
    # Its index is looked up at click time, because tabs shift under it.
    bar = _closable_bar(qtbot, count=3)
    last = _close_button(bar, 2)
    asked = []
    bar.tabCloseRequested.connect(asked.append)
    bar.removeTab(0)

    last.click()

    assert asked == [1]  # it is the second tab now, and says so


# --- the preview tab, drawn in italic ----------------------------------------

def _painted_label_font(bar, index):
    """The font the bar's style would paint tab ``index``'s label with.

    Read at the drawing call rather than off a rendered pixmap: the offscreen
    platform this suite runs on paints italic and upright text identically, so a
    picture of the bar cannot tell them apart.
    """
    from PyQt6.QtGui import QPainter, QPixmap

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
    # Qt has no per-tab font, so the slant is applied where the label is finally
    # painted — this is the whole mechanism, and it is worth pinning down.
    bar = _closable_bar(qtbot, count=3)
    bar.set_preview_index(1)
    assert _painted_label_font(bar, 1).italic() is True


def test_the_other_tabs_stay_upright(qtbot):
    # The painter carries its font from one label to the next, so an italic left
    # behind would spread down the row.
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
    # A stale index — the preview tab closed, its index not yet re-synced —
    # must not slant whichever tab has since taken that slot.
    bar = _closable_bar(qtbot, count=2)
    bar.set_preview_index(5)
    assert _painted_label_font(bar, 0).italic() is False
    assert _painted_label_font(bar, 1).italic() is False


def test_the_bars_style_is_owned_by_the_bar(qtbot):
    # QProxyStyle takes ownership of a base style that has no parent, and setting
    # an app stylesheet re-wraps every widget's own style in a QStyleSheetStyle —
    # so an unparented proxy is deleted out from under Python the first time the
    # app is themed, and the next thing to touch it faults the process.
    bar = _closable_bar(qtbot)
    assert bar._preview_style.parent() is bar


def test_the_italic_mark_survives_the_app_being_themed(qtbot):
    from PyQt6.QtWidgets import QApplication

    from origenerator.gui.stylesheet import build_stylesheet

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


def test_a_close_button_follows_its_tab_when_it_is_dragged(qtbot):
    # Reordering by drag is new; a tab's ✕ must still close the tab it rides on
    # rather than whatever has taken its old slot.
    bar = _closable_bar(qtbot, count=3)
    first = _close_button(bar, 0)
    asked = []
    bar.tabCloseRequested.connect(asked.append)
    bar.moveTab(0, 2)

    first.click()

    assert asked == [2]


# --- the mark a tab wears, and the space around it ---------------------------

def _picture(width, height, color=Qt.GlobalColor.red) -> QIcon:
    pixmap = QPixmap(width, height)
    pixmap.fill(color)
    return QIcon(pixmap)


@pytest.mark.parametrize("shape", [(256, 144), (144, 256), (200, 200)])
def test_a_mark_is_the_same_width_whatever_shape_the_picture_is(shape):
    # The row's spacing is built on the mark's width, so a portrait thumbnail
    # must not push the label further out than a landscape one does.
    mark = tab_mark(_picture(*shape))
    assert mark.actualSize(MARK_CANVAS) == MARK_CANVAS


def test_a_mark_trails_the_gap_its_label_needs(qtbot):
    # Qt's own tab layout puts the text a fixed 4px after whatever the icon
    # measures, so the rest of the gap rides on the canvas as transparency.
    canvas = tab_mark(_picture(256, 144)).pixmap(MARK_CANVAS).toImage()
    assert canvas.width() == MARK + EDGE - 4
    assert canvas.pixelColor(MARK - 1, MARK // 2).alpha() == 255   # picture
    assert canvas.pixelColor(MARK, MARK // 2).alpha() == 0         # its gap


def test_a_tab_with_nothing_to_show_wears_nothing(qtbot):
    assert tab_mark(QIcon()).isNull()


def test_a_marks_distance_from_the_tab_edge_is_the_apps_own(qtbot):
    # The whole point of the arithmetic above: painted under the real stylesheet,
    # a tab's mark starts EDGE in from the tab's left edge — the same inset the ✕
    # keeps at the other end.
    from origenerator.gui.stylesheet import build_stylesheet

    app = QApplication.instance()
    prior = app.styleSheet()
    try:
        app.setStyleSheet(build_stylesheet())  # before the widget: it styles on build
        tabs = QTabWidget()
        tabs.setTabBar(ElidingTabBar())
        qtbot.addWidget(tabs)
        tabs.setTabsClosable(True)
        tabs.setIconSize(MARK_CANVAS)
        tabs.addTab(QWidget(), tab_mark(_picture(256, 144)), "a tab")
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
