from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTabBar


class ElidingTabBar(QTabBar):
    """A tab bar that keeps every tab on screen at once — and keeps its row when
    it holds none.

    Each tab is capped at ``MAX_TAB_WIDTH`` with its label elided, so a long
    title takes only its share of the row instead of stretching the tab. When
    more tabs open than fit even at that width, they collapse further — down to
    an equal share of the bar — rather than disappearing behind scroll buttons.

    An empty bar still asks for the height it had while it held tabs. A stock
    QTabBar asks for nothing, and QTabWidget sizes its corner widget to the bar —
    so closing the last tab flattened the corner's buttons to zero pixels and
    took the "+" that reopens a tab off screen with them.
    """

    MAX_TAB_WIDTH = 220

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.setUsesScrollButtons(False)
        self._row_height = 0  # what one tab measured; the row an empty bar holds

    def sizeHint(self):
        size = super().sizeHint()
        if self.count() > 0:
            self._row_height = size.height()  # remember the row a tab asks for
        else:
            size.setHeight(self._row_height)
        return size

    def minimumSizeHint(self):
        size = super().minimumSizeHint()
        if self.count() == 0:
            size.setHeight(self._row_height)
        return size

    def tabSizeHint(self, index):
        size = super().tabSizeHint(index)
        size.setWidth(min(size.width(), self.MAX_TAB_WIDTH))
        return size

    def minimumTabSizeHint(self, index):
        size = super().minimumTabSizeHint(index)
        # Let a tab shrink to no more than an equal share of the bar, so every
        # tab keeps a slot as more are opened — the row packs them tighter rather
        # than pushing the overflow off the edge (there are no scroll buttons).
        if self.count() > 0 and self.width() > 0:
            size.setWidth(min(size.width(), self.width() // self.count()))
        return size
