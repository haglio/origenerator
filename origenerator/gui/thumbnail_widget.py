from pathlib import Path

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, pyqtSignal

# A selected thumbnail lightens its whole tile — behind both the image and the
# caption — the way a file browser highlights a picked item. Two things make
# the fill actually show:
#   * WA_StyledBackground, or a plain QWidget subclass paints no stylesheet
#     background at all; and
#   * transparent child labels, or the app's global `QWidget { background-color }`
#     paints them opaque and the fill only peeks through the 4px margin as a
#     frame (which is what an earlier attempt did).
# The image also lightens its resting border a touch when selected.
_SELECTED_BG = "#4a4a4a"
_SELECTED_TILE_CSS = f"#thumbnailTile {{ background-color: {_SELECTED_BG}; border-radius: 4px; }}"
_BORDER_UNSELECTED = "2px solid #3f3f3f"
_BORDER_SELECTED = "2px solid #8a8a8a"


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
        # Transparent so the tile's fill shows through behind the caption.
        self._text_label.setStyleSheet("background-color: transparent;")

        layout.addWidget(self._image_label)
        layout.addWidget(self._text_label)
        self._apply_styles()

    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool):
        """Lighten the whole tile when selected; restore the resting look when not."""
        if selected == self._selected:
            return  # idempotent: skip restyling thumbnails a click didn't move
        self._selected = selected
        self._apply_styles()

    def _apply_styles(self):
        self.setStyleSheet(_SELECTED_TILE_CSS if self._selected else "")
        border = _BORDER_SELECTED if self._selected else _BORDER_UNSELECTED
        # Transparent background so the tile fill shows behind any letterboxing.
        self._image_label.setStyleSheet(
            f"background-color: transparent; border: {border}; border-radius: 3px;"
        )

    def mousePressEvent(self, event):
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.clicked.emit(self.prompt_id)
