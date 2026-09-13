from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QLayout, QWidgetItem


class _FullRow(QWidgetItem):
    def minimumSize(self):
        return QSize(0, super().minimumSize().height())


class FlowLayout(QLayout):
    """Lay items out left-to-right, wrapping to a new row when the width runs out.

    Unlike ``QGridLayout``'s fixed column count, this fits as many items per row
    as the current width allows and reflows on resize, so a pane of fixed-size
    tiles uses the whole width instead of stopping at an arbitrary column. And
    unlike ``QHBoxLayout``, an item is always laid out at its own size hint: a row
    of buttons wraps onto a second line rather than squeezing every label down to
    an unreadable stub.

    ``align_right`` pushes each row against the right edge, for a bank of buttons
    that sits in that corner — the rows stay ragged on the left, the way a button
    bank reads, instead of walking away from the corner as it wraps.
    """

    def __init__(self, parent=None, *, margin=0, spacing=6, row_spacing=None,
                 align_right=False):
        """*row_spacing* is the gap BETWEEN wrapped rows, defaulting to *spacing*.

        They are separate because a row of buttons wants its items close and
        its rows apart: at one gap for both, two wrapped rows read as a single
        crowded block rather than as two rows.
        """
        super().__init__(parent)
        self._items = []
        self._row_spacing = spacing if row_spacing is None else row_spacing
        self._align_right = align_right
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def add_full_row(self, widget):
        self.addChildWidget(widget)
        self.addItem(_FullRow(widget))

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
            if item.isEmpty():
                continue
            size = size.expandedTo(item.minimumSize())
        return QRect(QPoint(0, 0), size).marginsAdded(self.contentsMargins()).size()

    def _do_layout(self, rect, place):
        """Flow items across ``rect``; return the total height they occupy.

        With ``place`` false, only measure (for :meth:`heightForWidth`); with it
        true, also position each item — the path Qt drives on resize. The rows are
        worked out first and placed after, because a right-aligned row cannot be
        positioned until it is known how wide it ended up.
        """
        area = rect.marginsRemoved(self.contentsMargins())
        margin_height = rect.height() - area.height()
        spacing = self.spacing()
        rows, row, x = [], [], area.x()
        for item in self._items:
            if item.isEmpty():
                continue  # a hidden widget takes no slot, and no gap where one was
            if isinstance(item, _FullRow):
                if row:
                    rows.append(row)
                rows.append([(item, QSize(area.width(), item.sizeHint().height()))])
                row, x = [], area.x()
                continue
            hint = item.sizeHint()
            if row and x + hint.width() > area.right():
                rows.append(row)            # won't fit
                row, x = [], area.x()       # wrap
            row.append((item, hint))
            x += hint.width() + spacing
        if row:
            rows.append(row)

        y = area.y()
        for placed in rows:
            x = area.x()
            if self._align_right:
                width = sum(hint.width() for _item, hint in placed) + spacing * (len(placed) - 1)
                x += max(0, area.width() - width)
            for item, hint in placed:
                if place:
                    item.setGeometry(QRect(QPoint(x, y), hint))
                x += hint.width() + spacing
            y += max(hint.height() for _item, hint in placed) + self._row_spacing
        if not rows:
            return margin_height
        return y - self._row_spacing - area.y() + margin_height
