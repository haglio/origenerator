from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from origenerator.gui.tile_rules import STATUS_SCRIM


class TileStatusScrim(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setObjectName(STATUS_SCRIM)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

    def cover(self, widget: QLabel, message: str | None, *, inset: int = 0):
        self.setGeometry(widget.geometry().adjusted(inset, inset, -inset, -inset))
        self.setText(message or "")
        self.setVisible(bool(message))
        if message:
            self.raise_()
