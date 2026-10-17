"""The app's one OSR2 switch: on drives the device, off parks it.

The switch itself has no widget: the console's button sets it, and so do Space,
Esc, a spoken word and a resumed session.

It holds both of the app's drivers, because "what is the OSR2 doing" is one
question and they are two halves of the answer: the funscript driver while a
scripted video is in front, the self-generated motion otherwise, and neither
while the device is parked.

It wears a checkable button's three names on purpose. Every one of those
callers flipped a button before, and the voice router still flips the radio
and the microphone that way, so one shape across the four is one fewer thing to
keep in step.
"""
from __future__ import annotations

import logging

from funestra.console import OSR2_DRIVING, OSR2_PARKED
from funestra.drive_readout import DRIVEN_BY_FUNSCRIPT, DRIVEN_BY_ROBOT_HAND
from funestra.robot_hand import FULL_INTENSITY
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)


class Osr2Control(QObject):
    # Anything that can change whether the switch is on, the park included:
    # what re-aims the device, and what a console showing the switch redraws on.
    changed = pyqtSignal()
    # The app has finished re-aiming the device, so what is driving it may be
    # different: every console over it draws itself again.
    settled = pyqtSignal()

    def __init__(self, motion=None, *, script=None, parent=None) -> None:
        super().__init__(parent)
        self._motion = motion
        # The funscript driver, set once the view has built it.  Held here
        # rather than asked of the gallery so a slideshow's console, which never sees
        # the gallery, can still say what has the device.
        self.script = script
        self._engaged = False
        # Whether a Fun Time session beside this window has claimed the device.
        self._session_has_it = False
        self._max_intensity = FULL_INTENSITY

    def drive_with(self, motion, script) -> None:
        self._engage(False)
        self._motion = motion
        self.script = script
        self._hold_the_drivers_to_the_max_intensity()

    @property
    def max_intensity(self) -> int:
        return self._max_intensity

    def set_max_intensity(self, level: int) -> None:
        self._max_intensity = max(0, min(FULL_INTENSITY, level))
        self._hold_the_drivers_to_the_max_intensity()
        self.changed.emit()

    def _hold_the_drivers_to_the_max_intensity(self) -> None:
        if self._motion is not None:
            self._motion.set_max_intensity(self._max_intensity)
        if self.script is not None:
            self.script.max_intensity = self._max_intensity

    def isEnabled(self) -> bool:  # noqa: N802 - a button's name, deliberately
        """Whether this app may drive the device at all.

        False where the OSR2 is not its: hosted by Fun Time, the session's main
        Funestra owns the device for the session's whole length -- and so it does
        beside a standalone window the session never took over, which is one
        device driven by two apps until this says otherwise.
        """
        return self._motion is not None and not self._session_has_it

    def isChecked(self) -> bool:  # noqa: N802 - a button's name, deliberately
        return self.state() == OSR2_DRIVING

    def setChecked(self, on) -> None:  # noqa: N802 - a button's name, deliberately
        """Switch on (driving) or off (parked), as a button flips it.

        Silent when it is already there, like a button's own toggled signal, so
        a switch put where the app already is does not re-run what a click does.
        """
        if bool(on) == self.isChecked() or not self.isEnabled():
            return
        self.set_state(OSR2_DRIVING if on else OSR2_PARKED)

    def engaged(self) -> bool:
        """Whether this app puts anything on the device: driving it, or holding
        it parked at home."""
        return self._engaged

    def state(self) -> str:
        """Driving while the device gets the funscript or the motion from here,
        and parked otherwise: the motion stilled at home, or nothing here
        reaching the device at all."""
        held = self._motion.held if self._motion is not None else None
        return OSR2_DRIVING if self._engaged and held is None else OSR2_PARKED

    def set_state(self, state: str) -> None:
        """Switch on (driving) or off (parked) -- what a press on the console is.

        The park moves first, so whatever reconciles on the switch already sees
        it; and a move that leaves the app holding the device still says so,
        since driving to parked engages nothing new and would otherwise reach
        nobody.
        """
        if self._motion is not None:
            if state == OSR2_DRIVING:
                self._motion.release()
            else:
                self._motion.hold(OSR2_PARKED)
        was = self._engaged
        self._engage(True)
        if self._engaged == was:
            self._say_where_the_device_stands()
            self.changed.emit()

    def _engage(self, on: bool) -> None:
        on = bool(on) and self.isEnabled()
        if on == self._engaged:
            return
        self._engaged = on
        self._say_where_the_device_stands()
        self.changed.emit()

    def the_session_has_it(self, held: bool) -> None:
        """A Fun Time session has claimed the OSR2, or has let it go.

        Letting go is what stops whatever this app had on the device: the view's
        one reconcile answers the change, as it does for a press.
        """
        if held == self._session_has_it:
            return
        logger.info("The OSR2 is %s", "Fun Time's" if held else "ours again")
        self._session_has_it = held
        was = self._engaged
        self._engage(False)
        if self._engaged == was:
            self.changed.emit()

    def _say_where_the_device_stands(self) -> None:
        """Record whether the app just switched the device on or off.

        The drivers log their own engage and release, which leaves the park
        silent -- so a log could not answer whether the OSR2 was under this app
        at all, which is the first question anyone debugging two apps on one
        device asks.
        """
        logger.info("OSR2 control: %s", self.state())

    def restore(self, saved) -> None:
        """Put back the state a saved session was left in: on if it was driving
        (True from a session saved while this was last an on/off switch), off
        for anything else -- parked, the retracted and control off this no
        longer has, or nothing at all."""
        self.set_state(OSR2_DRIVING if saved in (True, OSR2_DRIVING) else OSR2_PARKED)

    def source(self) -> str | None:
        """What is sending to the device right now, or None while nothing is.

        The funscript wins wherever there is one to follow, which is what the
        view's own reconcile decides; this reads the answer back off the drivers
        rather than working it out a second time.
        """
        if self.script is not None and self.script.active:
            return DRIVEN_BY_FUNSCRIPT
        if self._motion is not None and self._motion.active:
            return DRIVEN_BY_ROBOT_HAND
        return None
