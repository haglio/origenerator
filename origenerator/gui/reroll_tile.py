"""The ``+`` leading a gallery settings folder: a fresh generation of the folder's
settings with a new seed.

While the folder is making one it stays where it is, grayed out, and the run gets
a tile of its own (:class:`~origenerator.gui.generating_tile.GeneratingTile`).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

from origenerator.gui import grid_card
from origenerator.gui.inflight import ALREADY_MAKING_ONE_TIP


class RerollTile(QFrame):
    add_requested = pyqtSignal()

    def __init__(self, parent=None, *, making_one=False):
        super().__init__(parent)
        self.setObjectName("rerollTile")
        self.setFixedSize(*grid_card.card_size())
        self.setStyleSheet(grid_card.idle_css("rerollTile"))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*(grid_card.CARD_MARGIN,) * 4)
        layout.setSpacing(grid_card.CARD_SPACING)

        self._glyph = QLabel("+")
        self._glyph.setFixedSize(*grid_card.PICTURE_SIZE)
        self._glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._glyph.setStyleSheet(grid_card.glyph_css())
        layout.addWidget(self._glyph)

        self._caption = QLabel("New (random seed)")
        self._caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._caption.setWordWrap(True)
        grid_card.style_caption(self._caption)
        layout.addWidget(self._caption)

        if making_one:
            self.setEnabled(False)
            self.setToolTip(ALREADY_MAKING_ONE_TIP)
            self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation, True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.add_requested.emit()
