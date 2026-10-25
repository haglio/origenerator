"""The one Funestra a standalone Origenerator activates for a Slideshow, in a pane of the slideshow's window.

The Funestra is the family's window (:class:`funestra.funestra.Funestra`), and the
Slideshow drives it the way it drives one of a session's: through the pane's
:class:`PaneChannel`, which answers the three calls a session's Funestra answers on
its files, in this process.

The engine is handed a window, so it cannot exist before there is one to hand
it; a list handed over before then is kept and opened on the moment the pane
is first shown.  A platform with no windows in it -- the suite's -- never
shows one, and a test hands the pane an engine of its own instead.
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import ExitStack

from funestra.funestra import Channels, Funestra
from funestra.funestra_verbs import RELOAD_PLAYLIST
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


class PaneChannel:
    def __init__(self) -> None:
        self.on_a_list = lambda: None
        self._funestra: Funestra | None = None
        self.items: list[PlaylistItem] = []
        self._owed: list[str] = []

    def write_playlist(self, items) -> None:
        self.items = list(items)
        self.on_a_list()

    def send(self, verb: str) -> bool:
        if self._funestra is None:
            self._owed.append(verb)
        elif verb == RELOAD_PLAYLIST:
            self._funestra.take_the_list(self.items)
        else:
            self._funestra.apply(verb)
        return True

    def status(self) -> dict[str, str]:
        return {} if self._funestra is None else self._funestra.status_fields()

    def opened(self, funestra: Funestra) -> None:
        self._funestra = funestra
        owed, self._owed = self._owed, []
        for verb in owed:
            self.send(verb)


class FunestraPane(QWidget):
    def __init__(self, parent=None, *, channel: PaneChannel, user, panel, engine_for=None,
                 radio=None, volume=None, on_volume_moved=None):
        super().__init__(parent)
        self._user = user
        self._panel = panel
        self._radio = radio
        self._volume = volume
        self._on_volume_moved = on_volume_moved
        self._engine_for = engine_for
        self._engine = None
        self._funestra: Funestra | None = None
        self.channel = channel
        self._muted = False
        self._paused = False
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
        channel.on_a_list = self._open_if_ready
        self._open_if_ready()

    @property
    def playback(self):
        return None if self._funestra is None else self._funestra.playback

    def show_message(self, text: str) -> None:
        self._message.setText(text)
        if self._funestra is None and not self.channel.items:
            self._stack.setCurrentWidget(self._message)

    def message(self) -> str:
        return self._message.text() if self._stack.currentWidget() is self._message else ""

    def _open_if_ready(self) -> None:
        if self._funestra is not None or not self.channel.items:
            return
        self._stack.setCurrentWidget(self._window)
        if self._funestra is not None:
            return  # the window's first showing opened it
        engine = self._engine_for(int(self._window.winId())) if self._engine_for else self._open_engine()
        if engine is None:
            return
        self._engine = engine
        self._funestra = Funestra(
            engine, channels=Channels(), playlist=self.channel.items, audible=True,
            muted=self._muted, users={"slideshow": self._user}, panel=self._panel,
            radio=None if self._radio is None else self._radio.held_by_a_slideshow(),
            on_volume_moved=self._on_volume_moved)
        self._funestra.set_muted(self._muted)
        if self._volume is not None:
            self._funestra.set_volume(self._volume)
        self._funestra.playback.set_paused(self._paused)
        self.channel.opened(self._funestra)
        self._running_ahead.enter_context(ahead_while_playing())
        self._tick.start()
        self._mover = threading.Thread(target=self._move_until_closed,
                                       name="slideshow-mover", daemon=True)
        self._mover.start()

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
            logger.exception("A slideshow's image stopped moving")

    def set_audio_muted(self, muted: bool) -> None:
        self._muted = muted
        if self._funestra is not None:
            self._funestra.set_muted(muted)

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        if self._funestra is not None:
            self._funestra.playback.set_paused(paused)

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
