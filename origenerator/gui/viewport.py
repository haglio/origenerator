from __future__ import annotations

import os
from pathlib import Path

from app_support.funscript import read_actions
from PySide6.QtCore import (
    QEvent,
    QPoint,
    QRect,
    QSize,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import QImage, QImageReader, QMovie, QPixmap
from PySide6.QtMultimedia import QMediaMetaData, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)
from shared_ui.message_shape import MESSAGE_PAD_H, MESSAGE_PAD_V, MESSAGE_RADIUS, MESSAGE_TOP_MARGIN
from shared_ui.palette import BLACK, WHITE, as_hex, as_rgba

from origenerator import crash_notes
from origenerator.config import OUTPUT_PLACES
from origenerator.funscript import funscript_of
from origenerator.gui import omnipause
from origenerator.gui.announced_position import AnnouncedPosition
from origenerator.gui.combination_view import CombinationView
from origenerator.gui.contact_sheet import ContactSheet
from origenerator.gui.corner_buttons import CornerButtons
from origenerator.gui.drag_thumbnail import (
    DragOut,
    fit_thumbnail,
    label_thumbnail,
)
from origenerator.gui.generation_drag import generation_mime
from origenerator.gui.live_frames import pixmap_of
from origenerator.gui.off_thread import run_off_thread
from origenerator.gui.scrubber import Scrubber
from origenerator.gui.video_surface import (
    VideoSurface,
    release_media_player,
    stop_and_let_go_of_the_file,
)
from origenerator.media import MediaType

_PLACEHOLDER = "Select a generation to preview"

_MESSAGE_PLATE = (f"color: {as_hex(WHITE)}; background: {as_rgba(BLACK, 0.78)};"
                 f" padding: {MESSAGE_PAD_V}px {MESSAGE_PAD_H}px;"
                 f" border-radius: {MESSAGE_RADIUS}px;")
_MESSAGE_MARGIN = MESSAGE_TOP_MARGIN


_WINDOW_SHOWN_BY = {
    QEvent.Type.Hide: lambda _window: False,
    QEvent.Type.Show: lambda _window: True,
    QEvent.Type.WindowStateChange: lambda window: not window.isMinimized(),
}


