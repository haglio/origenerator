from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from shared_ui.fonts import wordmark_font
from shared_ui.palette import as_hex
from shared_ui.preview import Preview, window_title
from shared_ui.spacing import BUTTON_GAP, BUTTON_SIZE, MARGIN_STANDARD
from shared_ui.wordmark import wordmark_ink


class AppTitle(QWidget):
    def __init__(self, name: str, icon: QIcon, preview: Preview | None, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(MARGIN_STANDARD, MARGIN_STANDARD, MARGIN_STANDARD, 0)
        row.setSpacing(BUTTON_GAP)
        self.logo = QLabel()
        self.logo.setPixmap(icon.pixmap(BUTTON_SIZE, BUTTON_SIZE))
        self.name = QLabel(name)
        self.name.setFont(wordmark_font())
        self.name.setStyleSheet(f"color: {as_hex(wordmark_ink(preview))};")
        row.addWidget(self.logo)
        row.addWidget(self.name)
        row.addStretch(1)
        if preview is not None:
            self.setToolTip(window_title(name, preview))


def under(title: AppTitle, content: QWidget) -> QWidget:
    stacked = QWidget()
    column = QVBoxLayout(stacked)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(0)
    column.addWidget(title)
    column.addWidget(content, 1)
    return stacked
