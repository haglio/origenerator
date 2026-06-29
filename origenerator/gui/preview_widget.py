"""A preview pane that shows an image or video for the selected generation.

The gallery hands it a resolved ``(path, media_type)`` and it does the rest:
static images are scaled to fit (and rescaled on resize), animated images
(animated WebP/GIF) loop via ``QMovie``, and videos auto-play muted on a loop so
selecting one gives an immediate moving preview without stealing audio.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QWidget, QStackedLayout, QLabel, QSizePolicy, QApplication
from PyQt6.QtGui import QPixmap, QMovie, QImageReader
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

_PLACEHOLDER = "Select a generation to preview"


class PreviewWidget(QWidget):
    def __init__(self, parent=None, *, player: QMediaPlayer | None = None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._movie: QMovie | None = None
        self._movie_native = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)

        self._image_label = QLabel(_PLACEHOLDER)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setMinimumHeight(240)
        self._stack.addWidget(self._image_label)

        self._video = QVideoWidget()
        self._audio = QAudioOutput(self)
        self._audio.setMuted(True)
        # The player is injectable so unit tests can drive playback intent
        # without spinning up the real (WMF) backend, which deadlocks at exit.
        self._player = player if player is not None else QMediaPlayer(self)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video)
        self._player.setLoops(QMediaPlayer.Loops.Infinite)
        self._stack.addWidget(self._video)

        self._stack.setCurrentWidget(self._image_label)

        # The real WMF backend can deadlock during Qt/Python shutdown if a player
        # is still active, so release it before the app quits. Injected test
        # players don't touch the backend and don't need (or want) this hook.
        if player is None:
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self._release)

    def show_media(self, path, media_type: str) -> None:
        """Display ``path`` as an image or video per ``media_type``."""
        if media_type == "video":
            self.show_video(path)
        else:
            self.show_image(path)

    def show_image(self, path) -> None:
        self._player.stop()
        reader = QImageReader(str(path))
        if reader.supportsAnimation() and reader.imageCount() > 1:
            self._pixmap = None
            self._set_movie(QMovie(str(path)), reader.size())
        else:
            self._set_movie(None)
            self._pixmap = QPixmap(str(path))
            self._rescale()
        self._stack.setCurrentWidget(self._image_label)

    def show_video(self, path) -> None:
        self._set_movie(None)
        self._pixmap = None
        self._image_label.clear()
        self._player.setSource(QUrl.fromLocalFile(str(Path(path))))
        self._stack.setCurrentWidget(self._video)
        self._player.play()

    def clear(self) -> None:
        self._player.stop()
        self._set_movie(None)
        self._pixmap = None
        self._image_label.setText(_PLACEHOLDER)
        self._stack.setCurrentWidget(self._image_label)

    def is_showing_video(self) -> bool:
        return self._stack.currentWidget() is self._video

    def _release(self) -> None:
        """Tear down the media pipeline so shutdown can't deadlock the backend."""
        self._player.stop()
        self._player.setSource(QUrl())

    def _set_movie(self, movie: QMovie | None, native_size=None) -> None:
        """Attach (or clear) an animated movie, retiring any previous one.

        The movie is parented to this widget so the label's pointer can't dangle
        if Python drops the wrapper before the next paint.
        """
        if self._movie is not None:
            self._movie.stop()
            self._movie.deleteLater()
        self._movie = movie
        self._movie_native = native_size
        if movie is not None:
            movie.setParent(self)
            self._image_label.setMovie(movie)
            self._scale_movie()
            movie.start()

    def _scale_movie(self) -> None:
        if self._movie is None or self._movie_native is None or not self._movie_native.isValid():
            return
        target = self._movie_native.scaled(
            self._image_label.size(), Qt.AspectRatioMode.KeepAspectRatio
        )
        if not target.isEmpty():
            self._movie.setScaledSize(target)

    def _rescale(self) -> None:
        if self._movie is not None:
            return
        if self._pixmap is None or self._pixmap.isNull():
            self._image_label.setText("No preview available")
            return
        self._image_label.setPixmap(
            self._pixmap.scaled(
                self._image_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._movie is not None:
            self._scale_movie()
        elif self._pixmap is not None:
            self._rescale()
