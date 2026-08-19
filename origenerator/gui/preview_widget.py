"""A preview pane that shows an image or video for the selected generation.

The gallery hands it a resolved ``(path, media_type)`` and it does the rest:
static images are scaled to fit (and rescaled on resize), animated images
(animated WebP/GIF) loop via ``QMovie``, and videos auto-play on a loop — muted by
default, so selecting one gives an immediate moving preview without stealing audio,
while the fullscreen slideshow opts in to sound.

A still can also be drawn part-way into itself (:meth:`PreviewWidget.set_zoom`),
which is how the fullscreen show creeps into each picture while it holds the
screen; every other pane leaves that at the whole picture.
"""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QStackedLayout, QVBoxLayout, QLabel, QSizePolicy, QApplication,
)
from PyQt6.QtGui import QPixmap, QMovie, QImageReader, QDrag
from PyQt6.QtCore import Qt, QUrl, QPoint, QRect, QSize, QEvent, pyqtSignal
from PyQt6.QtMultimedia import QMediaMetaData, QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

from origenerator.funscript import funscript_path_for, read_actions
from origenerator.gui.funscript_strip import FunscriptStrip
from origenerator.gui.generation_drag import generation_mime
from origenerator.ken_burns import crop_box

_PLACEHOLDER = "Select a generation to preview"


def _path_key(path) -> str:
    """One comparable form for a file path, so two spellings of the same file —
    a ``Path`` against a string, or Windows' case-blind pair — match."""
    return os.path.normcase(os.path.abspath(str(path)))


