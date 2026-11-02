from __future__ import annotations

import logging

from funestra.console import OSR2_DRIVING, OSR2_PARKED
from funestra.drive_readout import DRIVEN_BY_FUNSCRIPT, DRIVEN_BY_ROBOT_HAND
from funestra.robot_hand import FULL_INTENSITY
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)


class Osr2Control(QObject):
    changed = pyqtSignal()
    settled = pyqtSignal()

    def __init__(self, motion=None, *, script=None, parent=None) -> None:
        super().__init__(parent)
        self._motion = motion
        self.script = script
        self._engaged = False
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
        return self._motion is not None and not self._session_has_it

    def isChecked(self) -> bool:  # noqa: N802 - a button's name, deliberately
        return self.state() == OSR2_DRIVING

    def setChecked(self, on) -> None:  # noqa: N802 - a button's name, deliberately
        if bool(on) == self.isChecked() or not self.isEnabled():
            return
        self.set_state(OSR2_DRIVING if on else OSR2_PARKED)

    def engaged(self) -> bool:
        return self._engaged

    def state(self) -> str:
        held = self._motion.held if self._motion is not None else None
        return OSR2_DRIVING if self._engaged and held is None else OSR2_PARKED

    def set_state(self, state: str) -> None:
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
        if held == self._session_has_it:
            return
        logger.info("The OSR2 is %s", "Fun Time's" if held else "ours again")
        self._session_has_it = held
        was = self._engaged
        self._engage(False)
        if self._engaged == was:
            self.changed.emit()

    def _say_where_the_device_stands(self) -> None:
        logger.info("OSR2 control: %s", self.state())

    def restore(self, saved) -> None:
        self.set_state(OSR2_DRIVING if saved in (True, OSR2_DRIVING) else OSR2_PARKED)

    def source(self) -> str | None:
        if self.script is not None and self.script.active:
            return DRIVEN_BY_FUNSCRIPT
        if self._motion is not None and self._motion.active:
            return DRIVEN_BY_ROBOT_HAND
        return None
