from __future__ import annotations

from funestra.main_hud import OSR2_CONTROL_UNANSWERED
from funestra.main_hud_painter import MainHudPainter
from funestra.osr2_controls_host import Osr2ControlsHost
from PySide6.QtCore import QTimer
from shared_ui.pressable_drawing import PressableDrawing

from origenerator import osr2
from origenerator.gui.osr2_controls_state import (
    REPAINT_MS,
    Osr2Situation,
    osr2_controls_hud,
    osr2_controls_room,
    post_device_action,
)

DEVICE_WATCH_MS = 1000


class Osr2Controls(PressableDrawing):
    def __init__(self, motion, parent=None, device=None, control=None, trouble=None):
        painter = MainHudPainter(device_only=True)
        super().__init__(Osr2ControlsHost(post=self._post, painter=painter), parent)
        self._painter = painter
        self._motion = motion
        self._control = control
        if control is not None:
            control.changed.connect(self.refresh)
            control.settled.connect(self.refresh)
        self._ask_device = device
        self._ask_trouble = trouble
        self._drawn_device = None
        self.setFixedSize(*osr2_controls_room(motion))
        self._repaint = QTimer(self)
        self._repaint.setInterval(REPAINT_MS)
        self._repaint.timeout.connect(self.update)
        self._device_watch = QTimer(self)
        self._device_watch.setInterval(DEVICE_WATCH_MS)
        self._device_watch.timeout.connect(self._redraw_if_the_device_switched)
        signal = getattr(motion, "active_changed", None)
        if signal is not None:
            signal.connect(self._on_active_changed)

    def _on_active_changed(self, _active: bool) -> None:
        self._sync_repaint()
        self.update()

    def refresh(self) -> None:
        self._sync_repaint()
        self.update()

    def _sync_repaint(self) -> None:
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
        post_device_action(action, motion=self._motion, control=self._control)
        self.update()

    def _script(self):
        return self._control.script if self._control is not None else None

    def _osr2_control(self) -> str:
        return (OSR2_CONTROL_UNANSWERED if self._control is None
                else self._control.state())

    def drawing(self) -> tuple[bytes, tuple[int, int]]:
        self._drawn_device = self._device()
        device, trouble, broker_running = self._drawn_device
        return self._painter.rgba(osr2_controls_hud(
            self._motion, Osr2Situation(device=device, trouble=trouble,
            control=self._osr2_control(), script=self._script(), broker_running=broker_running)))

    def _redraw_if_the_device_switched(self) -> bool:
        if self._device() == self._drawn_device:
            return False
        self.update()
        return True

    def _device(self):
        ask = self._ask_device if self._ask_device is not None else osr2.device_mode
        ask_why = self._ask_trouble if self._ask_trouble is not None else osr2.device_trouble
        return ask(), ask_why(), osr2.broker_running()

