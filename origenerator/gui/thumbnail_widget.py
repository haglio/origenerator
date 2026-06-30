from pathlib import Path

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, QPoint, pyqtSignal

# A selected thumbnail lightens its whole tile — behind both the image and the
# caption — the way a file browser highlights a picked item. Two things make
# the fill actually show:
#   * WA_StyledBackground, or a plain QWidget subclass paints no stylesheet
#     background at all; and
#   * transparent child labels, or the app's global `QWidget { background-color }`
#     paints them opaque and the fill only peeks through the 4px margin as a
#     frame (which is what an earlier attempt did).
# The image also lightens its resting border a touch when selected.
_SELECTED_BG = "#3a3a3a"
_SELECTED_TILE_CSS = f"#thumbnailTile {{ background-color: {_SELECTED_BG}; border-radius: 4px; }}"
_BORDER_UNSELECTED = "2px solid #3f3f3f"
_BORDER_SELECTED = "2px solid #8a8a8a"
# Hover highlight: a blue accent marking every thumbnail that shares the hovered
# one's settings — a preview of the folder a click would carry into a new tab.
_HIGHLIGHT_BG = "#24405e"
_HIGHLIGHT_TILE_CSS = f"#thumbnailTile {{ background-color: {_HIGHLIGHT_BG}; border-radius: 4px; }}"
_BORDER_HIGHLIGHT = "2px solid #3080e0"


class ThumbnailWidget(QWidget):
    clicked = pyqtSignal(str)  # prompt_id
    context_requested = pyqtSignal(str, QPoint)  # prompt_id, global position
    hovered = pyqtSignal(str)    # prompt_id — mouse entered the tile
    unhovered = pyqtSignal(str)  # prompt_id — mouse left the tile

    def __init__(self, prompt_id: str, thumb_path: str | None, label_text: str, parent=None):
        super().__init__(parent)
        self.prompt_id = prompt_id
        self._selected = False
        self._highlighted = False
        self.setObjectName("thumbnailTile")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Take focus on click so the gallery's Delete/Ctrl+Z keys reach it even
        # when the user works entirely in the main pane, never touching the tree.
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        # Right-click anywhere on the tile asks the gallery for a context menu.
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.context_requested.emit(self.prompt_id, self.mapToGlobal(pos))
        )
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

        # Let mouse events (clicks, hover) fall through to the tile, so enter/leave
        # track the whole tile instead of flickering as the cursor crosses a child.
        self._image_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

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

    def is_highlighted(self) -> bool:
        return self._highlighted

    def set_highlighted(self, highlighted: bool):
        """Mark the tile as part of the hovered settings group (blue accent)."""
        if highlighted == self._highlighted:
            return
        self._highlighted = highlighted
        self._apply_styles()

    def _apply_styles(self):
        # Hover-highlight takes visual priority over a resting selection.
        if self._highlighted:
            self.setStyleSheet(_HIGHLIGHT_TILE_CSS)
            border = _BORDER_HIGHLIGHT
        elif self._selected:
            self.setStyleSheet(_SELECTED_TILE_CSS)
            border = _BORDER_SELECTED
        else:
            self.setStyleSheet("")
            border = _BORDER_UNSELECTED
        # Transparent background so the tile fill shows behind any letterboxing.
        self._image_label.setStyleSheet(
            f"background-color: transparent; border: {border}; border-radius: 3px;"
        )

    def enterEvent(self, event):
        self.hovered.emit(self.prompt_id)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.unhovered.emit(self.prompt_id)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        # Only a left click (re)selects. A right click opens the context menu via
        # the custom-context-menu signal and must NOT collapse a multi-selection.
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.prompt_id)
