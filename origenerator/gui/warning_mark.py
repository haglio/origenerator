from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel


class WarningMark(QLabel):
    pressed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("⚠", parent)
        self.setObjectName("warningMark")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        policy = self.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.setSizePolicy(policy)
        self.hide()

    def warn(self, tip: str) -> None:
        self.setToolTip(tip)
        self.setHidden(not tip)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed.emit()
            event.accept()
        else:
            super().mousePressEvent(event)
