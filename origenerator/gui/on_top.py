from __future__ import annotations

import weakref

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget

STAYS_ON_TOP = Qt.WindowType.WindowStaysOnTopHint
_WINDOWS = (Qt.WindowType.Window, Qt.WindowType.Dialog)


def _stand_on_top_without_hiding(window: QWidget, on: bool) -> None:
    window.overrideWindowFlags(window.windowFlags() | STAYS_ON_TOP if on
                               else window.windowFlags() & ~STAYS_ON_TOP)
    handle = window.windowHandle()
    if handle is not None:
        handle.setFlag(STAYS_ON_TOP, on)


class OnTop(QObject):
    def __init__(self, two_screens, parent=None):
        super().__init__(parent)
        self._two_screens = two_screens
        self._standalone = False
        self._paused = False
        self._put_on_top: weakref.WeakSet = weakref.WeakSet()
        self._programs: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
        QGuiApplication.instance().focusWindowChanged.connect(self._focus_moved)

    def stand_alone(self, alone: bool) -> None:
        self._standalone = alone
        self.dress_all()

    def room_paused(self, paused: bool) -> None:
        self._paused = paused
        self.dress_all()

    def keep_on_top_too(self, program) -> None:
        self._tell(program, self._wanted())

    def dress_all(self) -> None:
        on = self._wanted()
        for window in QApplication.topLevelWidgets():
            if window.isVisible() and window.windowType() in _WINDOWS:
                self._dress(window, on)
        for program in list(self._programs):
            self._tell(program, on)

    def _tell(self, program, on: bool) -> None:
        if self._programs.get(program) is not on:
            program.stand_on_top(on)
            self._programs[program] = on

    def _focus_moved(self, _window) -> None:
        self.dress_all()

    def _wanted(self) -> bool:
        return (self._standalone and not self._paused
                and self._two_screens.slideshows_monitor() is not None)

    def _dress(self, window: QWidget, on: bool) -> None:
        if on and not window.windowFlags() & STAYS_ON_TOP:
            _stand_on_top_without_hiding(window, True)
            self._put_on_top.add(window)
        elif not on and window in self._put_on_top:
            _stand_on_top_without_hiding(window, False)
            self._put_on_top.discard(window)
