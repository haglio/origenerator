"""A preview pane that shows an image or video for the selected generation.

The gallery hands it a resolved ``(path, media_type)`` and it does the rest:
static images are scaled to fit (and rescaled on resize), animated images
(animated WebP/GIF) loop via ``QMovie``, and videos auto-play muted on a loop so
selecting one gives an immediate moving preview without stealing audio.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QStackedLayout, QVBoxLayout, QLabel, QSizePolicy, QApplication,
)
from PyQt6.QtGui import QPixmap, QMovie, QImageReader
from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

from origenerator.funscript import funscript_path_for, read_actions
from origenerator.gui.funscript_strip import FunscriptStrip

_PLACEHOLDER = "Select a generation to preview"


class PreviewWidget(QWidget):
    video_ended = pyqtSignal()  # a non-looping video reached its end (slideshow use)

    def __init__(self, parent=None, *, player: QMediaPlayer | None = None,
                 loop_videos: bool = True, allow_fullscreen: bool = True,
                 show_funscript_strip: bool = False, on_double_click=None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._movie: QMovie | None = None
        self._movie_native = None
        # The current on-disk media as (path, media_type), or None while showing a
        # placeholder or a live frame — what a double-click pops open fullscreen.
        self._media: tuple | None = None
        self._allow_fullscreen = allow_fullscreen  # a slideshow / the fullscreen view opts out
        self._fullscreen: QWidget | None = None    # the open fullscreen window, kept alive here
        # A double-click that doesn't open fullscreen (this preview opted out) runs
        # this instead — the fullscreen view uses it so a second double-click, which
        # lands here on its inner preview, dismisses it.
        self._on_double_click = on_double_click
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # The media (image/video) fills the pane; an optional funscript strip rides
        # along its bottom edge, so a scripted clip shows its stroke motion at a glance.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        media_host = QWidget()
        outer.addWidget(media_host, 1)
        self._stack = QStackedLayout(media_host)
        self._stack.setContentsMargins(0, 0, 0, 0)

        self._image_label = QLabel(_PLACEHOLDER)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setMinimumHeight(240)
        # Let the placeholder wrap so its text width doesn't set a wide minimum
        # on the preview pane (and thus the whole window).
        self._image_label.setWordWrap(True)
        self._stack.addWidget(self._image_label)

        self._video = QVideoWidget()
        self._audio = QAudioOutput(self)
        self._audio.setMuted(True)
        # The player is injectable so unit tests can drive playback intent
        # without spinning up the real (WMF) backend, which deadlocks at exit.
        self._player = player if player is not None else QMediaPlayer(self)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video)
        # Infinite for the info-pane preview (an immediate moving thumbnail); a
        # slideshow plays each clip once and advances when it ends.
        self._player.setLoops(
            QMediaPlayer.Loops.Infinite if loop_videos else QMediaPlayer.Loops.Once
        )
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._stack.addWidget(self._video)

        self._stack.setCurrentWidget(self._image_label)

        # Opt-in funscript heatmap along the bottom edge (the info-pane and fullscreen
        # previews use it); hidden until a scripted video is shown.
        self._strip = FunscriptStrip() if show_funscript_strip else None
        if self._strip is not None:
            outer.addWidget(self._strip)
            self._strip.hide()

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
        self._media = (path, "image")
        reader = QImageReader(str(path))
        if reader.supportsAnimation() and reader.imageCount() > 1:
            self._pixmap = None
            self._set_movie(QMovie(str(path)), reader.size())
        else:
            self._set_movie(None)
            self._pixmap = QPixmap(str(path))
            self._rescale()
        self._stack.setCurrentWidget(self._image_label)
        self._hide_strip()  # an image carries no stroke script

    def show_video(self, path) -> None:
        self._set_movie(None)
        self._media = (path, "video")
        self._pixmap = None
        self._image_label.clear()
        self._player.setSource(QUrl.fromLocalFile(str(Path(path))))
        self._stack.setCurrentWidget(self._video)
        self._player.play()
        self._update_strip(path)

    def show_frame(self, data: bytes) -> None:
        """Display one in-progress preview frame from raw encoded image bytes.

        ComfyUI streams live previews as encoded images over the websocket
        rather than writing a file, so this loads straight from memory. Bytes
        that don't decode (a truncated frame) are ignored, leaving the current
        view untouched.
        """
        pixmap = QPixmap()
        if not pixmap.loadFromData(data) or pixmap.isNull():
            return
        self._player.stop()
        self._media = None  # a transient live frame, not a file to open fullscreen
        self._set_movie(None)
        self._pixmap = pixmap
        self._rescale()
        self._stack.setCurrentWidget(self._image_label)
        self._hide_strip()  # a live in-progress frame has no script yet

    def show_message(self, text: str) -> None:
        """Show a plain text message in place of any media.

        For a transient state the idle placeholder would misdescribe — a re-roll
        that's generating but hasn't streamed a preview frame yet.
        """
        self._player.stop()
        self._media = None  # a message, not a file to open fullscreen
        self._set_movie(None)
        self._pixmap = None
        self._image_label.setText(text)
        self._stack.setCurrentWidget(self._image_label)
        self._hide_strip()

    def clear(self) -> None:
        self.show_message(_PLACEHOLDER)
        self._player.setSource(QUrl())  # release any held video file so it can be deleted

    def is_showing_video(self) -> bool:
        return self._stack.currentWidget() is self._video

    def player(self) -> QMediaPlayer:
        """The underlying media player — the OSR2 driver follows its position."""
        return self._player

    def _update_strip(self, video_path) -> None:
        """Aim the funscript strip at ``video_path``'s sidecar, showing it only when
        one exists — so the strip's presence is itself the "this clip has a script"
        cue (the same script the OSR2 drive would read for this video)."""
        if self._strip is None:
            return
        actions = read_actions(funscript_path_for(video_path)) if video_path else None
        self._strip.set_actions(actions or [])
        self._strip.setVisible(bool(actions))

    def _hide_strip(self) -> None:
        """Drop the strip whenever the pane isn't showing a video."""
        if self._strip is not None:
            self._strip.set_actions([])
            self._strip.hide()

    def current_video_path(self):
        """The on-disk video currently shown, or ``None`` for an image/placeholder/
        live frame — what a funscript lookup and device driving key off."""
        if self._media is not None and self._media[1] == "video":
            return self._media[0]
        return None

    def mouseDoubleClickEvent(self, event) -> None:
        # Open fullscreen, or — when this preview can't (it opted out, e.g. the
        # fullscreen view's own inner preview) — run the double-click callback, so a
        # second double-click that lands here closes the fullscreen view.
        if self.open_fullscreen() is None and self._on_double_click is not None:
            self._on_double_click()

    def open_fullscreen(self):
        """Pop the current media open fullscreen (Escape or a double-click closes
        it). A no-op when this preview opted out (a slideshow, or the fullscreen
        view itself) or nothing displayable is on screen — a placeholder, a
        message, or a live in-progress frame with no file behind it yet."""
        if not self._allow_fullscreen or self._media is None:
            return None
        # Imported here, not at module scope: fullscreen_preview builds a
        # PreviewWidget, so a top-level import would be circular.
        from origenerator.gui.fullscreen_preview import FullscreenPreview
        self._fullscreen = FullscreenPreview(self._media)
        self._fullscreen.showFullScreen()
        return self._fullscreen

    def _on_media_status(self, status) -> None:
        """Report a finished (non-looping) video so a slideshow can advance."""
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.video_ended.emit()

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
