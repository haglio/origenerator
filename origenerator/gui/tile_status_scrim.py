from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel
from shared_ui.palette import BLACK, WHITE, as_hex, as_rgba
from shared_ui.spacing import BUTTON_RADIUS

_TILE_STATUS_SCRIM_CSS = (
    f"background-color: {as_rgba(BLACK, 0.45)}; color: {as_hex(WHITE)};"
    f" font-weight: bold; border-radius: {BUTTON_RADIUS}px;"
)


class TileStatusScrim(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setStyleSheet(_TILE_STATUS_SCRIM_CSS)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

    def cover(self, widget: QLabel, message: str | None, *, inset: int = 0):
        self.setGeometry(widget.geometry().adjusted(inset, inset, -inset, -inset))
        self.setText(message or "")
        self.setVisible(bool(message))
        if message:
            self.raise_()
