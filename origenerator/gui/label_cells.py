from __future__ import annotations

from PyQt6.QtCore import QRect, QSize
from PyQt6.QtWidgets import QWIDGETSIZE_MAX, QFormLayout, QHBoxLayout, QWidget

from origenerator.gui.warning_mark import WarningMark


class LabelColumn:
    def __init__(self):
        self._cells: list[LabelCell] = []
        self._room = QWIDGETSIZE_MAX

    def join(self, cell: LabelCell) -> None:
        self._cells.append(cell)

    def width(self) -> int:
        return min(max(cell.natural_width() for cell in self._cells), self._room)

    def fit_in(self, room: int) -> None:
        if room == self._room:
            return
        self._room = room
        for cell in self._cells:
            cell.updateGeometry()


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


class LabelForm(QFormLayout):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.label_column = LabelColumn()
        self.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

    def setGeometry(self, rect: QRect) -> None:
        self.label_column.fit_in(self._room_for_labels(rect.width()))
        super().setGeometry(rect)

    def _room_for_labels(self, width: int) -> int:
        margins = self.contentsMargins()
        widest_field = max((self.itemAt(row, QFormLayout.ItemRole.FieldRole).minimumSize().width()
                            for row in range(self.rowCount()) if self._labels_a_field(row)),
                           default=0)
        return (width - margins.left() - margins.right() - self.horizontalSpacing()
                - widest_field)

    def _labels_a_field(self, row: int) -> bool:
        return (self.isRowVisible(row)
                and self.itemAt(row, QFormLayout.ItemRole.LabelRole) is not None
                and self.itemAt(row, QFormLayout.ItemRole.FieldRole) is not None)
