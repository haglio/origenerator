from __future__ import annotations

from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QHBoxLayout, QWidget

from origenerator.gui.warning_mark import WarningMark


class LabelColumn:
    def __init__(self):
        self._cells: list[LabelCell] = []

    def join(self, cell: LabelCell) -> None:
        self._cells.append(cell)

    def width(self) -> int:
        return max(cell.natural_width() for cell in self._cells)


class LabelCell(QWidget):
    def __init__(self, mark: WarningMark, label: QWidget, column: LabelColumn):
        super().__init__()
        self._column = column
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(mark)
        row.addStretch(1)
        row.addWidget(label)
        column.join(self)

    def natural_width(self) -> int:
        return self.layout().sizeHint().width()

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(self._column.width(), hint.height())
