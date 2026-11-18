from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QLayout, QWidget, QWidgetItem
from shared_ui.spacing import GAP_SMALL

from origenerator.gui.warning_mark import WarningMark


class _FullRow(QWidgetItem):
    def minimumSize(self):
        return QSize(0, super().minimumSize().height())


class _Trailing(QWidgetItem):
    pass


class _Grouped(QWidgetItem):
    def __init__(self, widget, group: int):
        super().__init__(widget)
        self.group = group


class FlowLayout(QLayout):
    def __init__(self, parent=None, *, margin=0, spacing=6, row_spacing=None,
                 group_spacing=None, align_right=False):
        super().__init__(parent)
        self._items = []
        self._groups_added = 0
        self._row_spacing = spacing if row_spacing is None else row_spacing
        self._group_spacing = spacing if group_spacing is None else group_spacing
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

    def group_spacing(self) -> int:
        return self._group_spacing

    def set_group_spacing(self, spacing: int) -> None:
        self._group_spacing = spacing
        self.invalidate()

    def add_group(self, widgets):
        self._groups_added += 1
        for widget in widgets:
            self.addChildWidget(widget)
            self.addItem(_Grouped(widget, self._groups_added))

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
        rows = self._rows(area)
        y = area.y()
        for placed in rows:
            leading = _closed_up([entry for entry in placed if not isinstance(entry[0], _Trailing)])
            trailing = _closed_up([entry for entry in placed if isinstance(entry[0], _Trailing)])
            x = area.x()
            if self._align_right:
                x += max(0, area.width() - _width_of(placed))
            for run, run_x in ((leading, x),
                               (trailing, area.x() + max(0, area.width() - _width_of(trailing)))):
                start = run_x
                for item, hint, before in run:
                    start += before
                    if place:
                        item.setGeometry(QRect(QPoint(start, y), hint))
                    start += hint.width()
            y += max(hint.height() for _item, hint, _gap in placed) + self._row_spacing
        if not rows:
            return margin_height
        return y - self._row_spacing - area.y() + margin_height

    def _rows(self, area):
        right = area.x() + area.width()
        rows, row, x = [], [], area.x()
        for unit, gap in self._units(area.width()):
            if isinstance(unit[0][0], _FullRow):
                if row:
                    rows.append(row)
                item = unit[0][0]
                rows.append([(item, QSize(area.width(), item.sizeHint().height()), 0)])
                row, x = [], area.x()
                continue
            width = _span_of(unit, self.spacing())
            if row and x + gap + width > right:
                rows.append(row)
                row, x = [], area.x()
            for index, (item, hint) in enumerate(unit):
                before = (gap if index == 0 else self.spacing()) if row else 0
                if row and x + before + hint.width() > right:
                    rows.append(row)
                    row, x, before = [], area.x(), 0
                row.append((item, hint, before))
                x += before + hint.width()
        if row:
            rows.append(row)
        return rows

    def _units(self, width: int):
        units, previous_group = [], None
        for item in self._items:
            if item.isEmpty():
                continue
            group = item.group if isinstance(item, _Grouped) else None
            entry = (item, _hint_within(item, width))
            if group is not None and group == previous_group:
                units[-1][0].append(entry)
            else:
                between_groups = group is not None and previous_group is not None
                units.append(([entry], self._group_spacing if between_groups else self.spacing()))
            previous_group = group
        return units


def _hint_within(item, width: int) -> QSize:
    hint = item.sizeHint()
    hint.setWidth(min(hint.width(), max(width, item.minimumSize().width())))
    if item.hasHeightForWidth():
        hint.setHeight(item.heightForWidth(hint.width()))
    return hint


def _span_of(unit, spacing) -> int:
    return sum(hint.width() for _item, hint in unit) + spacing * max(0, len(unit) - 1)


def _closed_up(run):
    return [(item, hint, before if index else 0) for index, (item, hint, before) in enumerate(run)]


def _width_of(placed) -> int:
    return sum(hint.width() + before for _item, hint, before in _closed_up(placed))


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
