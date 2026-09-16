"""The app's one OSR2 switch, and which of the four control states it is in.

It was a button in the toolbar until the players' console grew a control-state
group of its own -- control off, parked, retracted, driving -- and a second
switch for one device is exactly what that group replaces. What is left is the
switch itself, with no widget: the console sets it, and so do Space, Esc, a
spoken word and a resumed session.

It holds both of the app's drivers, because "what is the OSR2 doing" is one
question and they are two halves of the answer: the funscript driver while a
scripted video is in front, the self-generated motion otherwise, and neither
while the device is held at an end or let go of.

It wears a checkable button's three names and its toggled signal on purpose.
Every one of those callers flipped a button before, and the voice router still
flips the audio bed and the microphone that way, so one shape across the four is
one fewer thing to keep in step.
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from origenerator.paths import ensure_player_core_on_path

ensure_player_core_on_path()
from player_core.console import (  # noqa: E402
    OSR2_CONTROL_OFF,
    OSR2_DRIVING,
    OSR2_PARKED,
    OSR2_RETRACTED,
)
from player_core.drive_readout import DRIVEN_BY_FUNSCRIPT, DRIVEN_BY_ROBOT_HAND  # noqa: E402
from player_core.robot_hand import PARK_CENTER, RETRACT_CENTER  # noqa: E402

_HELD_AT = {OSR2_PARKED: PARK_CENTER, OSR2_RETRACTED: RETRACT_CENTER}
_HELD_STATE = {center: state for state, center in _HELD_AT.items()}


class Osr2Control(QObject):
    # The switch moved: what reconciles the device follows this.
    toggled = pyqtSignal(bool)
    # And anything that can change which of the four buttons lights, the holds
    # included -- what a console showing that group redraws on.
    changed = pyqtSignal()
    # The app has finished re-aiming the device, so what is driving it may be
    # different: every console over it draws itself again.
    settled = pyqtSignal()

    def __init__(self, motion=None, *, script=None, parent=None) -> None:
        super().__init__(parent)
        self._motion = motion
        # The funscript driver, set once the view has built it.  Held here
        # rather than asked of the gallery so a show's console, which never sees
        # the gallery, can still say what has the device.
        self.script = script
        self._checked = False

    def isEnabled(self) -> bool:  # noqa: N802 - a button's name, deliberately
        """Whether this app may drive the device at all.

        False where the OSR2 is not its: hosted by Fun Time, the session's main
        player owns the device for the session's whole length.
        """
        return self._motion is not None

    def isChecked(self) -> bool:  # noqa: N802 - a button's name, deliberately
        return self._checked

    def setChecked(self, on) -> None:  # noqa: N802 - a button's name, deliberately
        """Set the switch, announcing the move to whoever is following it.

        Silent when it is already there, like a button's own toggled signal, so
        a switch put where the app already is does not re-run what a click does.
        """
        on = bool(on) and self.isEnabled()
        if on == self._checked:
            return
        self._checked = on
        self.toggled.emit(on)
        self.changed.emit()

    def state(self) -> str:
        """Which of the console's four control states this app is in.

        Driving covers every way the device can be getting something from here,
        funscript or motion; the two holds are the motion stilled at one end or
        the other; off is the switch off, with nothing going out at all.
        """
        if not self._checked:
            return OSR2_CONTROL_OFF
        held = self._motion.held_at if self._motion is not None else None
        return _HELD_STATE.get(held, OSR2_DRIVING)

    def set_state(self, state: str) -> None:
        """Ask for one of those four -- what a press on the console's group is.

        The hold moves first, so whatever reconciles on the switch already sees
        it; and a state that leaves the switch where it was still says so, since
        driving to parked flips nothing and would otherwise reach nobody.
        """
        if self._motion is not None:
            if state in _HELD_AT:
                self._motion.hold(_HELD_AT[state])
            elif state == OSR2_DRIVING:
                self._motion.release()
        was = self._checked
        self.setChecked(state != OSR2_CONTROL_OFF)
        if self._checked == was:
            self.changed.emit()

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
