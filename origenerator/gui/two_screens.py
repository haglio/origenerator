from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication
from shared_ui.orientation import LANDSCAPE, PORTRAIT
from shared_ui.orientation import orientation_of_size as shape_of_size

from origenerator.gui.on_top import OnTop

_THE_OTHER = {PORTRAIT: LANDSCAPE, LANDSCAPE: PORTRAIT}
LEFT = "left"
RIGHT = "right"


def screens():
    return QGuiApplication.screens()


def monitor_shaped(shape: str):
    return _every_shapes_first_monitor().get(shape)


def _every_shapes_first_monitor() -> dict:
    by_shape: dict = {}
    for screen in screens():
        area = screen.geometry()
        by_shape.setdefault(shape_of_size(area.width(), area.height()), screen)
    return by_shape


def _monitors_by_shape() -> dict:
    by_shape = _every_shapes_first_monitor()
    return by_shape if len(by_shape) == len(_THE_OTHER) else {}


class TwoScreens(QObject):
    switched = Signal()
    core_is_up = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._core_on = LANDSCAPE
        self.on_top = OnTop(self, self)

    def core_on(self) -> str:
        return self._core_on

    def put_core_on(self, shape) -> None:
        if shape in _THE_OTHER and shape != self._core_on:
            self._core_on = shape
            self.switched.emit()

    def switch(self) -> None:
        self.put_core_on(_THE_OTHER[self._core_on])

    def put_the_slideshow_on(self, shape: str) -> None:
        self.put_core_on(_THE_OTHER.get(shape))

    def slideshow_on(self) -> str:
        return _THE_OTHER[self._core_on]

    def cores_monitor(self):
        return _monitors_by_shape().get(self._core_on)

    def slideshows_monitor(self):
        return _monitors_by_shape().get(self.slideshow_on())

    def core_would_move(self) -> str | None:
        here, there = self.cores_monitor(), self.slideshows_monitor()
        if here is None:
            return None
        return LEFT if there.geometry().x() < here.geometry().x() else RIGHT
