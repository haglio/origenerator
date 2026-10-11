"""Tests for origenerator.win32 taskbar identity and window helpers."""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

from origenerator.win32 import (
    raise_window_without_activating,
    register_notification_identity,
    this_process_creation_time,
    window_exists,
)


class TestWindowExists:
    """A handle outlives the window it named, so anything that must reach THAT
    window and no other has to ask first."""

    def test_zero_is_never_a_window(self):
        with patch("origenerator.win32._user32") as mock:
            mock.IsWindow.return_value = 1
            assert window_exists(0) is False
        mock.IsWindow.assert_not_called()

    def test_follows_is_window(self):
        with patch("origenerator.win32._user32") as mock:
            mock.IsWindow.return_value = 0
            assert window_exists(4321) is False
            mock.IsWindow.return_value = 1
            assert window_exists(4321) is True


class TestRaiseWindowWithoutActivating:
    def test_puts_the_window_above_its_siblings_without_moving_sizing_or_activating_it(self):
        with patch("origenerator.win32._user32") as user32:
            user32.IsWindow.return_value = 1

            raise_window_without_activating(111)

        (hwnd, insert_after, *rect, flags), _kwargs = user32.SetWindowPos.call_args
        assert (hwnd.value, insert_after, rect) == (111, None, [0, 0, 0, 0])
        assert flags == 0x0001 | 0x0002 | 0x0010  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE

    def test_a_dead_handle_is_left_alone(self):
        with patch("origenerator.win32._user32") as user32:
            user32.IsWindow.return_value = 0

            assert raise_window_without_activating(111) is False

        user32.SetWindowPos.assert_not_called()


class TestNotificationIdentity:
    def test_it_registers_the_name_and_the_mark_under_the_apps_own_id(self):
        # Windows heads a notification with whatever is registered under the id
        # the process claims. With nothing there it prints the id itself and
        # draws a generic glyph, which is what a finished run's first
        # notification came out looking like.
        written = {}

        register_notification_identity(
            "Origenerator", name="Origenerator", icon=Path("C:/marks/o.png"),
            write=lambda key, values: written.update({key: values}))

        assert written == {
            r"Software\Classes\AppUserModelId\Origenerator": {
                "DisplayName": "Origenerator",
                "IconUri": str(Path("C:/marks/o.png")),
            },
        }

    def test_a_registry_that_refuses_the_write_costs_the_launch_nothing(self):
        def refuse(key, values):
            raise OSError("access denied")

        register_notification_identity("Origenerator", name="Origenerator",
                                       icon=Path("C:/marks/o.png"), write=refuse)


def test_this_process_was_created_in_filetime_ticks_before_now():
    ticks_per_second = 10_000_000
    seconds_from_1601_to_1970 = 11_644_473_600
    now = int((time.time() + seconds_from_1601_to_1970) * ticks_per_second)

    created = this_process_creation_time()

    assert 0 < now - created < 24 * 3600 * ticks_per_second
    assert this_process_creation_time() == created
