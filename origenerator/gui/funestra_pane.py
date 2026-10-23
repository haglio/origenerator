"""The one Funestra a standalone Origenerator activates for a Slideshow, in a pane of the slideshow's window.

The Funestra is the family's window (:class:`funestra.funestra.Funestra`):
it plays what it is handed, draws its own panel over the picture, answers the
presses on it, and moves slowly over a still while it holds the screen.  Here
it draws into a native window of this pane's, and the Slideshow runs on it the
way Kino runs on Fun Time's Main Funestra: handed the playback, asked about
every press, given a pass of its own each frame.

The engine is handed a window, so it cannot exist before there is one to hand
it; a pass handed over before then is kept and opened on the moment the pane
is first shown.  A platform with no windows in it -- the suite's -- never
shows one, and a test hands the pane an engine of its own instead.  What has
nothing to open yet -- the wait before a run's first frame -- is a line on a
label, which the picture replaces.
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import ExitStack
from pathlib import Path

from funestra.funestra import Channels, Funestra
from funestra.playlist import PlaylistItem
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from origenerator.funestras_engine import offer_the_copy_beside_the_checkouts
from origenerator.running_ahead import ahead_while_playing

logger = logging.getLogger(__name__)

_TICK_MS = 16
WHEEL_NOTCH = 120


class FunestraPane(QWidget):
    def __init__(self, parent=None, *, user, panel, on_open=None, engine_for=None,
                 radio=None, volume=None, on_volume_moved=None):
        super().__init__(parent)
        self._user = user
        self._panel = panel
        self._radio = radio
        self._volume = volume
        self._on_volume_moved = on_volume_moved
        self._on_open = on_open
        self._engine_for = engine_for
        self._engine = None
        self._funestra: Funestra | None = None
        self._owed: tuple[list[PlaylistItem], Path | None] | None = None
        self._muted = False
        self._pressing_again = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        host = QWidget()
        outer.addWidget(host, 1)
        self._stack = QStackedLayout(host)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._message = QLabel()
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._message.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._stack.addWidget(self._message)
        self._window = _FunestraWindow(self)
        self._stack.addWidget(self._window)

        self._tick = QTimer(self)
        self._tick.setInterval(_TICK_MS)
        self._tick.timeout.connect(self.tick)
        self._stop_moving = threading.Event()
        self._mover: threading.Thread | None = None
        self._running_ahead = ExitStack()

    @property
    def playback(self):
        return None if self._funestra is None else self._funestra.playback

    def hand_over(self, items: list[PlaylistItem], *, land: Path | None = None) -> None:
        """Give the Funestra this pass to play, standing on *land* where that
        names an item of it: opening the Funestra on the pass if it is not
        open yet, and keeping the pass for it if it cannot open yet."""
        if not items:
            return
        if self._funestra is None:
            self._owed = (items, land)
            self._stack.setCurrentWidget(self._window)
            self._open_if_ready()
            return
        playback = self._funestra.playback
        landing = next((item for item in items if item.path == land), None)
        if landing is not None and playback.current_video != landing.path:
            playback.play_file(landing.path, landing.funscript)
        playback.replace_playlist([item.path for item in items],
                                  {item.path: item.funscript for item in items
                                   if item.funscript is not None})

    def show_message(self, text: str) -> None:
        self._message.setText(text)
        if self._funestra is None and self._owed is None:
            self._stack.setCurrentWidget(self._message)

    def message(self) -> str:
        return self._message.text() if self._stack.currentWidget() is self._message else ""

    def _open_if_ready(self) -> None:
        if self._funestra is not None or self._owed is None:
            return
        engine = self._engine_for(int(self._window.winId())) if self._engine_for else self._open_engine()
        if engine is None:
            return
        items, land = self._owed
        self._owed = None
        self._engine = engine
        self._funestra = Funestra(
            engine, channels=Channels(), playlist=items, audible=True, muted=self._muted,
            users={"slideshow": self._user}, panel=self._panel,
            radio=None if self._radio is None else self._radio.held_by_a_slideshow(),
            on_volume_moved=self._on_volume_moved)
        self._funestra.set_muted(self._muted)
        if self._volume is not None:
            self._funestra.set_volume(self._volume)
        if land is not None and self._funestra.playback.current_video != land:
            self.hand_over(items, land=land)
        self._stack.setCurrentWidget(self._window)
        self._running_ahead.enter_context(ahead_while_playing())
        self._tick.start()
        self._mover = threading.Thread(target=self._move_until_closed,
                                       name="slideshow-mover", daemon=True)
        self._mover.start()
        if self._on_open is not None:
            self._on_open()

    def _open_engine(self):
        """The engine on this pane's window, or None where there is no window
        to draw into or the engine will not open."""
        application = QApplication.instance()
        if (application is None or application.platformName() == "offscreen"
                or not self._window.isVisible()):
            return None
        offer_the_copy_beside_the_checkouts()
        from funestra.mpv_engine import MpvEngine  # noqa: PLC0415

        try:
            return MpvEngine(int(self._window.winId()), muted=self._muted,
                             loop_file=False, prefetch=True)
        except Exception:
            logger.exception("A slideshow could not open the Funestras' engine")
            return None

    def tick(self) -> None:
        if self._funestra is not None:
            self._funestra.tick(window=self._device_size())

    def _device_size(self) -> tuple[int, int]:
        scale = self._window.devicePixelRatioF()
        return max(1, round(self._window.width() * scale)), max(1, round(self._window.height() * scale))

    def _device_point(self, position) -> tuple[int, int]:
        scale = self._window.devicePixelRatioF()
        return int(position.x() * scale), int(position.y() * scale)

    def _move_until_closed(self) -> None:
        try:
            while not self._stop_moving.is_set():
                time.sleep(_TICK_MS / 1000)
                self._engine.push_still()
        except Exception:
            logger.exception("A slideshow's picture stopped moving")

    def set_audio_muted(self, muted: bool) -> None:
        self._muted = muted
        if self._funestra is not None:
            self._funestra.set_muted(muted)

    def position(self) -> int:
        """How far into the clip on screen the Funestra has got, in milliseconds."""
        return 0 if self._funestra is None else int(self._funestra.playback.position_ms)

    def close_engine(self) -> None:
        """Let the engine go, before the window it draws into is taken down."""
        self._stop_moving.set()
        if self._mover is not None:
            self._mover.join()
        self._tick.stop()
        if self._funestra is not None:
            self._funestra.close()
        self._running_ahead.close()

    # --- the pointer, handed to the Funestra in its window's own pixels -----

    def press(self, position) -> None:
        if self._funestra is not None:
            self._funestra.press(*self._device_point(position), window=self._device_size())

    def press_again(self, position) -> None:
        self._pressing_again = True
        try:
            self.press(position)
        finally:
            self._pressing_again = False

    @property
    def pressing_again(self) -> bool:
        return self._pressing_again

    def release(self) -> None:
        if self._funestra is not None:
            self._funestra.release()

    def motion(self, position, *, held: bool) -> None:
        if self._funestra is not None:
            self._funestra.motion(*self._device_point(position), held=held,
                                  window=self._device_size())

    def wheel(self, position, steps: int) -> None:
        if self._funestra is not None:
            self._funestra.wheel(*self._device_point(position), steps,
                                 window=self._device_size())

    def pointer_left(self) -> None:
        if self._funestra is not None:
            self._funestra.leave()


class _FunestraWindow(QWidget):
    """The window the engine draws into: native, because that is what the
    engine is handed and what it paints, and asked for the moment it is first
    shown, since a window that has never been on screen is not one to hand over."""

    def __init__(self, pane: FunestraPane):
        super().__init__(pane)
        self._pane = pane
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setMouseTracking(True)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._pane._open_if_ready()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pane.press(event.position())

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pane.release()

    def mouseMoveEvent(self, event) -> None:
        self._pane.motion(event.position(),
                          held=bool(event.buttons() & Qt.MouseButton.LeftButton))

    def wheelEvent(self, event) -> None:
        turned = event.angleDelta().y()
        steps = turned // WHEEL_NOTCH or (1 if turned > 0 else -1)
        self._pane.wheel(event.position(), steps)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pane.press_again(event.position())

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._pane.pointer_left()
