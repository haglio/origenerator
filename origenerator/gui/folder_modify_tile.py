from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

from origenerator.gui import tile_shape

_IDLE_FRAME_CSS = tile_shape.idle_css("folderModifyTile")

_MARK_PX = 48

_CAPTION = "Modify batch (all seeds)"
_TOOLTIP = (
    "Rewrite this folder's prompt and run every image in it again with the same "
    "seed, so the new folder is this one said differently."
)


class FolderModifyTile(QFrame):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("folderModifyTile")
        self.setFixedSize(*tile_shape.tile_size())
        self.setStyleSheet(_IDLE_FRAME_CSS)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(_TOOLTIP)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*(tile_shape.TILE_MARGIN,) * 4)
        layout.setSpacing(tile_shape.TILE_SPACING)

        self._glyph = tile_shape.MarkPlate("pencil", side=_MARK_PX)
        layout.addWidget(self._glyph)

        self._caption = QLabel(_CAPTION)
        self._caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._caption.setWordWrap(True)
        tile_shape.style_caption(self._caption)
        layout.addWidget(self._caption)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
