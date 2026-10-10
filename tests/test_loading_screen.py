"""Origenerator's loading screen: the family's loading window wearing this app's
caption, name and icon, and walking the boot's own steps."""

from __future__ import annotations

import logging

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from origenerator.app import (
    BUILDING_THE_INTERFACE,
    CHECKOUT,
    CONNECTING,
    MAINTENANCE,
    OPENING_THE_LIBRARY,
    STARTING_THE_SERVER,
    boot_steps,
)
from origenerator.gui.loading_screen import (
    CANCEL_HINT,
    CAPTION,
    Loading,
    LoadingCanceled,
    loading_screen,
)

_STEPS = boot_steps(MAINTENANCE)


def _screen():
    return loading_screen(CHECKOUT / "icon.ico", None, _STEPS)


def test_window_title_identifies_app(qtbot):
    screen = _screen()
    qtbot.addWidget(screen)

    assert screen.windowTitle() == CAPTION


def test_the_splash_never_wears_the_apps_own_caption(qtbot):
    """A hosting Fun Time session resolves the main window by that exact
    caption, so a loading screen wearing it would be mistaken for the window."""
    screen = _screen()
    qtbot.addWidget(screen)

    assert screen.windowTitle() != "Origenerator"


def test_it_opens_on_the_boots_first_words_offering_esc(qtbot):
    screen = _screen()
    qtbot.addWidget(screen)

    assert (screen.panel.wordmark, screen.panel.status, screen.panel.hint) == (
        "Origenerator", STARTING_THE_SERVER, CANCEL_HINT)
    assert screen.panel.icon is not None


def test_every_line_the_boot_says_is_a_step_the_bar_knows():
    """A line the screen has never heard of leaves the bar where it was, so
    every status the boot announces has to be in its plan, in the boot's order."""
    said = [step for step, _weight in _STEPS]

    assert said[:2] == [STARTING_THE_SERVER, OPENING_THE_LIBRARY]
    assert said[-2:] == [CONNECTING, BUILDING_THE_INTERFACE]
    assert said[2:-2] == [boot_pass.status for boot_pass in MAINTENANCE if boot_pass.status]


def test_esc_stops_the_boot_at_its_next_step_with_the_screen_saying_so(qtbot, qapp):
    screen = _screen()
    qtbot.addWidget(screen)
    loading = Loading(qapp, logging.getLogger("test.boot"), screen)
    loading.say(OPENING_THE_LIBRARY)

    QTest.keyClick(screen, Qt.Key.Key_Escape)

    with pytest.raises(LoadingCanceled):
        loading.say(CONNECTING)
    assert (screen.panel.status, screen.panel.hint) == ("Canceling...", "")


def test_closing_the_loading_screen_cancels_rather_than_hides_it(qtbot, qapp):
    screen = _screen()
    qtbot.addWidget(screen)
    loading = Loading(qapp, logging.getLogger("test.boot"), screen)
    screen.show()

    screen.close()

    with pytest.raises(LoadingCanceled):
        loading.stop_if_canceled()
    assert screen.panel.status == "Canceling..."
