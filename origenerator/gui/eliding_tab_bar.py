from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QProxyStyle, QStyle, QTabBar, QToolButton
from shared_ui.spacing import GAP_MEDIUM, MARGIN_STANDARD

from origenerator.gallery.item_numbers import widest_item_name
from origenerator.gui.icons import tab_close_icon

_CLOSE_PADDING = GAP_MEDIUM

EDGE = MARGIN_STANDARD

# Qt's tab layout puts the label a fixed _QT_LABEL_GAP after the icon, so the
# mark's canvas carries the rest of the label gap as transparency.
MARK = 20
_QT_LABEL_GAP = 4  # QCommonStylePrivate::tabLayout's, not ours to set
MARK_CANVAS = QSize(MARK + EDGE - _QT_LABEL_GAP, MARK)


def tab_mark(icon: QIcon) -> QIcon:
    if icon.isNull():
        return icon
    # Ask big, then fill: QIcon won't scale a pixmap up, so this is whatever the
    # source actually has, at its own shape.
    source = icon.pixmap(QSize(MARK * 8, MARK * 8))
    if source.isNull():
        return icon
    filled = source.scaled(MARK, MARK, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
    canvas = QPixmap(MARK_CANVAS)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.drawPixmap(0, 0, filled, (filled.width() - MARK) // 2,
                       (filled.height() - MARK) // 2, MARK, MARK)
    painter.end()
    return QIcon(canvas)


class _PreviewTabStyle(QProxyStyle):
    """Draws one tab's label slanted.

    ``QStyleOptionTab`` carries no font, and the app's stylesheet overwrites a font set on the
    bar at every polish, so the slant is applied in ``drawItemText``, which receives each label's rect.
    """

    def __init__(self, bar: ElidingTabBar):
        super().__init__()
        self._bar = bar
        # QProxyStyle takes ownership of a parentless base style, which a stylesheet
        # then re-wraps and deletes out from under Python.
        self.setParent(bar)

    def drawItemText(self, painter, rect, *the_rest):
        font = painter.font()
        italic = self._bar.rect_is_preview_tab(rect)
        if font.italic() != italic:
            font.setItalic(italic)
            painter.setFont(font)
        super().drawItemText(painter, rect, *the_rest)


class ElidingTabBar(QTabBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.setUsesScrollButtons(False)
        self._row_height = 0
        self._preview_index = -1
        self._preview_style = _PreviewTabStyle(self)
        self.setStyle(self._preview_style)

    def set_preview_index(self, index: int):
        if index == self._preview_index:
            return
        self._preview_index = index
        self.update()

    def rect_is_preview_tab(self, rect) -> bool:
        if not 0 <= self._preview_index < self.count():
            return False
        return self.tabRect(self._preview_index).contains(rect.center())

    def sizeHint(self):
        size = super().sizeHint()
        if self.count() > 0:
            self._row_height = size.height()
        else:
            size.setHeight(self._row_height)
        return size

    def minimumSizeHint(self):
        size = super().minimumSizeHint()
        size.setWidth(0)
        if self.count() == 0:
            size.setHeight(self._row_height)
        return size

    def tabSizeHint(self, index):
        size = super().tabSizeHint(index)
        metrics = self.fontMetrics()
        room = (size.width() - metrics.horizontalAdvance(self.tabText(index))
                + metrics.horizontalAdvance(widest_item_name(metrics.horizontalAdvance)))
        size.setWidth(min(size.width(), room))
        return size

    def minimumTabSizeHint(self, index):
        size = super().minimumTabSizeHint(index)
        if self.count() > 0 and self.width() > 0:
            size.setWidth(min(size.width(), self.width() // self.count()))
        return size

    def tabInserted(self, index: int):
        super().tabInserted(index)
        if self.tabsClosable():
            self.setTabButton(index, QTabBar.ButtonPosition.RightSide,
                              self._close_button())

    def _close_button(self) -> QToolButton:
        mark = self.style().pixelMetric(QStyle.PixelMetric.PM_TabCloseIndicatorWidth)
        button = QToolButton(self)
        button.setObjectName("tabCloseButton")
        button.setIcon(tab_close_icon())
        button.setIconSize(QSize(mark, mark))
        button.setFixedSize(mark + _CLOSE_PADDING, mark)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip("Close this tab")
        button.clicked.connect(lambda _=False, b=button: self._close_clicked(b))
        return button

    def _close_clicked(self, button):
        for index in range(self.count()):
            if self.tabButton(index, QTabBar.ButtonPosition.RightSide) is button:
                self.tabCloseRequested.emit(index)
                return

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton and self.tabsClosable():
            index = self.tabAt(event.position().toPoint())
            if index >= 0:
                self.tabCloseRequested.emit(index)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        # Qt 6.11 closes a tab on this release itself, which after the press above
        # would be a second tab: the row has shifted under the cursor by then.
        if event.button() == Qt.MouseButton.MiddleButton:
            event.accept()
            return
        super().mouseReleaseEvent(event)
