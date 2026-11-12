from __future__ import annotations

import pytest

from origenerator.gui import two_screens
from origenerator.gui.two_screens import TwoScreens
from tests.his_monitors import HIS_TWO_MONITORS

PORTRAIT = "portrait"
LANDSCAPE = "landscape"
LANDSCAPE_MONITOR, PORTRAIT_MONITOR = HIS_TWO_MONITORS


@pytest.fixture
def his_two_monitors(monkeypatch):
    monkeypatch.setattr(two_screens, "screens", lambda: [LANDSCAPE_MONITOR, PORTRAIT_MONITOR])


def _switches_heard(sides: TwoScreens) -> list:
    heard = []
    sides.switched.connect(lambda: heard.append(sides.core_on()))
    return heard


def test_core_starts_on_the_landscape_monitor_with_the_slideshow_on_the_portrait_one(
        his_two_monitors):
    sides = TwoScreens()

    assert (sides.cores_monitor(), sides.slideshows_monitor()) == (
        LANDSCAPE_MONITOR, PORTRAIT_MONITOR)


def test_a_switch_trades_the_two_monitors_and_says_so(his_two_monitors):
    sides = TwoScreens()
    heard = _switches_heard(sides)

    sides.switch()

    assert (sides.cores_monitor(), sides.slideshows_monitor(), heard) == (
        PORTRAIT_MONITOR, LANDSCAPE_MONITOR, [PORTRAIT])


def test_a_slideshow_put_on_cores_monitor_sends_core_to_the_other(his_two_monitors):
    sides = TwoScreens()
    heard = _switches_heard(sides)

    sides.put_the_slideshow_on(LANDSCAPE)

    assert (sides.slideshows_monitor(), sides.cores_monitor(), heard) == (
        LANDSCAPE_MONITOR, PORTRAIT_MONITOR, [PORTRAIT])


def test_a_slideshow_put_on_the_monitor_it_has_moves_nothing(his_two_monitors):
    sides = TwoScreens()
    heard = _switches_heard(sides)

    sides.put_the_slideshow_on(PORTRAIT)

    assert (sides.core_on(), heard) == (LANDSCAPE, [])


@pytest.mark.parametrize("saved", [None, "sideways", 3])
def test_a_saved_side_that_is_no_shape_leaves_core_where_it_was(his_two_monitors, saved):
    sides = TwoScreens()

    sides.put_core_on(saved)

    assert sides.core_on() == LANDSCAPE


@pytest.mark.parametrize("monitors", [[], [LANDSCAPE_MONITOR],
                                      [LANDSCAPE_MONITOR, LANDSCAPE_MONITOR]])
def test_without_a_monitor_of_each_shape_neither_window_has_one(monkeypatch, monitors):
    monkeypatch.setattr(two_screens, "screens", lambda: monitors)
    sides = TwoScreens()

    assert (sides.cores_monitor(), sides.slideshows_monitor()) == (None, None)


def test_core_would_move_toward_the_monitor_the_slideshow_is_on(his_two_monitors):
    sides = TwoScreens()
    first = sides.core_would_move()

    sides.switch()

    assert (first, sides.core_would_move()) == ("right", "left")


def test_core_would_move_nowhere_with_one_monitor(monkeypatch):
    monkeypatch.setattr(two_screens, "screens", lambda: [LANDSCAPE_MONITOR])

    assert TwoScreens().core_would_move() is None
