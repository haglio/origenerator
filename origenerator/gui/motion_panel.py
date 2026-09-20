"""Genau's console, in the foot of the main window — the same one Fun Time draws.

Nothing on it is drawn here. :class:`player_core.console_hud.ConsolePainter`
paints it, and this widget renders that into a bitmap and blits it: the status
line, the transport, the clip-seconds pace, the hands-free row, the OSR2 line
and the drive readout under them, all the code Fun Time runs.  What goes on it
and what a press takes off it are :mod:`origenerator.gui.console`'s, which a
show's own panel asks the same questions of.

The one row left off is the one naming the three players, and the minimize
button riding it. This console is inside another app's window, so it is not one
of those three and has no borderless window of its own to park.

The on/off switch IS on it: the control-state group -- parked, retracted,
driving, control off -- is the app's one OSR2 switch now, and the toolbar's
separate one is gone.

This is the surface with no show under it.  A show does not float one of these:
it wears ONE panel (:mod:`origenerator.gui.show_hud`), which carries the device
rows, the OSR2 line and the readout itself -- two panels in one corner said the
status twice, in two lines that disagreed, and drew prev/next/lock/trash on
each.
"""

from __future__ import annotations

from player_core.console import OSR2_CONTROL_UNANSWERED
from player_core.console_hud import ConsolePainter, hud_xy
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QWidget

from origenerator import osr2
from origenerator.gui.console import (
    REPAINT_MS,
    console_hud,
    panel_size,
    post_console_action,
)
from origenerator.gui.motion_hud import MOTION_KEY_LEGEND
from origenerator.gui.slideshow_pace import PaceOnlyHost, SlideshowPace


