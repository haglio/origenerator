"""The ``+`` leading a gallery settings folder: a fresh generation of the folder's
settings with a new seed.

While the folder is making one it stays where it is, grayed out, and the run gets
a tile of its own (:class:`~origenerator.gui.generating_tile.GeneratingTile`).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

from origenerator.gui import tile_shape
from origenerator.gui.inflight import ALREADY_MAKING_ONE_TIP

_MARK_PX = 56


class NewTile(QFrame):
    add_requested = pyqtSignal()

    def __init__(self, parent=None, *, making_one=False):
        super().__init__(parent)
        self.setObjectName("newTile")
        self.setFixedSize(*tile_shape.tile_size())
        self.setStyleSheet(tile_shape.idle_css("newTile"))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*(tile_shape.TILE_MARGIN,) * 4)
        layout.setSpacing(tile_shape.TILE_SPACING)

        self._glyph = tile_shape.MarkPlate("plus", side=_MARK_PX)
        layout.addWidget(self._glyph)

        self._caption = QLabel("New (random seed)")
        self._caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._caption.setWordWrap(True)
        tile_shape.style_caption(self._caption)
        layout.addWidget(self._caption)

        if making_one:
            self.setEnabled(False)
            self.setToolTip(ALREADY_MAKING_ONE_TIP)
            self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation, True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.add_requested.emit()
