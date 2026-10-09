from __future__ import annotations

import logging

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication, QLabel, QProgressBar

from origenerator.gui.loading_screen import Loading, LoadingCanceled, LoadingScreen


def _shown(screen):
    return [label.text() for label in screen.findChildren(QLabel)]


def test_escape_keeps_the_loading_screen_up_saying_it_is_canceling(qtbot):
    screen = LoadingScreen()
    qtbot.addWidget(screen)
    screen.show()

    with qtbot.waitSignal(screen.canceled, timeout=1000):
        qtbot.keyClick(screen, Qt.Key.Key_Escape)

    assert screen.isVisible()
    assert "Canceling..." in _shown(screen)


def test_closing_the_loading_screen_cancels_rather_than_hides_it(qtbot):
    screen = LoadingScreen()
    qtbot.addWidget(screen)
    screen.show()

    with qtbot.waitSignal(screen.canceled, timeout=1000):
        screen.close()

    assert screen.isVisible()
    assert "Canceling..." in _shown(screen)


def test_the_screen_offers_esc_until_it_is_canceling(qtbot):
    screen = LoadingScreen()
    qtbot.addWidget(screen)
    assert "Press Esc to cancel opening Origenerator" in _shown(screen)

    screen.reject()

    assert "Press Esc to cancel opening Origenerator" not in _shown(screen)


def test_a_step_that_reports_after_the_cancel_leaves_canceling_on_screen(qtbot):
    screen = LoadingScreen()
    qtbot.addWidget(screen)
    screen.reject()

    screen.set_status("Waiting for server... (90s remaining)")

    assert "Canceling..." in _shown(screen)
    assert "Waiting for server... (90s remaining)" not in _shown(screen)


def test_a_close_waiting_its_turn_stops_the_loading_at_the_next_step(qtbot, qapp):
    screen = LoadingScreen()
    qtbot.addWidget(screen)
    screen.show()
    loading = Loading(qapp, logging.getLogger("t"), screen)

    QApplication.postEvent(screen, QCloseEvent())

    with pytest.raises(LoadingCanceled):
        loading.say("Backing up the records...")


def test_without_a_screen_each_step_goes_to_the_log(qapp, caplog):
    loading = Loading(qapp, logging.getLogger("t"))

    with caplog.at_level(logging.INFO):
        loading.say("Backing up the records...")

    assert "Boot: Backing up the records..." in caplog.text


def test_progress_bar_is_indeterminate(qtbot):
    screen = LoadingScreen()
    qtbot.addWidget(screen)
    bars = screen.findChildren(QProgressBar)
    assert len(bars) == 1
    # range (0, 0) makes Qt render a busy sweep instead of a percentage.
    assert bars[0].minimum() == 0
    assert bars[0].maximum() == 0


def test_set_status_updates_visible_text(qtbot):
    screen = LoadingScreen()
    qtbot.addWidget(screen)
    screen.set_status("Starting ComfyUI server")
    shown = [label.text() for label in screen.findChildren(QLabel)]
    assert any("Starting ComfyUI server" in text for text in shown)


def test_window_title_identifies_app(qtbot):
    screen = LoadingScreen()
    qtbot.addWidget(screen)
    assert "Origenerator" in screen.windowTitle()


def test_the_splash_never_wears_the_apps_own_caption(qtbot):
    # A hosting Fun Time session resolves the main window by the exact caption
    # "Origenerator"; a splash (any process's) wearing it could be mistaken
    # for the app.
    screen = LoadingScreen()
    qtbot.addWidget(screen)
    assert screen.windowTitle() != "Origenerator"
