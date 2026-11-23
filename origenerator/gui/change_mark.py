from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolButton
from shared_ui.icon_button import fill_square_with_icon
from shared_ui.icons import qt_icon
from shared_ui.spacing import BUTTON_SIZE_HUD


class ChangeMark(QToolButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        fill_square_with_icon(self, size=BUTTON_SIZE_HUD)
        self.setIcon(qt_icon("delta"))
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.hide()

    def show_change(self, tip: str) -> None:
        self.setToolTip(tip)
        self.setVisible(bool(tip))
