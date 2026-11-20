from __future__ import annotations

from PySide6.QtCore import QEvent, QSize
from PySide6.QtWidgets import QScrollArea, QSizePolicy, QWidget


class FittingScroll(QScrollArea):
    def __init__(self, content: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setWidget(content)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        content.installEventFilter(self)

    def sizeHint(self) -> QSize:  # noqa: N802 -- Qt's name
        content = self.widget()
        hint = content.sizeHint()
        return hint if hint.isValid() else content.size()

    def eventFilter(self, watched, event):  # noqa: N802 -- Qt's name
        if event.type() in (QEvent.Type.LayoutRequest, QEvent.Type.Resize):
            self.updateGeometry()
        return super().eventFilter(watched, event)
