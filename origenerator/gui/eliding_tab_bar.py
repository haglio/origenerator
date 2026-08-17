from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QProxyStyle, QStyle, QTabBar, QToolButton

from origenerator.gui.icons import tab_close_icon

# How much wider than its mark a tab's close button sits, so the ✕ isn't flush
# against the tab's right edge.
_CLOSE_PADDING = 12


class _PreviewTabStyle(QProxyStyle):
    """Draws one tab's label slanted — the IDE mark for a tab held only until the
    next one is clicked.

    Qt offers no per-tab font: ``QStyleOptionTab`` carries no font, and a font set
    on the bar itself is overwritten by the app's stylesheet at every polish. So
    the slant is applied at the last point that sees one label at a time. Every
    tab label, however the style draws the tab around it, reaches ``drawItemText``
    with the label's own rect — enough to tell which tab is being painted.

    Each label sets the flag either way rather than only slanting the preview
    one: the painter carries its font from one label to the next, so an italic
    left behind would spread down the row.
    """

    def __init__(self, bar: "ElidingTabBar"):
        super().__init__()
        self._bar = bar
        # Parented to the bar on purpose. Setting an app stylesheet re-wraps every
        # widget's own style in a QStyleSheetStyle, and QProxyStyle takes ownership
        # of a base style that has no parent — so an unparented proxy gets deleted
        # out from under Python the first time a stylesheet is applied, and the
        # next thing to touch it faults. Owned by the bar, it is left alone.
        self.setParent(bar)

    def drawItemText(self, painter, rect, flags, palette, enabled, text,
                     text_role=QPalette.ColorRole.NoRole):
        font = painter.font()
        italic = self._bar.rect_is_preview_tab(rect)
        if font.italic() != italic:
            font.setItalic(italic)
            painter.setFont(font)
        super().drawItemText(painter, rect, flags, palette, enabled, text, text_role)


class ElidingTabBar(QTabBar):
    """A tab bar that keeps every tab on screen at once, and marks the preview one.

    Each tab is capped at ``MAX_TAB_WIDTH`` with its label elided, so a long
    title takes only its share of the row instead of stretching the tab. When
    more tabs open than fit even at that width, they collapse further — down to
    an equal share of the bar — rather than disappearing behind scroll buttons.

    An empty bar still asks for the height it had while it held tabs, so a bar
    that momentarily empties doesn't collapse the row it stands in.

    One tab at a time may be the *preview* tab (:meth:`set_preview_index`), drawn
    in italic: the container replaces it on the next click rather than opening
    another beside it, and the slant is how that shows.

    Each tab carries a close button of this bar's own rather than the stock one,
    which the platform style paints red on the tab in front and pushes flush
    against its right edge. Ours is the same mark at every position, padded off
    the edge.
    """

    MAX_TAB_WIDTH = 220

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.setUsesScrollButtons(False)
        self._row_height = 0  # what one tab measured; the row an empty bar holds
        self._preview_index = -1
        self._preview_style = _PreviewTabStyle(self)  # parents itself to this bar
        self.setStyle(self._preview_style)

    # --- the preview tab ----------------------------------------------------

    def set_preview_index(self, index: int):
        """Mark the tab at ``index`` as the preview one — ``-1`` for none."""
        if index == self._preview_index:
            return
        self._preview_index = index
        self.update()

    def preview_index(self) -> int:
        """Which tab is drawn in italic, or ``-1`` when none is."""
        return self._preview_index

    def rect_is_preview_tab(self, rect) -> bool:
        """Is ``rect`` — a label about to be painted — inside the preview tab?

        Matched by position because that is all the drawing call carries; a title
        would not do, since two tabs can be named the same.
        """
        if not 0 <= self._preview_index < self.count():
            return False
        return self.tabRect(self._preview_index).contains(rect.center())

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
        button.setIcon(tab_close_icon(self))
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
