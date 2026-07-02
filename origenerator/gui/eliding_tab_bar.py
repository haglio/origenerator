from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTabBar


class ElidingTabBar(QTabBar):
    """A tab bar that keeps every tab on screen at once.

    Each tab is capped at ``MAX_TAB_WIDTH`` with its label elided, so a long
    title takes only its share of the row instead of stretching the tab. When
    more tabs open than fit even at that width, they collapse further — down to
    an equal share of the bar — rather than disappearing behind scroll buttons.
    """

    MAX_TAB_WIDTH = 220

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.setUsesScrollButtons(False)

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