class PreviewWidget(QWidget):
    video_ended = pyqtSignal()  # a non-looping video reached its end (slideshow use)
    # This backend cannot open the clip at all — a different thing from ending,
    # and the one a show has to be told about (see _on_media_status).
    video_unplayable = pyqtSignal()
    media_resized = pyqtSignal()  # the media was refitted (an overlay must re-place)
    drag_started = pyqtSignal(str)  # the shown generation began dragging out (prompt_id)
    drag_ended = pyqtSignal()       # that drag finished (dropped or canceled)

    def __init__(self, parent=None, *, player: QMediaPlayer | None = None,
                 loop_videos: bool = True, allow_fullscreen: bool = True,
                 show_funscript_strip: bool = False, mute_audio: bool = True,
                 on_double_click=None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._movie: QMovie | None = None
        self._movie_native = None
        # The current on-disk media as (path, media_type), or None while showing a
        # placeholder or a live frame — what a double-click pops open fullscreen.
        self._media: tuple | None = None
        # Whether a generation is running behind this pane — its streamed frames, or
        # the wait before the first one arrives — and that latest frame. A double-click
        # opens fullscreen over these too, and the view opened that way keeps following
        # from here: later frames, then the finished file. Without it, watching a
        # generation had to wait for it to land.
        self._live = False
        self._live_frame: bytes | None = None
        self._allow_fullscreen = allow_fullscreen  # a slideshow's own preview opts out
        self._fullscreen: QWidget | None = None    # the open fullscreen window, kept alive here
        # What builds that window. The gallery sets it, because what a double-click
        # opens is a slideshow of the folder behind this pane — which this pane
        # knows nothing about. Unset, a double-click opens nothing.
        self._open_fullscreen_view = None
        # A double-click that doesn't open fullscreen (this preview opted out, or has
        # nothing to open) runs this instead — the slideshow uses it so a second
        # double-click dismisses it.
        self._on_double_click = on_double_click
        # The shown generation's prompt_id when the owner has armed the preview to be
        # dragged out onto a combine slot (like a gallery thumbnail), else None; a
        # transient view (a live frame, a message) disarms it. _drag_origin holds the
        # left-press point while measuring whether a move is a drag or just a click.
        self._draggable_id: str | None = None
        self._drag_origin: QPoint | None = None
        # How far into the still this pane is drawn — the fullscreen show's slow
        # push (see set_zoom). 1.0, the whole picture, for every other pane:
        # nothing but a show ever moves it.
        self._zoom = 1.0
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
        # Rescale the media whenever the label itself resizes — see eventFilter for
        # why this can't ride on the widget's own resizeEvent.
        self._image_label.installEventFilter(self)
        # Let mouse events fall through to this widget, so a press/drag/double-click
        # over the media is handled here (drag-out, open-fullscreen) rather than being
        # swallowed by the label or the video surface.
        self._image_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._stack.addWidget(self._image_label)

        self._video = QVideoWidget()
        self._video.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._audio = QAudioOutput(self)
        self._audio.setMuted(mute_audio)
        # The player is injectable so unit tests can drive playback intent
        # without spinning up the real (WMF) backend, which deadlocks at exit.
        # A hosting session's OmniPause over this pane, held rather than edged:
        # the pane is re-pointed constantly and each new media starts playing.
        self._playback_paused = False
        self._player = player if player is not None else QMediaPlayer(self)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video)
        # Infinite for the info-pane preview (an immediate moving thumbnail); a
        # slideshow plays each clip once and advances when it ends.
        self._player.setLoops(
            QMediaPlayer.Loops.Infinite if loop_videos else QMediaPlayer.Loops.Once
        )
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_media_error)
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
        self._end_live(self._media)
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
        self._end_live(self._media)
        self._pixmap = None
        self._image_label.clear()
        self._player.setSource(QUrl.fromLocalFile(str(Path(path))))
        self._stack.setCurrentWidget(self._video)
        self._player.play()
        if self._playback_paused:
            self._player.pause()  # a clip loaded into a frozen room opens held
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
        self._live, self._live_frame = True, data  # …but a running generation to watch
        self._draggable_id = None  # nor a saved generation to drag out
        self._set_movie(None)
        self._pixmap = pixmap
        self._rescale()
        self._stack.setCurrentWidget(self._image_label)
        self._hide_strip()  # a live in-progress frame has no script yet
        win = self._following_fullscreen()
        if win is not None:
            win.show_frame(data)  # keep a view watching this generation up to date

    def show_message(self, text: str, *, live: bool = False) -> None:
        """Show a plain text message in place of any media.

        For a transient state the idle placeholder would misdescribe — a re-roll
        that's generating but hasn't streamed a preview frame yet.

        ``live`` marks the message as a running generation's, so a double-click
        opens fullscreen over it all the same — the view comes up saying it's
        generating and fills in as the frames arrive.
        """
        self._player.stop()
        self._media = None  # a message, not a file to open fullscreen
        self._end_live(None)  # a message is no result to hand a following view
        self._live = live
        self._draggable_id = None  # nor a saved generation to drag out
        self._set_movie(None)
        self._pixmap = None
        self._image_label.setText(text)
        self._stack.setCurrentWidget(self._image_label)
        self._hide_strip()

    def _end_live(self, media: tuple | None) -> None:
        """Stop mirroring a running generation, handing ``media`` — the file it
        landed as, if any — to a fullscreen show opened over its live frames, so
        watching a generation fullscreen ends on the finished image rather than the
        last low-res frame.

        What decides the hand-off is the *view's* own liveness, never this pane's:
        the pane blanks to its placeholder on every gallery rebuild while a run
        streams — including the one that lands it, moments before the saved file
        arrives here — so its own flag is already off by then."""
        self._live, self._live_frame = False, None
        if media is None:
            return
        win = self._following_fullscreen()
        if win is not None:
            win.show_landed(media)

    def _following_fullscreen(self):
        """The fullscreen show this pane opened over a running generation and is
        still feeding, or ``None``. One that's been dismissed — or that already
        landed on a file, and so is an ordinary show of it now — follows
        nothing."""
        win = self._fullscreen
        if win is None or not win.isVisible() or not win.is_live():
            return None
        return win

    def clear(self) -> None:
        self.show_message(_PLACEHOLDER)
        self._player.setSource(QUrl())  # release any held video file so it can be deleted

    def is_showing_any(self, paths) -> bool:
        """Whether the file on screen is one of ``paths``, however each is spelled."""
        if self._media is None:
            return False
        return _path_key(self._media[0]) in {_path_key(p) for p in paths}

    def release_media(self, paths) -> None:
        """Let go of ``paths`` — files about to be moved or deleted.

        A loaded video keeps its file open for as long as it's the player's
        source, and Windows refuses to move a file anything holds open, so a
        pane still showing a condemned item is what makes its own deletion
        fail. Panes showing anything else are left exactly as they are: only
        what's about to go is dropped, along with a fullscreen show of it.
        """
        if self._fullscreen is not None:
            self._fullscreen.release_media(paths)
        if self.is_showing_any(paths):
            self.clear()

    def is_showing_video(self) -> bool:
        return self._stack.currentWidget() is self._video

    def media_rect(self) -> QRect:
        """Where the media is actually drawn inside this pane, in its coordinates.

        Media is fitted keeping its aspect ratio, so a portrait image on a wide
        screen leaves surround either side of it — which is what an overlay (the
        slideshows' neighbor stills) needs to know to keep clear of the picture.
        Falls back to the whole pane whenever the drawn size isn't knowable yet:
        a video whose resolution hasn't arrived, or nothing on screen at all.
        """
        drawn = self._drawn_size()
        if drawn is None or drawn.isEmpty():
            return self.rect()
        rect = QRect(QPoint(0, 0), drawn)
        rect.moveCenter(self._image_label.mapTo(self, self._image_label.rect().center()))
        return rect

    def _drawn_size(self):
        """The media's rendered size — the scaled pixmap or movie frame, or a
        video's resolution fitted to its surface — or ``None`` when unknown."""
        if self.is_showing_video():
            resolution = self._player.metaData().value(QMediaMetaData.Key.Resolution)
            if isinstance(resolution, QSize) and resolution.isValid():
                return resolution.scaled(self._video.size(),
                                         Qt.AspectRatioMode.KeepAspectRatio)
            return None
        if self._movie is not None:
            scaled = self._movie.scaledSize()
            return scaled if scaled.isValid() else None
        pixmap = self._image_label.pixmap()
        return None if pixmap is None or pixmap.isNull() else pixmap.size()

    def player(self) -> QMediaPlayer:
        """The underlying media player — the OSR2 driver follows its position."""
        return self._player

    def set_zoom(self, zoom: float) -> None:
        """Draw the still *zoom* deep into itself — the show's Ken Burns push.

        A centered crop of 1/*zoom*, scaled back up to the size the whole picture
        was drawn at, so the rect the media occupies stays where it is — within
        the pixel the crop rounds to. The neighbor stills and the HUD map are
        placed against :meth:`media_rect`, and a zoom that grew the drawn picture
        instead would shove them about twenty times a second.

        Stills only. An animated image is already moving and a video is its own
        motion, so both take the number inertly — as does every pane but a
        show's, none of which ever calls this.
        """
        zoom = max(1.0, float(zoom))
        if zoom == self._zoom:
            return
        self._zoom = zoom
        self._rescale()

    def set_audio_muted(self, muted: bool) -> None:
        """Silence (or voice) this pane's playback outright."""
        self._audio.setMuted(muted)

    def audio_muted(self) -> bool:
        return self._audio.isMuted()

    def set_playback_paused(self, paused: bool) -> None:
        """Freeze or resume whatever is moving here (a hosted session's
        OmniPause): a playing video, or an animated image's own movie.

        Remembered rather than only applied, because this pane is re-pointed
        constantly — a click, a landing generation, a tab change — and each of
        those starts the new media playing.  A pane frozen once has to stay
        frozen through every one of them until the room resumes.  A still takes
        the flag inertly; its advance is the owning view's dwell timer, not
        this pane's.
        """
        self._playback_paused = paused
        self._apply_playback_pause()

    def _apply_playback_pause(self) -> None:
        """Hold what is on screen now, if the freeze is on."""
        if self._movie is not None:
            self._movie.setPaused(self._playback_paused)
        if not self.is_showing_video():
            return
        if self._playback_paused:
            self._player.pause()
        else:
            self._player.play()

    def current_media_path(self) -> str:
        """The file on screen, or "" while showing a placeholder or live frame."""
        return str(self._media[0]) if self._media is not None else ""

    def set_draggable_id(self, prompt_id: str | None) -> None:
        """Arm (or disarm) dragging the shown media out as a generation.

        The owner passes the displayed generation's prompt_id so the preview can be
        dragged onto a combine slot exactly like a gallery thumbnail; ``None`` leaves
        it undraggable. A transient view (a live frame or a message) disarms itself,
        so this only ever needs re-arming when a saved generation is shown."""
        self._draggable_id = prompt_id

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

    def mousePressEvent(self, event) -> None:
        # The media children are transparent to the mouse, so a press over the
        # image or video lands here. Note the origin for a possible drag of the
        # shown generation; a plain click still falls through to the double-click.
        if event.button() == Qt.MouseButton.LeftButton and self._draggable_id is not None:
            self._drag_origin = event.position().toPoint()

    def mouseMoveEvent(self, event) -> None:
        # Drag the shown generation out to a combine slot, but only once the press
        # has travelled far enough to read as a drag rather than a click — so a
        # plain click still just opens fullscreen on the following double-click.
        if self._drag_origin is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if self._draggable_id is None:
            return
        moved = (event.position().toPoint() - self._drag_origin).manhattanLength()
        if moved < QApplication.startDragDistance():
            return
        prompt_id = self._draggable_id
        self._drag_origin = None
        self._start_drag(prompt_id)

    def _start_drag(self, prompt_id: str) -> None:
        """Carry the shown generation out under the shared drag type, so a combine
        slot can read its prompt_id — the same payload a gallery thumbnail drags."""
        drag = QDrag(self)
        drag.setMimeData(generation_mime(prompt_id))
        pixmap = self._image_label.pixmap()
        if pixmap is not None and not pixmap.isNull():
            drag.setPixmap(pixmap)  # the shown still trails the cursor
        # Announce the drag so a combine slot can light the moment it starts —
        # QDrag.exec is modal, so the highlight is on for the whole gesture.
        self.drag_started.emit(prompt_id)
        try:
            drag.exec(Qt.DropAction.CopyAction)
        finally:
            self.drag_ended.emit()

    def set_fullscreen_factory(self, make) -> None:
        """Wire what a double-click here opens: ``make(media, frame)`` returns a
        shown fullscreen window, or ``None``.

        The gallery supplies it, because the window is a slideshow of the folder
        this pane's generation sits in and the pane has no idea what that folder
        holds. Left unset — a bare preview in a test — a double-click opens
        nothing.
        """
        self._open_fullscreen_view = make

    def mouseDoubleClickEvent(self, event) -> None:
        # Open fullscreen, or — when this preview can't (it opted out, e.g. the
        # slideshow's own inner preview) — run the double-click callback, so a
        # second double-click that lands here closes the slideshow.
        if self.open_fullscreen() is None and self._on_double_click is not None:
            self._on_double_click()

    def open_fullscreen(self):
        """Pop what's on screen open fullscreen (Escape or a double-click closes it):
        a slideshow of this generation's folder, held on this one.

        That's the current file, or — while a generation is running behind this pane —
        its live frames, in a view that goes on following the run from here and swaps
        to the finished file when it lands. A no-op when this preview opted out (a
        slideshow's own inner preview), when nothing has wired
        :meth:`set_fullscreen_factory`, or when there's nothing to watch at all:
        the idle placeholder or a plain message."""
        if not self._allow_fullscreen or (self._media is None and not self._live):
            return None
        if self._open_fullscreen_view is None:
            return None
        self._fullscreen = self._open_fullscreen_view(self._media, self._live_frame)
        return self._fullscreen

    def _on_media_status(self, status) -> None:
        """Report a finished video so a slideshow can advance — and separately,
        one this backend cannot open at all.

        The second is not a kind of ending, and treating it as one is what left
        a show on a black rectangle: a clip with no codec here never reports
        EndOfMedia, and a video carries no dwell timer (its own length is its
        dwell), so nothing was ever going to move the show off it again.  A
        browse of the whole library is exactly where such a clip turns up.
        """
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.video_ended.emit()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self.video_unplayable.emit()

    def _on_media_error(self, error, _message: str = "") -> None:
        """Same report, from the other direction: the backend can raise the
        error without ever moving the status to InvalidMedia."""
        if error != QMediaPlayer.Error.NoError and self.is_showing_video():
            self.video_unplayable.emit()

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
            movie.setPaused(self._playback_paused)  # an animated still, in a frozen room

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
        drawn = self._pixmap
        if self._zoom > 1.0:
            # Crop out of the source and scale that up, rather than scaling the
            # whole picture up and cropping the result: the source is usually
            # bigger than the pane, so the pixels the push moves into are real
            # ones rather than interpolated ones.
            drawn = drawn.copy(
                QRect(*crop_box(drawn.width(), drawn.height(), self._zoom)))
        self._image_label.setPixmap(
            drawn.scaled(
                self._image_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def eventFilter(self, obj, event):
        # Refit the media to the label's *own* size whenever the label resizes, rather
        # than reacting to this widget's resizeEvent. Going fullscreen resizes the
        # label a beat after the widget, so scaling to the widget's not-yet-grown size
        # left the image scaled small and then centered on the full screen — black on
        # all four sides. Keying off the label's resize fits it to the real pane every
        # time that changes, initial fullscreen included.
        if obj is self._image_label and event.type() == QEvent.Type.Resize:
            if self._movie is not None:
                self._scale_movie()
            elif self._pixmap is not None:
                self._rescale()
            # The label lags this widget going fullscreen, so anything placed
            # against the media's rect has to re-place when the refit lands.
            self.media_resized.emit()
        return super().eventFilter(obj, event)
