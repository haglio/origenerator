"""The other trailing card in a settings folder: ask for the same thing, said
differently.

The re-roll card beside it keeps the words and changes the seed. This one is its
mirror — it keeps the seeds and changes the words, running the folder again with
the prompt rewritten, so what comes back is the same set of images said another
way rather than a new set of images.

Pressing it launches nothing: it opens a config tab where the folder's own
prompt is there to be edited by hand, the folder's images filling the preview
above it.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

from origenerator.gui import grid_card

_IDLE_FRAME_CSS = grid_card.idle_css("folderModifyTile")

# A pencil rather than a plus: the card next door makes another one of these, and
# this one writes on them.
_MARK_PX = 48

_CAPTION = "Modify (all seeds)"
_TOOLTIP = (
    "Rewrite this folder's prompt and run every image in it again with the same "
    "seed, so the new folder is this one said differently."
)


class FolderModifyTile(QFrame):
    """A card that opens this folder's prompt for a rewrite."""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("folderModifyTile")
        self.setFixedSize(*grid_card.card_size())
        self.setStyleSheet(_IDLE_FRAME_CSS)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(_TOOLTIP)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*(grid_card.CARD_MARGIN,) * 4)
        layout.setSpacing(grid_card.CARD_SPACING)

        self._glyph = grid_card.MarkPlate("pencil", side=_MARK_PX)
        layout.addWidget(self._glyph)

        self._caption = QLabel(_CAPTION)
        self._caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._caption.setWordWrap(True)
        grid_card.style_caption(self._caption)  # the grid's shared caption size
        layout.addWidget(self._caption)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
