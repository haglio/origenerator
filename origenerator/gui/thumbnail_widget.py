from pathlib import Path

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, pyqtSignal

# A selected thumbnail fills its whole tile — behind both the image and the
# caption — with a lighter grey, the way a file browser highlights a picked
# item. The fill is an object-name rule on the tile and needs
# WA_StyledBackground: a plain QWidget subclass won't paint a stylesheet
# background otherwise (which is why an earlier tile-border attempt was
# invisible). The image keeps a fixed resting frame; the fill is the cue.
_SELECTED_BG = "#4a4a4a"
_SELECTED_TILE_CSS = (
    f"#thumbnailTile {{ background-color: {_SELECTED_BG}; border-radius: 4px; }}"
)


class ThumbnailWidget(QWidget):
    clicked = pyqtSignal(str)  # prompt_id

    def __init__(self, prompt_id: str, thumb_path: str | None, label_text: str, parent=None):
        super().__init__(parent)
        self.prompt_id = prompt_id
        self._selected = False
        self.setObjectName("thumbnailTile")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Take focus on click so the gallery's Delete/Ctrl+Z keys reach it even
        # when the user works entirely in the main pane, never touching the tree.
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setFixedSize(180, 200)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self._image_label = QLabel()
        self._image_label.setFixedSize(172, 160)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet("border: 1px solid #3f3f3f; border-radius: 3px;")

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
        """Fill the whole tile when selected; clear the fill when not."""
        if selected == self._selected:
            return  # idempotent: skip restyling thumbnails a click didn't move
        self._selected = selected
        self.setStyleSheet(_SELECTED_TILE_CSS if selected else "")

    def mousePressEvent(self, event):
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.clicked.emit(self.prompt_id)
