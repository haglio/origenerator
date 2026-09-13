"""Tests for origenerator.win32 taskbar identity and foreground helpers."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import call, patch

import pytest

from origenerator.win32 import (
    force_foreground_window,
    raise_window_without_activating,
    register_notification_identity,
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


class TestForceForegroundWindow:
    """The boot takes long enough that the user clicks into something else while
    it runs, which leaves the last input event with THAT app — and Windows then
    refuses this process the foreground silently, dropping the window under
    whatever they moved on to. Attaching to the foreground thread's input queue
    is what makes the activation go through."""

    @staticmethod
    def _mock(user32, kernel32, *, ends_up_foreground: int, was_foreground: int = 999):
        user32.IsWindow.return_value = 1
        user32.GetForegroundWindow.side_effect = [was_foreground, ends_up_foreground]
        user32.GetWindowThreadProcessId.return_value = 7001
        user32.AttachThreadInput.return_value = 1
        kernel32.GetCurrentThreadId.return_value = 7002

    def test_attaches_the_foreground_queue_activates_then_detaches(self):
        with patch("origenerator.win32._user32") as user32, \
             patch("origenerator.win32._kernel32") as kernel32:
            self._mock(user32, kernel32, ends_up_foreground=111)

            assert force_foreground_window(111) is True

        assert user32.AttachThreadInput.call_args_list == [
            call(7001, 7002, True),
            call(7001, 7002, False),
        ]
        user32.SetForegroundWindow.assert_called_once_with(111)
        user32.BringWindowToTop.assert_called_once_with(111)

    def test_reports_false_when_the_window_did_not_take_the_foreground(self):
        with patch("origenerator.win32._user32") as user32, \
             patch("origenerator.win32._kernel32") as kernel32:
            self._mock(user32, kernel32, ends_up_foreground=999)

            assert force_foreground_window(111) is False

    def test_dead_handle_activates_nothing(self):
        with patch("origenerator.win32._user32") as user32, \
             patch("origenerator.win32._kernel32") as kernel32:
            self._mock(user32, kernel32, ends_up_foreground=111)
            user32.IsWindow.return_value = 0

            assert force_foreground_window(111) is False

        user32.SetForegroundWindow.assert_not_called()
        user32.AttachThreadInput.assert_not_called()

    def test_no_foreground_window_means_nothing_to_attach_to(self):
        """An offscreen/headless desktop has no foreground window: the
        activation still lands, and this still reads False."""
        with patch("origenerator.win32._user32") as user32, \
             patch("origenerator.win32._kernel32") as kernel32:
            self._mock(user32, kernel32, ends_up_foreground=0, was_foreground=0)

            assert force_foreground_window(111) is False

        user32.AttachThreadInput.assert_not_called()
        user32.SetForegroundWindow.assert_called_once_with(111)

    def test_does_not_attach_to_its_own_thread(self):
        # Already the foreground process: attaching a thread to itself fails and
        # would leave the detach below unbalanced.
        with patch("origenerator.win32._user32") as user32, \
             patch("origenerator.win32._kernel32") as kernel32:
            self._mock(user32, kernel32, ends_up_foreground=111)
            user32.GetWindowThreadProcessId.return_value = 7002

            assert force_foreground_window(111) is True

        user32.AttachThreadInput.assert_not_called()
        user32.SetForegroundWindow.assert_called_once_with(111)

    def test_detaches_even_when_the_activation_raises(self):
        with patch("origenerator.win32._user32") as user32, \
             patch("origenerator.win32._kernel32") as kernel32:
            self._mock(user32, kernel32, ends_up_foreground=111)
            user32.SetForegroundWindow.side_effect = OSError("denied")

            with pytest.raises(OSError):
                force_foreground_window(111)

        assert user32.AttachThreadInput.call_args_list[-1] == call(7001, 7002, False)


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
