from PyQt6.QtWidgets import QLayout
from PyQt6.QtCore import Qt, QSize, QRect, QPoint


class FlowLayout(QLayout):
    """Lay items out left-to-right, wrapping to a new row when the width runs out.

    Unlike ``QGridLayout``'s fixed column count, this fits as many items per row
    as the current width allows and reflows on resize, so a pane of fixed-size
    tiles uses the whole width instead of stopping at an arbitrary column.
    """

    def __init__(self, parent=None, *, margin=0, spacing=6):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), place=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, place=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(),
                      margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect, place):
        """Flow items across ``rect``; return the total height they occupy.

        With ``place`` false, only measure (for :meth:`heightForWidth`); with it
        true, also position each item — the path Qt drives on resize.
        """
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(),
                             -margins.right(), -margins.bottom())
        spacing = self.spacing()
        x, y, row_height = area.x(), area.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x > area.x() and x + hint.width() > area.right():
                x = area.x()                     # this item won't fit; wrap
                y += row_height + spacing
                row_height = 0
            if place:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + spacing
            row_height = max(row_height, hint.height())
        return y + row_height - rect.y() + margins.bottom()
