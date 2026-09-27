from __future__ import annotations

import winsound
from collections.abc import Iterator
from contextlib import contextmanager

from PyQt6.QtCore import QPropertyAnimation, QRect, Qt
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtWidgets import QWidget

from origenerator.gui.blurred import blurred_and_dimmed

_FADE_MS = 200


class FadedBackground(QWidget):
    def __init__(self, window: QWidget):
        super().__init__(window, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        area = window.geometry()
        self._picture = blurred_and_dimmed(_what_the_screen_shows(window, area), area.size())
        self.setGeometry(area)
        self.setWindowOpacity(0.0)
        self._fade_in = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setDuration(_FADE_MS)

    def showEvent(self, event):
        super().showEvent(event)
        self._fade_in.start()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self._picture)


def _what_the_screen_shows(window: QWidget, area: QRect) -> QPixmap:
    screen = window.screen()
    origin = screen.geometry().topLeft()
    return screen.grabWindow(0, area.x() - origin.x(), area.y() - origin.y(),
                             area.width(), area.height())


@contextmanager
def hard_to_miss(window: QWidget) -> Iterator[None]:
    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    if window.isMinimized():
        yield
        return
    faded = FadedBackground(window)
    faded.show()
    try:
        yield
    finally:
        faded.close()
