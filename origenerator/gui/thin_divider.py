from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
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

    def shown_with(self, widget: QWidget) -> ThinDivider:
        _ShownWith(self, widget)
        return self


class _ShownWith(QObject):
    def __init__(self, divider: QWidget, widget: QWidget):
        super().__init__(divider)
        self._divider = divider
        widget.installEventFilter(self)
        divider.setVisible(not widget.isHidden())

    def eventFilter(self, watched, event):  # noqa: N802 -- Qt's name
        if event.type() in (QEvent.Type.ShowToParent, QEvent.Type.HideToParent):
            self._divider.setVisible(not watched.isHidden())
        return False


def across() -> ThinDivider:
    return ThinDivider(Qt.Orientation.Horizontal)


def upright() -> ThinDivider:
    return ThinDivider(Qt.Orientation.Vertical)
