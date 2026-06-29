from pathlib import Path

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, pyqtSignal

# The image border doubles as the selection cue: a faint, lighter grey when the
# thumbnail is selected, the usual dark frame otherwise. Both are 2px so the
# picture never shifts as selection toggles. The border lives on the image
# QLabel, not the tile QWidget — a plain QWidget subclass won't paint a
# stylesheet border without WA_StyledBackground, so a tile-level border would
# silently render nothing.
_BORDER_UNSELECTED = "2px solid #3f3f3f"
_BORDER_SELECTED = "2px solid #8a8a8a"


class ThumbnailWidget(QWidget):
    clicked = pyqtSignal(str)  # prompt_id

    def __init__(self, prompt_id: str, thumb_path: str | None, label_text: str, parent=None):
        super().__init__(parent)
        self.prompt_id = prompt_id
        self._selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(180, 200)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self._image_label = QLabel()
        self._image_label.setFixedSize(172, 160)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._apply_border()

        if thumb_path and Path(thumb_path).exists():
            pm = QPixmap(str(thumb_path))
            self._image_label.setPixmap(
                pm.scaled(172, 160, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            self._image_label.setText("No preview")

        self._text_label = QLabel(label_text)
        self._text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text_label.setWordWrap(True)
        self._text_label.setMaximumHeight(30)

        layout.addWidget(self._image_label)
        layout.addWidget(self._text_label)

    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool):
        """Toggle the selection highlight on this thumbnail's image border."""
        if selected == self._selected:
            return  # idempotent: skip restyling thumbnails a click didn't move
        self._selected = selected
        self._apply_border()

    def _apply_border(self):
        border = _BORDER_SELECTED if self._selected else _BORDER_UNSELECTED
        self._image_label.setStyleSheet(f"border: {border}; border-radius: 3px;")

    def mousePressEvent(self, event):
        self.clicked.emit(self.prompt_id)
