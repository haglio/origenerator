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
from dataclasses import dataclass

from player_core.file_channel import consume_command_file
from PyQt6.QtCore import QObject, QPoint, QPointF, Qt, QTimer
from PyQt6.QtGui import QImage, QMouseEvent, QPainter, QWheelEvent
from PyQt6.QtMultimediaWidgets import QVideoWidget
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


@dataclass(frozen=True)
class Patch:
    """A picture the grab could not reach, and where it belongs in the window."""

    picture: QImage
    at: QPoint
    width: int
    height: int


def pictures_the_grab_missed(window, videos) -> list[Patch]:
    """Every visible video surface's own last frame, placed in *window*.

    A video plays on the media player's surface rather than through the paint
    pass, so a grab of the window comes back blank where it is: the last
    frame the surface handed its sink is the only picture of it there is (the
    same handle ``preview_widget`` drags one by).
    """
    patches = []
    for video in videos:
        if not video.isVisible():
            continue
        sink = video.videoSink()
        frame = sink.videoFrame() if sink is not None else None
        if frame is None or not frame.isValid():
            continue
        size = video.size()
        patches.append(Patch(frame.toImage(), video.mapTo(window, QPoint(0, 0)),
                             size.width(), size.height()))
    return patches


def painted_over(image: QImage, patches: list[Patch]) -> QImage:
    """*image* with each patch drawn where it belongs, scaled to its widget."""
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
            self._pointer = QPoint(x, y)
            self._point(kind)
            self._asked = True
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

    def _point(self, kind: str) -> None:
        if kind == HEADSET_PRESS:
            self._pressed = self._under_the_pointer()
            self._mouse(self._pressed, QMouseEvent.Type.MouseButtonPress,
                        Qt.MouseButton.LeftButton)
        elif kind == HEADSET_DRAG:
            self._mouse(self._pressed, QMouseEvent.Type.MouseMove,
                        Qt.MouseButton.LeftButton)
        elif self._pressed is None:
            self._mouse(self._under_the_pointer(), QMouseEvent.Type.MouseMove,
                        Qt.MouseButton.NoButton)

    def _under_the_pointer(self) -> QWidget:
        return self._window.childAt(self._pointer) or self._window

    def _mouse(self, target: QWidget | None, kind, buttons: Qt.MouseButton) -> None:
        if target is None:
            return
        local = QPointF(target.mapFrom(self._window, self._pointer))
        QApplication.sendEvent(target, QMouseEvent(
            kind, local, QPointF(self._pointer), Qt.MouseButton.LeftButton, buttons,
            Qt.KeyboardModifier.NoModifier))

    def _scroll(self, delta: int) -> None:
        target = self._under_the_pointer()
        QApplication.sendEvent(target, QWheelEvent(
            QPointF(target.mapFrom(self._window, self._pointer)),
            QPointF(self._pointer), QPoint(0, 0), QPoint(0, delta),
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
        image = within_the_cap(painted_over(
            self._window.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888),
            pictures_the_grab_missed(
                self._window, self._window.findChildren(QVideoWidget)),
        ))
        pixels = image.constBits().asstring(image.sizeInBytes())
        if pixels == self._sent:
            return
        self._frames.write(0, image.width(), image.height(), pixels)
        self._sent = pixels
