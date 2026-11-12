from __future__ import annotations

import shiboken6
from PySide6.QtCore import QRect, QSize
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QWidget

from origenerator.gui.warning_mark import WarningMark
from origenerator.gui.widget_size import QWIDGETSIZE_MAX


class LabelColumn:
    def __init__(self):
        self._cells: list[LabelCell] = []
        self._room = QWIDGETSIZE_MAX
        self._floor = 0

    def join(self, cell: LabelCell) -> None:
        self._cells.append(cell)

    def natural_width(self) -> int:
        return max((cell.natural_width() for cell in self._living()), default=0)

    def _living(self) -> list[LabelCell]:
        self._cells = [cell for cell in self._cells if shiboken6.isValid(cell)]
        return self._cells

    def width(self) -> int:
        return min(max(self.natural_width(), self._floor), self._room)

    def widen_to(self, floor: int) -> None:
        if floor == self._floor:
            return
        self._floor = floor
        for cell in self._living():
            cell.updateGeometry()

    def fit_in(self, room: int) -> None:
        if room == self._room:
            return
        self._room = room
        for cell in self._living():
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
        # Qt's QFormLayout gives its labels the widest one's width when a row fits beside its field and no width at all when none does.
        # Qt's QFormLayout keeps a section's labels whole while any one of its fields still fits beside them, and squeezes the rest.
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
