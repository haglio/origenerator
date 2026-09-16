"""The app's one OSR2 switch, and which of the four control states it is in.

It was a button in the toolbar until the players' console grew a control-state
group of its own -- parked, retracted, driving, control off -- and a second
switch for one device is exactly what that group replaces. What is left is the
switch itself, with no widget: the console sets it, and so do Space, Esc, a
spoken word and a resumed session.

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
from player_core.robot_hand import PARK_CENTER, RETRACT_CENTER  # noqa: E402

_HELD_AT = {OSR2_PARKED: PARK_CENTER, OSR2_RETRACTED: RETRACT_CENTER}
_HELD_STATE = {center: state for state, center in _HELD_AT.items()}


class Osr2Control(QObject):
    # The switch moved: what reconciles the device follows this.
    toggled = pyqtSignal(bool)
    # And anything that can change which of the four buttons lights, the holds
    # included -- what a console showing that group redraws on.
    changed = pyqtSignal()

    def __init__(self, motion=None, *, parent=None) -> None:
        super().__init__(parent)
        self._motion = motion
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

        A hold implies control: pressing park with the switch off turns it on
        and then stills the motion, which is what the one lit button then says.
        """
        self.setChecked(state != OSR2_CONTROL_OFF)
        if self._motion is None or state == OSR2_CONTROL_OFF:
            return
        if state in _HELD_AT:
            self._motion.hold(_HELD_AT[state])
        else:
            self._motion.release()
        self.changed.emit()
