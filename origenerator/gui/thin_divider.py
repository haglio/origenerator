from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QSizePolicy, QWidget
from shared_ui.colors import BG_SECONDARY
from shared_ui.spacing import HAIRLINE

THIN_DIVIDER = "thinDivider"
THIN_DIVIDER_COLOR = BG_SECONDARY


class ThinDivider(QFrame):
    def __init__(self, orientation: Qt.Orientation, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName(THIN_DIVIDER)
        if orientation == Qt.Orientation.Horizontal:
            self.setFixedHeight(HAIRLINE)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        else:
            self.setFixedWidth(HAIRLINE)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)


def across() -> ThinDivider:
    return ThinDivider(Qt.Orientation.Horizontal)
