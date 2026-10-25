"""Which monitor Origenerator's window comes up on, which its loading screen opens on."""
from __future__ import annotations

import base64
import struct

import pytest
from app_support.loading_screen import AppWindow
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QWidget

from origenerator.gui.window_monitor import the_screen_it_was_saved_on, the_window_on


def _saved_on(screen_number: int) -> str:
    rect = (0, 0, 799, 599)
    return base64.b64encode(struct.pack(">IHH4i4iiBBi4i", 0x1D9D0CB, 3, 0, *rect, *rect, screen_number,
                                        0, 0, 800, *rect)).decode("ascii")


def test_a_window_saved_on_a_monitor_comes_back_on_it(qtbot):
    window = QWidget()
    qtbot.addWidget(window)
    window.show()

    saved = base64.b64encode(bytes(window.saveGeometry())).decode("ascii")

    assert the_screen_it_was_saved_on(saved) is window.screen()


def test_the_monitor_is_read_from_where_qt_wrote_its_number():
    screens = ["the main one", "the portrait one"]

    assert the_screen_it_was_saved_on(_saved_on(1), screens=lambda: screens) == "the portrait one"


def test_a_window_saved_on_a_monitor_since_unplugged_comes_back_on_the_first_as_qt_puts_it():
    screens = ["the main one", "the portrait one"]

    assert the_screen_it_was_saved_on(_saved_on(2), screens=lambda: screens) == "the main one"


@pytest.mark.parametrize("geometry", [
    None, "not base64 at all", base64.b64encode(b"\x01\xd9\xd0").decode("ascii"),
    base64.b64encode(b"\x00" * 60).decode("ascii")])
def test_a_window_with_no_geometry_qt_could_restore_comes_back_on_no_monitor_in_particular(geometry):
    assert the_screen_it_was_saved_on(geometry, screens=lambda: ["the main one"]) is None


class _ScaledScreen:
    def geometry(self) -> QRect:
        return QRect(2560, 3, 1152, 2752)

    def devicePixelRatio(self) -> float:  # noqa: N802 - Qt's name
        return 1.25


def test_the_loading_screen_is_told_the_monitor_in_its_own_pixels_however_qt_scales_it():
    assert the_window_on(_ScaledScreen()) == AppWindow(kept_on=(2560, 3, 1440, 3440))
