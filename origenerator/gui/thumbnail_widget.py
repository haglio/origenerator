from pathlib import Path

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QApplication
from PyQt6.QtGui import QPixmap, QDrag
from PyQt6.QtCore import Qt, QPoint, QSize, QMimeData, QByteArray, pyqtSignal

from origenerator.gui.looping_preview import looping_movie
from origenerator.gui.media_badge import MediaBadge

_IMAGE_SIZE = QSize(172, 160)  # the thumbnail image area, inside the 180x200 tile

# A dragged thumbnail carries its generation's prompt_id under this type, which the
# gallery's combine drop slots read to know which image or video was dropped.
GENERATION_MIME = "application/x-origenerator-generation"


def generation_mime(prompt_id: str) -> QMimeData:
    """The drag payload naming a generation by prompt_id, for a drop slot to read."""
    mime = QMimeData()
    mime.setData(GENERATION_MIME, QByteArray(prompt_id.encode("utf-8")))
    return mime

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
    double_clicked = pyqtSignal(str)  # prompt_id — an "open" gesture
    context_requested = pyqtSignal(str, QPoint)  # prompt_id, global position
    hovered = pyqtSignal(str)    # prompt_id — mouse entered the tile
    unhovered = pyqtSignal(str)  # prompt_id — mouse left the tile

    def __init__(self, prompt_id: str, thumb_path: str | None, label_text: str,
                 parent=None, *, media_type: str | None = None,
                 movie_path: str | None = None):
        super().__init__(parent)
        self.prompt_id = prompt_id
        self._selected = False
        self._highlighted = False
        self._press_pos: QPoint | None = None  # left-press origin, for drag detection
        self.setObjectName("thumbnailTile")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
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
        self._image_label.setFixedSize(_IMAGE_SIZE)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # A video tile loops its short WebP preview; an image (or a video whose
        # WebP couldn't be built) shows its static frame.
        if movie_path and Path(movie_path).exists():
            movie = looping_movie(movie_path, _IMAGE_SIZE, self._image_label)
            self._image_label.setMovie(movie)
            movie.start()
        elif thumb_path and Path(thumb_path).exists():
            pm = QPixmap(str(thumb_path))
            self._image_label.setPixmap(
                pm.scaled(_IMAGE_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
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

        # In a mixed listing (the Recents shelf) a corner badge names the kind;
        # inside a single-type folder the caller leaves it off as redundant.
        if media_type:
            MediaBadge(media_type, self)

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
        # Only a left click (re)selects. A right click opens the context menu via
        # the custom-context-menu signal and must NOT collapse a multi-selection.
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()  # origin for a possible drag
            self.clicked.emit(self.prompt_id)

    def mouseMoveEvent(self, event):
        # Drag the generation out to a combine drop slot, but only once the press
        # has travelled far enough to read as a drag rather than a click — so a
        # plain click still just selects, and a double-click still opens.
        if self._press_pos is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        moved = (event.position().toPoint() - self._press_pos).manhattanLength()
        if moved < QApplication.startDragDistance():
            return
        self._press_pos = None
        drag = QDrag(self)
        drag.setMimeData(generation_mime(self.prompt_id))
        pixmap = self._image_label.pixmap()
        if pixmap is not None and not pixmap.isNull():
            drag.setPixmap(pixmap)  # the tile's image trails the cursor
        drag.exec(Qt.DropAction.CopyAction)

    def mouseDoubleClickEvent(self, event):
        # A left double-click is an "open" gesture; the first click's press has
        # already selected the tile, so the handler acts on the current selection.
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.prompt_id)
