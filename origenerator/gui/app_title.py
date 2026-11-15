from __future__ import annotations

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from shared_ui.palette import LOADING_ACCENT, PREVIEW_INK, as_hex
from shared_ui.preview import Preview, window_title
from shared_ui.spacing import BUTTON_GAP, BUTTON_SIZE, MARGIN_STANDARD
from shared_ui.type_scale import FONT_UI, SIZE_BODY


class AppTitle(QWidget):
    def __init__(self, name: str, icon: QIcon, preview: Preview | None, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(MARGIN_STANDARD, MARGIN_STANDARD, MARGIN_STANDARD, 0)
        row.setSpacing(BUTTON_GAP)
        self.logo = QLabel()
        self.logo.setPixmap(icon.pixmap(BUTTON_SIZE, BUTTON_SIZE))
        self.name = QLabel(name)
        lettering = QFont(FONT_UI, SIZE_BODY)
        lettering.setBold(True)
        lettering.setItalic(True)
        self.name.setFont(lettering)
        ink = LOADING_ACCENT if preview is None else PREVIEW_INK
        self.name.setStyleSheet(f"color: {as_hex(ink)};")
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
