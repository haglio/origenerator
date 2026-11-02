from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QGridLayout, QLabel, QLayout, QWidget, QWidgetItem
from shared_ui.spacing import GAP_SMALL

from origenerator.gui.warning_mark import WarningMark


class _FullRow(QWidgetItem):
    def minimumSize(self):
        return QSize(0, super().minimumSize().height())


class _Trailing(QWidgetItem):
    pass


class FlowLayout(QLayout):
    def __init__(self, parent=None, *, margin=0, spacing=6, row_spacing=None,
                 align_right=False):
        super().__init__(parent)
        self._items = []
        self._row_spacing = spacing if row_spacing is None else row_spacing
        self._align_right = align_right
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def row_spacing(self) -> int:
        return self._row_spacing

    def set_row_spacing(self, spacing: int) -> None:
        self._row_spacing = spacing
        self.invalidate()

    def addItem(self, item):
        self._items.append(item)

    def add_full_row(self, widget):
        self.addChildWidget(widget)
        self.addItem(_FullRow(widget))

    def add_trailing(self, widget):
        self.addChildWidget(widget)
        self.addItem(_Trailing(widget))

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
        area = rect.marginsRemoved(self.contentsMargins())
        margin_height = rect.height() - area.height()
        spacing = self.spacing()
        rows, row, x = [], [], area.x()
        for item in self._items:
            if item.isEmpty():
                continue
            if isinstance(item, _FullRow):
                if row:
                    rows.append(row)
                rows.append([(item, QSize(area.width(), item.sizeHint().height()))])
                row, x = [], area.x()
                continue
            hint = item.sizeHint()
            hint.setWidth(min(hint.width(), max(area.width(), item.minimumSize().width())))
            if row and x + hint.width() > area.right():
                rows.append(row)
                row, x = [], area.x()
            row.append((item, hint))
            x += hint.width() + spacing
        if row:
            rows.append(row)

        y = area.y()
        for placed in rows:
            leading = [(item, hint) for item, hint in placed if not isinstance(item, _Trailing)]
            trailing = [(item, hint) for item, hint in placed if isinstance(item, _Trailing)]
            x = area.x()
            if self._align_right:
                x += max(0, area.width() - _span_of(placed, spacing))
            for run, run_x in ((leading, x),
                               (trailing, area.x() + max(0, area.width() - _span_of(trailing, spacing)))):
                start = run_x
                for item, hint in run:
                    if place:
                        item.setGeometry(QRect(QPoint(start, y), hint))
                    start += hint.width() + spacing
            y += max(hint.height() for _item, hint in placed) + self._row_spacing
        if not rows:
            return margin_height
        return y - self._row_spacing - area.y() + margin_height


def _span_of(placed, spacing) -> int:
    return sum(hint.width() for _item, hint in placed) + spacing * max(0, len(placed) - 1)


def _narrowest(widget: QWidget) -> int:
    hint = widget.minimumSizeHint()
    return widget.minimumWidth() or hint.width()


class FieldGrid(QGridLayout):
    """Fields beside one column of captions, its warning marks in a column left of it.

    A layout, because Qt asks a widget's layout for its height at a width, never the widget."""

    def __init__(self, dropdowns: list[tuple[QLabel, QWidget]],
                 numbers: list[tuple[QLabel, QWidget]], marks: dict[QLabel, WarningMark]):
        super().__init__()
        self._dropdowns = dropdowns
        self._numbers = numbers
        self._marks = marks
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(GAP_SMALL)
        self._stacked: bool | None = None
        self._arrange(stacked=False)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        lines = [[pair] for pair in self._dropdowns]
        if width < self._one_line_width():
            lines += [[pair] for pair in self._numbers]
        else:
            lines.append(self._numbers)
        heights = [max(max(label.sizeHint().height(), field.sizeHint().height())
                       for label, field in line) for line in lines]
        return sum(heights) + (len(heights) - 1) * self.verticalSpacing()

    def sizeHint(self) -> QSize:
        width = self._one_line_width()
        return QSize(width, self.heightForWidth(width))

    def minimumSize(self) -> QSize:
        pairs = self._dropdowns + self._numbers
        narrowest = (self._mark_column()
                     + max(label.sizeHint().width() for label, _field in pairs)
                     + self.horizontalSpacing()
                     + max(_narrowest(field) for _label, field in pairs))
        return QSize(narrowest, self.heightForWidth(self._one_line_width()))

    def setGeometry(self, rect: QRect) -> None:
        self._arrange(stacked=rect.width() < self._one_line_width())
        super().setGeometry(rect)

    def _mark_column(self) -> int:
        return (max(self._marks[label].sizeHint().width() for label in self._marks)
                + self.horizontalSpacing())

    def _one_line_width(self) -> int:
        captions = max(label.sizeHint().width()
                       for label, _field in self._dropdowns + self._numbers[:1])
        return (self._mark_column() + captions
                + sum(label.sizeHint().width() for label, _field in self._numbers[1:])
                + sum(_narrowest(field) for _label, field in self._numbers)
                + self.horizontalSpacing() * (2 * len(self._numbers) - 1))

    def _arrange(self, stacked: bool) -> None:
        if stacked == self._stacked:
            return
        for column in range(self.columnCount()):
            self.setColumnStretch(column, 0)
        span = 1 if stacked else 2 * len(self._numbers) - 1
        for row, (label, field) in enumerate(self._dropdowns):
            if label in self._marks:
                self.addWidget(self._marks[label], row, 0)
            self.addWidget(label, row, 1)
            self.addWidget(field, row, 2, 1, span)
        below = len(self._dropdowns)
        for index, (label, field) in enumerate(self._numbers):
            row, column = (below + index, 1) if stacked else (below, 1 + 2 * index)
            self.addWidget(label, row, column)
            self.addWidget(field, row, column + 1)
            self.setColumnStretch(column + 1, 1)
        self._stacked = stacked
