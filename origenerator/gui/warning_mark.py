from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QLabel
from shared_ui.colors import YELLOW
from shared_ui.icons import draw_icon


class WarningMark(QLabel):
    pressed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        policy = self.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.setSizePolicy(policy)
        self.hide()

    def sizeHint(self) -> QSize:
        side = self.fontMetrics().height()
        return QSize(side, side)

    def paintEvent(self, event):
        side = min(self.width(), self.height())
        painter = QPainter(self)
        draw_icon(painter, "warning", YELLOW, size=side,
                  x=(self.width() - side) / 2, y=(self.height() - side) / 2)

    def warn(self, tip: str) -> None:
        self.setToolTip(tip)
        self.setHidden(not tip)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed.emit()
            event.accept()
        else:
            super().mousePressEvent(event)