def _path_key(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _message_over(host: QWidget) -> QLabel:
    message = _lets_the_mouse_through(QLabel(host))
    message.setStyleSheet(_MESSAGE_PLATE)
    message.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    message.hide()
    return message


def _lets_the_mouse_through(widget):
    widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    return widget


class Viewport(QWidget):
    media_resized = Signal()
    action_triggered = Signal(str, str)
    context_requested = Signal(str, QPoint)

    def __init__(self, parent=None, *, player: QMediaPlayer | None = None,
                 make_player=QMediaPlayer, show_scrubber: bool = False):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._image_size: QSize | None = None
        self._movie: QMovie | None = None
        self._movie_native = None
        self._media: tuple | None = None
        self._live = False
        self._fullscreen = self._open_fullscreen_view = None
        self._generation = self._actions_id = None
        self.drag_out = DragOut()
        self._playing_before_the_scrub = False
        self._behind = False
        self._window_hidden = False
        self._watched_window: QWidget | None = None

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

        self._player = player if player is not None else make_player(self)
        self._playhead = AnnouncedPosition(self._player)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._media_host = media_host = QWidget()
        outer.addWidget(media_host, 1)
        self._stack = QStackedLayout(media_host)
        self._stack.setContentsMargins(0, 0, 0, 0)

        self._image_label = _lets_the_mouse_through(QLabel(_PLACEHOLDER))
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setMinimumHeight(240)
        # Qt: a word-wrapped label's width sets a wide minimum on the pane unless it can wrap
        self._image_label.setWordWrap(True)
        self._image_label.installEventFilter(self)
        media_host.installEventFilter(self)

        self._video = _lets_the_mouse_through(VideoSurface())
        self._player.setVideoOutput(self._video.video_sink())
        self._player.setLoops(QMediaPlayer.Loops.Infinite)

        self._player.metaDataChanged.connect(self._place_controls)

        self._combination = _lets_the_mouse_through(CombinationView())
        self._sheet = _lets_the_mouse_through(ContactSheet(make_player=make_player))
        for page in (self._image_label, self._video, self._combination, self._sheet):
            self._stack.addWidget(page)

        self._stack.setCurrentWidget(self._image_label)

        self._message = _message_over(media_host)

        self._controls = CornerButtons(self)
        self._controls.triggered.connect(self._on_control)

        self._scrubber = self._scrubber_under(outer) if show_scrubber else None

        # Windows Media Foundation can deadlock at shutdown if a player is still active
        app = QApplication.instance()
        if player is None and app is not None:
            app.aboutToQuit.connect(self.release_player)

        omnipause.holds(self)

    def _scrubber_under(self, outer: QVBoxLayout) -> Scrubber:
        scrubber = Scrubber()
        outer.addWidget(scrubber)
        scrubber.hide()
        self._player.durationChanged.connect(scrubber.set_duration)
        self._player.positionChanged.connect(scrubber.set_position)
        scrubber.scrubbed.connect(self._player.setPosition)
        scrubber.held.connect(self._hold_for_a_scrub)
        return scrubber

    def _hold_for_a_scrub(self, held: bool) -> None:
        if held:
            self._playing_before_the_scrub = self._player.isPlaying()
            self._player.pause()
        elif self._playing_before_the_scrub:
            self._play_where_it_is_seen()

    def _take_the_pane(self, media, *, generation: str | None = None,
                       stop_player: bool = True, enhancing: bool = False,
                       live: bool = False) -> None:
        self._set_movie(None)
        self._pixmap = self._image_size = None
        self._hide_scrubber()
        if stop_player:
            self._stop_playback()
        if not enhancing:
            self.set_message(None)
            self.set_actions(None)
        self._media, self._generation = media, generation
        self._live = live

    def show_media(self, path, media_type: str, generation: str | None = None) -> None:
        if media_type == MediaType.VIDEO:
            self.show_video(path, generation)
        else:
            self.show_image(path, generation)

    def show_image(self, path, generation: str | None = None) -> None:
        last_frame = self._video_still() if self.is_showing_video() else None
        self._take_the_pane((path, MediaType.IMAGE), generation=generation)
        reader = QImageReader(str(path))
        if reader.supportsAnimation() and reader.imageCount() > 1:
            self._set_movie(QMovie(str(path)), reader.size())
            self._stack.setCurrentWidget(self._image_label)
            return
        self._image_size = reader.size()
        if last_frame is not None:
            self._image_label.setPixmap(last_frame)
            self._stack.setCurrentWidget(self._image_label)
        asked = self._media
        run_off_thread(lambda: QImage(str(path)),
                       lambda image: self._decoded(asked, image), owner=self)

    def _video_still(self) -> QPixmap | None:
        frame = self._video.current_frame()
        if frame.isNull():
            return None
        return QPixmap.fromImage(frame).scaled(
            self._image_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)

    def _decoded(self, asked, image: QImage) -> None:
        if self._media is not asked:
            return
        self._show_image(QPixmap.fromImage(image))
        self._place_controls()
        if image.size() != self._image_size:
            self.media_resized.emit()

    def _show_image(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self._rescale()
        self._stack.setCurrentWidget(self._image_label)

    def show_video(self, path, generation: str | None = None) -> None:
        self._take_the_pane((path, MediaType.VIDEO), generation=generation,
                            stop_player=False)
        crash_notes.note(f"a viewer shows the video of item {generation}" if generation
                         else "a viewer shows a video that is no item")
        self._image_label.clear()
        self._player.setSource(QUrl.fromLocalFile(str(Path(path))))
        self._stack.setCurrentWidget(self._video)
        self._play_where_it_is_seen()
        self._show_scrubber(path)

    def show_frame(self, data: bytes, *, enhancing: bool = False,
                   generation: str | None = None) -> None:
        if (pixmap := pixmap_of(data)) is None:
            return
        self._take_the_pane(None, generation=generation, enhancing=enhancing, live=True,
                            stop_player=not self._live)
        self._show_image(pixmap)
        self._raise_message()

    def show_combination(self, combination) -> None:
        self._take_the_pane(None)
        self._image_label.clear()
        self._combination.show_pair(combination)
        self._stack.setCurrentWidget(self._combination)

    def mark_prompt_edited(self, edited: bool) -> None:
        self._combination.mark_prompt_edited(edited)

    def show_folder(self, files) -> None:
        self._take_the_pane(None)
        self._image_label.clear()
        self._sheet.show_files(files)
        self._stack.setCurrentWidget(self._sheet)

    def show_message(self, text: str, *, live: bool = False) -> None:
        self._take_the_pane(None, live=live)
        self._image_label.setText(text)
        self._stack.setCurrentWidget(self._image_label)

    def set_message(self, text: str | None) -> None:
        if not text:
            self._message.hide()
            return
        if not self._message.isHidden() and self._message.text() == text:
            return
        self._message.setText(text)
        self._message.show()
        self._place_message()
        self._raise_message()

    def _place_message(self) -> None:
        # Qt: adjustSize on a wrapping label picks a squarish block, so wrap only past the limit
        host = self._media_host
        limit = max(1, host.width() - 2 * _MESSAGE_MARGIN)
        self._message.setWordWrap(False)
        self._message.adjustSize()
        if self._message.width() > limit:
            self._message.setWordWrap(True)
            self._message.resize(limit, self._message.heightForWidth(limit))
        self._message.move(_MESSAGE_MARGIN, _MESSAGE_MARGIN)

    def _raise_message(self) -> None:
        # Qt: a stacked layout raises the widget it switches to above every sibling, the message included
        self._message.raise_()

    def clear(self) -> None:
        self.show_message(_PLACEHOLDER)
        self._player.setSource(QUrl())  # Windows will not move a file the player holds open

    def is_showing_any(self, paths) -> bool:
        if self._media is None:
            return False
        return _path_key(self._media[0]) in {_path_key(p) for p in paths}

    def release_media(self, paths) -> None:
        if self._fullscreen is not None:
            self._fullscreen.release_media(paths)
        if self.is_showing_any(paths):
            self.clear()

    def is_showing_video(self) -> bool:
        return self._stack.currentWidget() is self._video

    def video_on_screen(self) -> str | None:
        return self._generation if self.is_showing_video() else None

    def media_rect(self) -> QRect:
        drawn = self._drawn_size()
        if drawn is None or drawn.isEmpty():
            return self._media_host.geometry()
        rect = QRect(QPoint(0, 0), drawn)
        # Qt: centered on the media area: a stacked layout sizes only the page showing, so the label keeps a stale geometry under a video
        rect.moveCenter(self._media_host.geometry().center())
        return rect

    def _drawn_size(self):
        if self.is_showing_video():
            # Qt Multimedia: a video's resolution arrives late, or never; a backend need not report it.
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
        return self._player

    def playhead(self) -> AnnouncedPosition:
        return self._playhead

    def set_frozen(self, frozen: bool) -> None:
        if self._movie is not None:
            self._movie.setPaused(frozen)
        if self.is_showing_video():
            self._play_where_it_is_seen()

    def set_behind(self, behind: bool) -> None:
        self._behind = behind
        if self.is_showing_video():
            self._play_where_it_is_seen()

    def _play_where_it_is_seen(self) -> None:
        seen = not (self._behind or self._window_hidden)
        if seen and not omnipause.frozen():
            self._player.play()
        else:
            self._player.pause()

    def showEvent(self, event) -> None:
        window = self.window()
        if window is not self and window is not self._watched_window:
            if self._watched_window is not None:
                self._watched_window.removeEventFilter(self)
            self._watched_window = window
            window.installEventFilter(self)
        super().showEvent(event)

    def _window_shown(self, shown: bool) -> None:
        self._window_hidden = not shown
        if self.is_showing_video():
            self._play_where_it_is_seen()

    def media_size(self) -> tuple[int, int] | None:
        if self._movie is not None:
            frame = self._movie.currentPixmap()
            if not frame.isNull():
                return frame.width(), frame.height()
        if self._pixmap is not None and not self._pixmap.isNull():
            return self._pixmap.width(), self._pixmap.height()
        if self._image_size is not None and self._image_size.isValid():
            return self._image_size.width(), self._image_size.height()
        return None

    def set_actions(self, prompt_id: str | None, *, favorite: bool = False,
                    enhance: str | None = None, kind: str | None = None) -> None:
        self._actions_id = prompt_id
        if prompt_id is None:
            self._controls.hide_all()
            return
        self._controls.show_for(favorite=favorite, enhance=enhance, kind=kind)
        self._place_controls()

    def actions_id(self) -> str | None:
        return self._actions_id

    def _on_control(self, action: str) -> None:
        if self._actions_id is not None:
            self.action_triggered.emit(self._actions_id, action)

    def _on_context_menu(self, pos: QPoint) -> None:
        if self._actions_id is not None:
            self.context_requested.emit(self._actions_id, self.mapToGlobal(pos))

    def _place_controls(self) -> None:
        self._controls.place(self.media_rect())

    def resizeEvent(self, event) -> None:
        self._place_controls()
        super().resizeEvent(event)

    def _show_scrubber(self, video_path) -> None:
        if self._scrubber is None:
            return
        actions = (read_actions(funscript_of(video_path, places=OUTPUT_PLACES))
                   if video_path else [])
        self._scrubber.set_actions(actions)
        self._scrubber.set_position(self._player.position())
        self._scrubber.setVisible(bool(video_path))

    def _hide_scrubber(self) -> None:
        if self._scrubber is not None:
            self._scrubber.set_actions([])
            self._scrubber.hide()

    def mousePressEvent(self, event) -> None:
        if self._generation is not None:
            self.drag_out.note_press(event)

    def mouseMoveEvent(self, event) -> None:
        if self._generation is None or not self.drag_out.should_start(event):
            return
        self._start_drag(self._generation)

    def _start_drag(self, prompt_id: str) -> None:
        self.drag_out.start(generation_mime(prompt_id),
                            self._drag_thumbnail())

    def _drag_thumbnail(self) -> QPixmap:
        if self.is_showing_video():
            frame = self._video.current_frame()
            return QPixmap() if frame.isNull() else fit_thumbnail(QPixmap.fromImage(frame))
        return label_thumbnail(self._image_label)

    def set_fullscreen_factory(self, make) -> None:
        self._open_fullscreen_view = make

    def mouseDoubleClickEvent(self, event) -> None:
        self.open_fullscreen()

    def open_fullscreen(self):
        if self._media is None and not self._live:
            return None
        if self._open_fullscreen_view is None:
            return None
        self._fullscreen = self._open_fullscreen_view(self._media, self._generation)
        return self._fullscreen

    def _stop_playback(self) -> None:
        stop_and_let_go_of_the_file(self._player)

    def release_player(self) -> None:
        self._sheet.clear()
        release_media_player(self._player)

    def _set_movie(self, movie: QMovie | None, native_size=None) -> None:
        # Qt: the movie is parented to this widget so the label's pointer cannot dangle when Python drops the wrapper
        self._combination.clear()
        self._sheet.clear()
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
            movie.setPaused(omnipause.frozen())

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

    def eventFilter(self, obj, event):
        if obj is self._watched_window and event.type() in _WINDOW_SHOWN_BY:
            self._window_shown(_WINDOW_SHOWN_BY[event.type()](obj))
            return super().eventFilter(obj, event)
        # Qt resizes the label a beat after the widget going fullscreen, so refit off the label's own resize, not the widget's
        if obj is self._image_label and event.type() == QEvent.Type.Resize:
            if self._movie is not None:
                self._scale_movie()
            elif self._pixmap is not None:
                self._rescale()
            if not self._message.isHidden():
                self._place_message()
            self._place_controls()
            self.media_resized.emit()
        elif obj is self._media_host and event.type() == QEvent.Type.Resize:
            if not self._message.isHidden():
                self._place_message()
            self._place_controls()
        return super().eventFilter(obj, event)
