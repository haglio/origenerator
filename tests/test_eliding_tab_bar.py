from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QTabWidget, QWidget

from origenerator.gui.eliding_tab_bar import ElidingTabBar


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
    # Qt sizes a tab widget's corner buttons to the bar, and a stock empty bar is
    # zero pixels tall — which took the "+" off screen with the last tab and made
    # an emptied pane a dead end. The row holds the height it had.
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
