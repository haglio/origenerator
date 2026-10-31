"""The OSR2 controls, at the top left of Core.

Nothing on it is drawn here. :class:`funestra.console_hud.ConsolePainter`
paints it, and this widget renders that into a bitmap and blits it: the
hands-free row, the OSR2 line and the drive readout under them, all the code
Fun Time runs.  What goes on it and what a press takes off it are
:mod:`origenerator.gui.osr2_controls_state`'s, which a slideshow's own HUD asks the same
questions of.

The on/off switch IS on it: the OSR2 controls' switch -- on driving, off
parked -- is the app's one, and the Gallery pane buttons' separate one is gone.

This is the surface with no slideshow under it.  A slideshow does not float one of these:
it wears ONE panel (:mod:`origenerator.gui.slideshow_hud`), which carries the device
rows, the OSR2 line and the readout itself -- two panels in one corner said the
status twice, in two lines that disagreed, and drew prev/next/lock/trash on
each.
"""

from __future__ import annotations

from funestra.console import OSR2_CONTROL_UNANSWERED
from funestra.console_hud import ConsolePainter
from funestra.device_panel import DevicePanel
from PyQt6.QtCore import QTimer
from shared_ui.pressable_drawing import PressableDrawing

from origenerator import osr2
from origenerator.gui.osr2_controls_state import (
    REPAINT_MS,
    osr2_controls_hud,
    osr2_controls_room,
    post_device_action,
)

DEVICE_WATCH_MS = 1000


class Osr2Controls(PressableDrawing):
    """The OSR2 controls, floated over whichever surface hosts them.

    It is always here, motion or no motion. With nothing driving, its readout
    grays and its trace holds still rather than animating a wave nobody is
    riding.
    """

    def __init__(self, motion, parent=None, device=None, control=None, trouble=None):
        painter = ConsolePainter(device_only=True)
        super().__init__(DevicePanel(post=self._post, painter=painter), parent)
        self._painter = painter
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
        # How to ask what the OSR2 reads as and why the Broker cannot hear it, or
        # None for the real reads: a test never reaches the machine's own stamps.
        self._ask_device = device
        self._ask_trouble = trouble
        self._drawn_device = None
        self.setFixedSize(*osr2_controls_room(motion))
        # The trace scrolls with the phase, so repaint on a beat while it is
        # moving — and only while it is. Still OSR2 controls redrawn ten times a
        # second is the same drawing at Pillow's price, and with the panel now
        # always up that price would be paid for the whole session.
        self._repaint = QTimer(self)
        self._repaint.setInterval(REPAINT_MS)
        self._repaint.timeout.connect(self.update)
        self._device_watch = QTimer(self)
        self._device_watch.setInterval(DEVICE_WATCH_MS)
        self._device_watch.timeout.connect(self._redraw_if_the_device_switched)
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
        self._device_watch.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._repaint.stop()
        self._device_watch.stop()

    def _post(self, action: str) -> None:
        """Do here what Fun Time would route to whichever Funestra owns it —
        through the one router both of this app's OSR2 controls press into."""
        post_device_action(action, motion=self._motion, control=self._control)
        self.update()

    # --- painting: the Funestras' console's own painter, blitted ----------------------

    def _script(self):
        """The app's funscript driver, when the switch handed one over."""
        return self._control.script if self._control is not None else None

    def _osr2_control(self) -> str:
        # Unanswered with no switch handed over: the group then draws the two
        # holds it has always had and no off button, which is a switch nothing
        # would hear.  The holds still reach the motion -- see _ask_for_control.
        return (OSR2_CONTROL_UNANSWERED if self._control is None
                else self._control.state())

    def drawing(self) -> tuple[bytes, tuple[int, int]]:
        """The OSR2 controls drawn — the drawing, before it is a widget. Returned
        rather than blitted straight so a test can look at what was actually
        drawn without a screen in front of it."""
        self._drawn_device = self._device()
        device, trouble, broker_running = self._drawn_device
        return self._painter.rgba(osr2_controls_hud(
            self._motion, device=device, trouble=trouble,
            control=self._osr2_control(), script=self._script(), broker_running=broker_running))

    def _redraw_if_the_device_switched(self) -> bool:
        if self._device() == self._drawn_device:
            return False
        self.update()
        return True

    def _device(self):
        """What the OSR2 reads as, and why the Broker cannot hear it when it
        cannot, asked afresh on every draw — the device is switched on and off,
        and into its own auto mode, without this app knowing, so there is
        nothing to cache the answer against."""
        ask = self._ask_device if self._ask_device is not None else osr2.device_mode
        ask_why = self._ask_trouble if self._ask_trouble is not None else osr2.device_trouble
        return ask(), ask_why(), osr2.broker_running()

