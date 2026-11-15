from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from origenerator.gui import omnipause
from origenerator.gui.osr2_control import Osr2Control
from origenerator.osr2_driver import Osr2Driver
from origenerator.osr2_motion_driver import Osr2MotionDriver


class Osr2Driving(QObject):
    def __init__(self, surface_in_front: Callable[[], object], *, hosted: bool,
                 motion: Osr2MotionDriver | None = None, waits_for_the_window: bool = False,
                 parent=None) -> None:
        super().__init__(parent)
        self._surface_in_front = surface_in_front
        self._waits_for_the_window = waits_for_the_window
        self.motion = None if hosted else (
            motion if motion is not None else Osr2MotionDriver(parent=self))
        self.driver = Osr2Driver(parent=self) if self.motion is not None else None
        for device in self._device():
            omnipause.holds(device)
        self.control = Osr2Control(self.motion, script=self.driver, parent=self)
        self.control.changed.connect(self.reconcile)
        self._kept = (self.motion, self.driver)
        self._left_in = None
        self._driving = None
        self._reconciling = False
        self._stop_when_the_app_quits()

    def _device(self) -> tuple:
        return (self.motion, self.driver) if self.motion is not None else ()

    def _stop_when_the_app_quits(self) -> None:
        app = QApplication.instance()
        if app is not None and self.driver is not None:
            app.aboutToQuit.connect(self.driver.stop)
            app.aboutToQuit.connect(self.motion.stop)

    def toggle(self) -> None:
        self.control.setChecked(not self.control.isChecked())

    def reconcile(self) -> None:
        if self.driver is None or self._reconciling:
            return
        self._reconciling = True
        try:
            held = self.motion.held is not None
            engaged = self.control.engaged() and not self._waits_for_the_window
            in_front = self._surface_in_front()
            target = (in_front.osr2_drive_target()
                      if in_front is not None and engaged and not held
                      else None)
            wants_motion = engaged and target is None
            if not wants_motion and self.motion.active:
                self.motion.stop()
            self._drive(target)
            if wants_motion and not self.motion.active:
                self.motion.start()
            self.control.settled.emit()
        finally:
            self._reconciling = False

    def _drive(self, target) -> None:
        if target is None:
            if self._driving is not None:
                self.driver.stop()
                self._driving = None
            return
        video_path, player, actions = target
        if self._driving != (video_path, player):
            self.driver.start(player, actions)
            self._driving = (video_path, player)

    def the_window_is_up(self) -> None:
        if self._waits_for_the_window:
            self._waits_for_the_window = False
            self.reconcile()

    def let_go_for_a_session(self) -> None:
        self.control.drive_with(None, None)
        if self.motion is not None:
            self.motion.stop()

    def leave_the_device_to_the_session(self) -> None:
        self._kept = (self.motion, self.driver)
        self.motion = self.driver = None

    def take_the_device_back(self) -> None:
        self.motion, self.driver = self._kept
        self.control.drive_with(self.motion, self.driver)

    def state(self):
        if not self.control.isEnabled():
            return self._left_in
        return self.control.state()

    def restore_state(self, saved) -> None:
        self._left_in = saved
        self.control.restore(saved)

    def max_intensity(self) -> int:
        return self.control.max_intensity

    def set_max_intensity(self, saved) -> None:
        if isinstance(saved, int):
            self.control.set_max_intensity(saved)

    def motion_settings(self) -> dict | None:
        return None if self.motion is None else self.motion.settings()

    def set_motion_settings(self, saved) -> None:
        if self.motion is not None:
            self.motion.take_settings(saved)
