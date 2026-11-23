from __future__ import annotations

from PySide6.QtCore import QRect, QSize
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget
from shared_ui.spacing import GAP_SMALL

from origenerator.gui.warning_mark import WarningMark


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
