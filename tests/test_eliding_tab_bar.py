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
