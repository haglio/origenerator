from __future__ import annotations

import pytest
from app_support.threading_utils import wait_until
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from origenerator.gui import two_screens
from origenerator.gui.on_top import OnTop
from origenerator.gui.two_screens import TwoScreens
from tests.his_monitors import HIS_TWO_MONITORS

STAYS_ON_TOP = Qt.WindowType.WindowStaysOnTopHint


@pytest.fixture
def his_two_monitors(monkeypatch):
    monkeypatch.setattr(two_screens, "screens", lambda: list(HIS_TWO_MONITORS))


@pytest.fixture
def window(qtbot):
    shown = QWidget()
    qtbot.addWidget(shown)
    shown.show()
    return shown


def _on_top(window: QWidget) -> bool:
    return bool(window.windowFlags() & STAYS_ON_TOP
                and window.windowHandle().flags() & STAYS_ON_TOP)


def test_standalone_on_two_monitors_keeps_its_windows_on_top(his_two_monitors, window):
    on_top = OnTop(TwoScreens())

    on_top.stand_alone(True)

    assert _on_top(window)


def test_an_omnipause_takes_the_windows_off_the_top_and_playing_puts_them_back(
        his_two_monitors, window):
    on_top = OnTop(TwoScreens())
    on_top.stand_alone(True)

    on_top.room_paused(True)
    paused = _on_top(window)
    on_top.room_paused(False)

    assert (paused, _on_top(window)) == (False, True)


def test_standalone_on_one_monitor_leaves_its_windows_as_other_programs_windows(
        monkeypatch, window):
    monkeypatch.setattr(two_screens, "screens", lambda: [HIS_TWO_MONITORS[0]])
    on_top = OnTop(TwoScreens())

    on_top.stand_alone(True)

    assert not _on_top(window)


def test_a_fun_time_session_taking_the_window_takes_it_off_the_top(his_two_monitors, window):
    on_top = OnTop(TwoScreens())
    on_top.stand_alone(True)

    on_top.stand_alone(False)

    assert not _on_top(window)


def test_a_window_on_top_of_its_own_stays_there_through_an_omnipause(his_two_monitors, qtbot):
    asked = QWidget()
    asked.setWindowFlag(STAYS_ON_TOP)
    qtbot.addWidget(asked)
    asked.show()
    on_top = OnTop(TwoScreens())
    on_top.stand_alone(True)

    on_top.room_paused(True)

    assert _on_top(asked)


def test_a_window_opened_later_goes_on_top_when_it_takes_the_focus(his_two_monitors, qtbot):
    on_top = OnTop(TwoScreens())
    on_top.stand_alone(True)
    later = QWidget()
    qtbot.addWidget(later)
    later.show()

    later.activateWindow()

    wait_until(lambda: _on_top(later), pump=QApplication.processEvents)


class _Program:
    def __init__(self) -> None:
        self.told: list[bool] = []

    def stand_on_top(self, on: bool) -> None:
        self.told.append(on)


def test_the_slideshows_own_program_stays_on_top_until_an_omnipause_and_is_told_once_each_time(
        his_two_monitors):
    on_top = OnTop(TwoScreens())
    on_top.stand_alone(True)
    program = _Program()

    on_top.keep_on_top_too(program)
    on_top.dress_all()
    on_top.room_paused(True)
    on_top.room_paused(False)

    assert program.told == [True, False, True]
