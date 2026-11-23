from __future__ import annotations

from PySide6.QtWidgets import QLabel

DELTA = "\u0394"


class ChangeMark(QLabel):
    def __init__(self, parent=None):
        super().__init__(DELTA, parent)
        self.setStyleSheet("font-weight: bold;")
        self.hide()

    def show_change(self, tip: str) -> None:
        self.setToolTip(tip)
        self.setVisible(bool(tip))
