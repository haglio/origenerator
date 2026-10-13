from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget


class WarningMark(QLabel):
    pressed = pyqtSignal()

    def __init__(self):
        super().__init__("⚠")
        self.setObjectName("warningMark")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        policy = self.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.setSizePolicy(policy)
        self.hide()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed.emit()
        super().mousePressEvent(event)


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
