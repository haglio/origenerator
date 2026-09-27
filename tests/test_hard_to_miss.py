from __future__ import annotations

import winsound

import pytest
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QMainWindow, QWidget

from origenerator.gui.hard_to_miss import FadedBackground, hard_to_miss

_BLACK_AND_WHITE_AVERAGE = 127


class _Checkerboard(QWidget):
    def paintEvent(self, _event):
        painter = QPainter(self)
        for x in range(0, self.width(), 8):
            for y in range(0, self.height(), 8):
                white = (x // 8 + y // 8) % 2
                painter.fillRect(x, y, 8, 8, QColor("white") if white else QColor("black"))


def _checkerboard_window(qtbot):
    window = QMainWindow()
    window.setCentralWidget(_Checkerboard())
    window.setGeometry(100, 120, 320, 200)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    return window


def _faded_backgrounds(window):
    return [faded for faded in window.findChildren(FadedBackground) if faded.isVisible()]


def _lightness_across_the_middle(picture):
    image = picture.toImage()
    return [image.pixelColor(x, image.height() // 2).lightness()
            for x in range(0, image.width(), 4)]


def test_the_window_behind_goes_dark_and_out_of_focus(qtbot):
    window = _checkerboard_window(qtbot)

    with hard_to_miss(window):
        levels = _lightness_across_the_middle(_faded_backgrounds(window)[0].grab())

    assert max(levels) < _BLACK_AND_WHITE_AVERAGE
    assert max(levels) - min(levels) < 255 // 8


def test_the_window_fades_rather_than_going_dark_at_once(qtbot):
    window = _checkerboard_window(qtbot)

    with hard_to_miss(window):
        faded = _faded_backgrounds(window)[0]
        opacity_at_first = faded.windowOpacity()
        qtbot.waitUntil(lambda: faded.windowOpacity() == 1.0)

    assert opacity_at_first == 0.0


def test_the_window_comes_back_the_moment_the_popup_is_done(qtbot):
    window = _checkerboard_window(qtbot)

    with hard_to_miss(window):
        pass

    assert _faded_backgrounds(window) == []


def test_the_window_comes_back_even_when_the_popup_fails(qtbot):
    window = _checkerboard_window(qtbot)

    with pytest.raises(RuntimeError), hard_to_miss(window):
        raise RuntimeError

    assert _faded_backgrounds(window) == []


def test_a_minimized_window_is_left_alone_and_the_alert_still_sounds(qtbot, alert_sounds):
    window = _checkerboard_window(qtbot)
    window.showMinimized()

    with hard_to_miss(window):
        faded = _faded_backgrounds(window)

    assert faded == []
    assert alert_sounds == [winsound.MB_ICONEXCLAMATION]
