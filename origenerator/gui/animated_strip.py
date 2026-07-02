"""A small gallery of the videos an image was animated into.

Shown in the info pane when an image is selected: each video the image was used
as the input for appears as a looping WebP preview (or its static thumbnail when
no animation is available), and clicking one navigates to that video. WebP +
``QMovie`` keeps many previews moving at once without a video player per tile.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, QSize, pyqtSignal

from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.looping_preview import looping_movie

_TILE = 132


class _VideoTile(QLabel):
    """One clickable preview tile that reports its generation's id when clicked."""

    clicked = pyqtSignal(str)

    def __init__(self, prompt_id: str, parent=None):
        super().__init__(parent)
        self._prompt_id = prompt_id
        self.setFixedSize(_TILE, _TILE)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._prompt_id)


class AnimatedVideoStrip(QWidget):
    """Preview tiles for the videos an image was animated into.

    ``show_videos`` takes ``(prompt_id, movie_path, still_path)`` triples — a
    looping WebP when ``movie_path`` is set, else the static ``still_path`` — and
    hides the whole strip when there are none. Clicking a tile emits
    ``video_activated`` with that video's prompt_id.
    """

    video_activated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        self._heading = QLabel("Animated in")
        self._heading.setStyleSheet("font-weight: 600;")
        box.addWidget(self._heading)
        self._host = QWidget()
        FlowLayout(self._host, spacing=6)
        box.addWidget(self._host)
        self._box = box
        self.hide()

    def show_videos(self, items: list[tuple[str, object, object]]):
        # Rebuild the tile host wholesale — deleting it stops and frees the old
        # tiles' movies, the same replace-the-widget idiom the gallery uses.
        self._box.removeWidget(self._host)
        self._host.deleteLater()
        self._host = QWidget()
        flow = FlowLayout(self._host, spacing=6)
        for prompt_id, movie_path, still_path in items:
            flow.addWidget(self._make_tile(prompt_id, movie_path, still_path))
        self._box.addWidget(self._host)
        self.setVisible(bool(items))

    def _make_tile(self, prompt_id, movie_path, still_path) -> _VideoTile:
        tile = _VideoTile(prompt_id)
        tile.clicked.connect(self.video_activated)
        if movie_path:
            movie = looping_movie(movie_path, QSize(_TILE, _TILE), tile)
            tile.setMovie(movie)
            movie.start()
        elif still_path:
            pixmap = QPixmap(str(still_path))
            if not pixmap.isNull():
                tile.setPixmap(pixmap.scaled(
                    _TILE, _TILE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ))
        return tile
