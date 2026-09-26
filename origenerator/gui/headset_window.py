"""This window as a picture, for a session whose room is in the headset.

A room in the headset has no monitor to put the gallery on, so the session asks
for its picture instead (``origenerator.fun_time_mode``): every frame goes into
a memory-mapped file the session names, the session draws it on a screen in the
room, and its pointer's presses come back through a file as the words that
module declares.  The same handover Fun Time's own library browser is shown by.

The pure half is here and is what the tests drive; the Qt half is the timer, the
grab and the synthesized events.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass

from player_core.file_channel import consume_command_file
from PyQt6 import sip
from PyQt6.QtCore import QObject, QPoint, QPointF, Qt, QTimer
from PyQt6.QtGui import QImage, QMouseEvent, QPainter, QWheelEvent
from PyQt6.QtWidgets import QApplication, QWidget

from origenerator.frame_channel import FrameWriter
from origenerator.fun_time_mode import (
    HEADSET_DRAG,
    HEADSET_HOVER,
    HEADSET_PRESS,
    HEADSET_RELEASE,
    HEADSET_SCROLL,
    FunTimeSession,
)

logger = logging.getLogger(__name__)

_POLL_MS = 15

#: Nothing asked for, nothing moving: a look this often is enough to notice a
#: tooltip or a spinner, and costs a grab of a window nobody is touching.
_IDLE_LOOK_S = 0.1

#: The longest edge a published picture may have.  The rect a session names is
#: not a promise about the window: Qt gives it the size its own minimums allow,
#: and it can be resized later.  So the channel is sized to this and anything
#: bigger is scaled into it -- more pixels than the screen in the room has are
#: pixels written, read and drawn for nothing.
CAP_PX = 1440

_NO_DRAG_PX = 1 << 20


@contextmanager
def _no_drag_can_start():
    before = QApplication.startDragDistance()
    QApplication.setStartDragDistance(_NO_DRAG_PX)
    try:
        yield
    finally:
        QApplication.setStartDragDistance(before)


@dataclass(frozen=True)
class Patch:

    picture: QImage
    at: QPoint
    width: int
    height: int


_OVER_THE_WINDOW = {Qt.WindowType.Dialog: 0, Qt.WindowType.Sheet: 0,
                    Qt.WindowType.Popup: 1, Qt.WindowType.ToolTip: 2}


def opened_over(window: QWidget) -> list[QWidget]:
    return sorted((top for top in QApplication.topLevelWidgets()
                   if top is not window and top.isVisible()
                   and top.windowType() in _OVER_THE_WINDOW),
                  key=lambda top: _OVER_THE_WINDOW[top.windowType()])


def windows_opened_over(window: QWidget, *, scale: float) -> list[Patch]:
    patches = []
    for top in opened_over(window):
        at = window.mapFromGlobal(top.mapToGlobal(QPoint(0, 0)))
        patches.append(Patch(top.grab().toImage(),
                             QPoint(round(at.x() * scale), round(at.y() * scale)),
                             round(top.width() * scale), round(top.height() * scale)))
    return patches


def _held_off(target: QWidget) -> bool:
    modal = QApplication.activeModalWidget()
    return modal is not None and modal is not target and not modal.isAncestorOf(target)


def painted_over(image: QImage, patches: list[Patch]) -> QImage:
    if not patches:
        return image
    painter = QPainter(image)
    try:
        for patch in patches:
            painter.drawImage(
                patch.at,
                patch.picture.scaled(patch.width, patch.height,
                                     Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation))
    finally:
        painter.end()
    return image


def pixels_per_coordinate(image: QImage, window) -> float:
    return image.width() / window.width() if window.width() else 1.0


def within_the_cap(image: QImage) -> QImage:
    """*image* itself, or scaled until its longest edge is :data:`CAP_PX`."""
    if max(image.width(), image.height()) <= CAP_PX:
        return image
    return image.scaled(CAP_PX, CAP_PX, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation).convertToFormat(
        QImage.Format.Format_RGBA8888)


class HeadsetWindow(QObject):
    """The gallery's picture published for the headset, and the room's presses
    on it delivered as this window's own mouse events."""

    def __init__(self, window: QWidget, session: FunTimeSession, parent=None) -> None:
        super().__init__(parent)
        self._window = window
        self._input = session.input_file
        self._frames = FrameWriter(session.frames_file, max_pixels=CAP_PX * CAP_PX)
        self._pointer = QPoint(0, 0)
        self._pressed: QWidget | None = None
        self._sent: bytes | None = None
        self._published: tuple[int, int] | None = None
        self._looked_at: float | None = None
        self._asked = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(_POLL_MS)

    def close(self) -> None:
        self._timer.stop()
        self._frames.close()

    # --- the room's presses, as this window's own events ---------------------

    def _tick(self) -> None:
        for line in consume_command_file(self._input, uppercase=False):
            self._heard(line)
        self.publish()

    def _heard(self, line: str) -> None:
        kind, _, rest = line.strip().partition(" ")
        if kind in (HEADSET_PRESS, HEADSET_DRAG, HEADSET_HOVER):
            try:
                x, y = (int(part) for part in rest.split())
            except ValueError:
                logger.warning("A headset press with no pixel: %r", line)
                return
            self._pointer = self._in_the_window(x, y)
            self._point(kind)
            self._asked = self._asked or kind != HEADSET_HOVER
        elif kind == HEADSET_RELEASE:
            self._mouse(self._pressed, QMouseEvent.Type.MouseButtonRelease,
                        Qt.MouseButton.NoButton)
            self._pressed = None
            self._asked = True
        elif kind == HEADSET_SCROLL:
            try:
                self._scroll(int(rest))
            except ValueError:
                logger.warning("A headset scroll of nothing: %r", line)
            self._asked = True

    def _in_the_window(self, x: int, y: int) -> QPoint:
        if self._published is None:
            return QPoint(x, y)
        width, height = self._published
        return QPoint(round(x * self._window.width() / width),
                      round(y * self._window.height() / height))

    def _point(self, kind: str) -> None:
        if kind == HEADSET_PRESS:
            self._pressed = self._under_the_pointer()
            self._put_away_what_it_missed(self._pressed)
            self._mouse(self._pressed, QMouseEvent.Type.MouseButtonPress,
                        Qt.MouseButton.LeftButton)
        elif kind == HEADSET_DRAG:
            self._mouse(self._pressed, QMouseEvent.Type.MouseMove,
                        Qt.MouseButton.LeftButton)
        elif self._pressed is None:
            self._mouse(self._under_the_pointer(), QMouseEvent.Type.MouseMove,
                        Qt.MouseButton.NoButton)

    def _under_the_pointer(self) -> QWidget:
        at = self._window.mapToGlobal(self._pointer)
        for top in reversed(opened_over(self._window)):
            local = top.mapFromGlobal(at)
            if top.windowType() != Qt.WindowType.ToolTip and top.rect().contains(local):
                return top.childAt(local) or top
        return self._window.childAt(self._pointer) or self._window

    def _put_away_what_it_missed(self, target: QWidget) -> None:
        for top in opened_over(self._window):
            if (top.windowType() == Qt.WindowType.Popup
                    and top is not target and not top.isAncestorOf(target)):
                top.close()

    def _mouse(self, target: QWidget | None, kind, buttons: Qt.MouseButton) -> None:
        if target is None or sip.isdeleted(target) or _held_off(target):
            return
        at = QPointF(self._window.mapToGlobal(self._pointer))
        with _no_drag_can_start():
            QApplication.sendEvent(target, QMouseEvent(
                kind, target.mapFromGlobal(at), at, Qt.MouseButton.LeftButton, buttons,
                Qt.KeyboardModifier.NoModifier))

    def _scroll(self, delta: int) -> None:
        target = self._under_the_pointer()
        if _held_off(target):
            return
        at = QPointF(self._window.mapToGlobal(self._pointer))
        QApplication.sendEvent(target, QWheelEvent(
            target.mapFromGlobal(at), at, QPoint(0, 0), QPoint(0, delta),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False))

    # --- this window's picture ----------------------------------------------

    def publish(self, now: float | None = None) -> None:
        """Write the window as it looks, unless it looks as it did last time."""
        if not self._window.isVisible():
            return
        now = time.monotonic() if now is None else now
        if not self._asked and self._looked_at is not None and now - self._looked_at < _IDLE_LOOK_S:
            return
        self._asked = False
        self._looked_at = now
        grabbed = self._window.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        image = within_the_cap(painted_over(grabbed, windows_opened_over(
            self._window, scale=pixels_per_coordinate(grabbed, self._window))))
        pixels = image.constBits().asstring(image.sizeInBytes())
        if pixels == self._sent:
            return
        self._frames.write(0, image.width(), image.height(), pixels)
        self._sent = pixels
        self._published = (image.width(), image.height())
