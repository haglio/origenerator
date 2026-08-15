from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QStyle, QTabBar, QToolButton

from origenerator.gui.icons import tab_close_icon

# How much wider than its mark a tab's close button sits, so the ✕ isn't flush
# against the tab's right edge.
_CLOSE_PADDING = 8


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

    Each tab carries a close button of this bar's own rather than the stock one,
    which the platform style paints red on the tab in front and pushes flush
    against its right edge. Ours is the same mark at every position, padded off
    the edge, and the very mark the pane's close-all wears.
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

    # --- each tab's own close button ---------------------------------------

    def tabInserted(self, index: int):
        super().tabInserted(index)
        if self.tabsClosable():
            self.setTabButton(index, QTabBar.ButtonPosition.RightSide,
                              self._close_button())

    def _close_button(self) -> QToolButton:
        """A tab's ✕: the style's own mark, unchanging, padded off the tab edge."""
        mark = self.style().pixelMetric(QStyle.PixelMetric.PM_TabCloseIndicatorWidth)
        button = QToolButton(self)
        button.setObjectName("tabCloseButton")
        button.setIcon(tab_close_icon())
        button.setIconSize(QSize(mark, mark))
        button.setFixedSize(mark + _CLOSE_PADDING, mark)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip("Close this configuration")
        button.clicked.connect(lambda _=False, b=button: self._close_clicked(b))
        return button

    def _close_clicked(self, button):
        """Ask for whichever tab is wearing this button now to close.

        Its index is looked up rather than captured: tabs shift as their
        neighbors close, and a captured one would soon name someone else.
        """
        for index in range(self.count()):
            if self.tabButton(index, QTabBar.ButtonPosition.RightSide) is button:
                self.tabCloseRequested.emit(index)
                return