class MotionPanel(QWidget):
    """The console, floated over whichever surface hosts it.

    It is always here, motion or no motion. Part of what is on it is not about a
    running motion at all — the pace an unheld slide moves on at — and a panel
    that appeared only once the device was being driven made that reachable
    only by starting a motion first. With nothing driving, it draws itself
    exactly as Fun Time's does with the OSR2 off: the OSR2 row reads "Off", the
    readout greys, and the trace holds still rather than animating a wave
    nobody is riding.
    """

    # Fun Time insets its HUD from the window's top-left corner by this much, and
    # a reader glancing between the two apps looks for one panel in one place.
    MARGIN = hud_xy()[0]

    def __init__(self, motion, parent=None, host=None, pace=None, device_on=None,
                 control=None):
        super().__init__(parent)
        self._motion = motion
        # The app's one OSR2 switch: the control-state group's four buttons
        # read which state it is in and ask it for another.  None where nobody
        # handed one over, which is what a test's bare panel gets -- the group
        # then draws as driving and its presses reach only the motion.
        self._control = control
        if control is not None:
            control.changed.connect(self.refresh)
            # And whenever the app re-aims the device: which driver has it moves
            # with the video in front as much as with a press on this panel.
            control.settled.connect(self.refresh)
        # How to ask whether the OSR2 is on the wire, or None for the real read.
        # Injectable so a test never reaches the machine's own broker stamps.
        self._ask_device = device_on
        # Without a slideshow under it the console still has a pace to set: the
        # one the next slideshow will open at.
        self._host = host if host is not None else PaceOnlyHost(
            pace if pace is not None else SlideshowPace(parent=self))
        self._painter = ConsolePainter()
        self.setToolTip(f"OSR2 motion — {MOTION_KEY_LEGEND}")
        self.setFixedSize(*panel_size(motion, self._host, self._osr2_control()))
        # A show's console is built while its video is already driving, so the
        # first paint must be the size that console draws at.
        # The trace scrolls with the phase, so repaint on a beat while it is
        # moving — and only while it is. A still console redrawn ten times a
        # second is the same picture at Pillow's price, and with the panel now
        # always up that price would be paid for the whole session.
        self._repaint = QTimer(self)
        self._repaint.setInterval(REPAINT_MS)
        self._repaint.timeout.connect(self.update)
        # Followed from wherever the motion was toggled — the signal for a driver
        # that has one, and :meth:`refresh` (which the hosts call on every motion
        # key) for one that doesn't.
        signal = getattr(motion, "active_changed", None)
        if signal is not None:
            signal.connect(self._on_active_changed)

    def _on_active_changed(self, _active: bool) -> None:
        self._sync_repaint()
        self.update()

    def refresh(self) -> None:
        """Redraw, and re-check whether the motion is running.

        The hosts call this after every motion key, which is the one moment the
        answer can have changed under a driver that reports no signal — so the
        trace starts and stops on the key that did it, not only on the signal a
        full driver happens to emit.
        """
        self._sync_repaint()
        self.update()

    def _sync_repaint(self) -> None:
        """Animate only what is moving: a shown panel with something driving.

        Either driver moves the line -- the motion's wave scrolls with its
        phase, the script's with the playhead -- and neither does while the
        device is held at an end or let go of.
        """
        if self.isVisible() and self._driving():
            self._repaint.start()
        else:
            self._repaint.stop()

    def _driving(self) -> bool:
        if self._control is not None:
            return self._control.source() is not None
        return bool(getattr(self._motion, "active", False))

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_repaint()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._repaint.stop()

    # --- presses: the console says what they post, this routes them ---------

    def mousePressEvent(self, event):
        self._post(self._painter.press_at(*self._window(event)))

    def mouseMoveEvent(self, event):
        if self._painter.holding:
            self._post(self._painter.drag_to(*self._window(event)))

    def mouseReleaseEvent(self, event):
        self._painter.release()

    def _window(self, event) -> tuple[int, int]:
        """This widget's coordinates as the window ones the painter expects.

        It sits at the same inset from its parent that Fun Time's does from its
        window, so putting the margin back is the whole conversion.
        """
        return (int(event.position().x()) + self.MARGIN,
                int(event.position().y()) + self.MARGIN)

    def _post(self, action: str) -> None:
        """Do here what Fun Time would route to whichever player owns it —
        through the one router both of this app's consoles press into."""
        post_console_action(action, motion=self._motion, host=self._host,
                            control=self._control)
        self.update()

    # --- painting: the console's own painter, blitted ----------------------

    def _script(self):
        """The app's funscript driver, when the switch handed one over."""
        return self._control.script if self._control is not None else None

    def _osr2_control(self) -> str:
        # Unanswered with no switch handed over: the group then draws the two
        # holds it has always had and no off button, which is a switch nothing
        # would hear.  The holds still reach the motion -- see _ask_for_control.
        return (OSR2_CONTROL_UNANSWERED if self._control is None
                else self._control.state())

    def render_console(self) -> tuple[bytes, tuple[int, int]]:
        """The console drawn — the picture, before it is a widget. Returned
        rather than blitted straight so a test can look at what was actually
        drawn without a screen in front of it."""
        return self._painter.rgba(console_hud(
            self._motion, self._host, device_on=self._device_on(),
            control=self._osr2_control(), script=self._script()))

    def _device_on(self) -> bool:
        """Whether the OSR2 is answering, asked afresh on every draw — the device
        is switched on and off without this app knowing, so there is nothing to
        cache the answer against."""
        ask = self._ask_device if self._ask_device is not None else osr2.device_on
        return bool(ask())

    def paintEvent(self, event):
        raw, (width, height) = self.render_console()
        if (width, height) != (self.width(), self.height()):
            # The rows change width with what they say — a two-digit dwell, a
            # longer waveform name — so the widget follows the picture rather
            # than cropping it.
            self.setFixedSize(width, height)
        painter = QPainter(self)
        painter.drawImage(0, 0, QImage(raw, width, height,
                                       QImage.Format.Format_RGBA8888))
        painter.end()
