"""Tests for origenerator.win32 taskbar identity and foreground helpers."""
from __future__ import annotations

from unittest.mock import call, patch

import pytest

from origenerator.win32 import (
    force_foreground_window,
    stamp_pinned_shortcuts,
    window_exists,
)


@pytest.fixture
def fake_pin_dir(tmp_path):
    """A fake taskbar pin dir rooted at a temp APPDATA."""
    pin_dir = (
        tmp_path
        / "Microsoft"
        / "Internet Explorer"
        / "Quick Launch"
        / "User Pinned"
        / "TaskBar"
    )
    pin_dir.mkdir(parents=True)
    return pin_dir


def _appdata_root(pin_dir):
    # pin_dir == APPDATA / Microsoft / Internet Explorer / Quick Launch / User Pinned / TaskBar
    return pin_dir.parents[4]


class TestStampPinnedShortcuts:
    def test_stamps_origenerator_shortcut(self, fake_pin_dir):
        lnk = fake_pin_dir / "Origenerator.lnk"
        lnk.write_bytes(b"")

        with (
            patch("os.environ", {"APPDATA": str(_appdata_root(fake_pin_dir))}),
            patch("origenerator.win32.set_shortcut_app_user_model_id") as mock_set,
        ):
            stamp_pinned_shortcuts("FunTime.Origenerator", include="origenerator")

        mock_set.assert_called_once_with(str(lnk), "FunTime.Origenerator")

    def test_skips_unrelated_shortcut(self, fake_pin_dir):
        # A sibling app's pinned shortcut (e.g. ComfyUI) must not be stamped.
        (fake_pin_dir / "ComfyUI.lnk").write_bytes(b"")

        with (
            patch("os.environ", {"APPDATA": str(_appdata_root(fake_pin_dir))}),
            patch("origenerator.win32.set_shortcut_app_user_model_id") as mock_set,
        ):
            stamp_pinned_shortcuts("FunTime.Origenerator", include="origenerator")

        mock_set.assert_not_called()

    def test_missing_pin_dir_is_noop(self, tmp_path):
        # APPDATA with no taskbar pin folder must not raise.
        with (
            patch("os.environ", {"APPDATA": str(tmp_path)}),
            patch("origenerator.win32.set_shortcut_app_user_model_id") as mock_set,
        ):
            stamp_pinned_shortcuts("FunTime.Origenerator", include="origenerator")

        mock_set.assert_not_called()


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
    refuses this process the foreground silently, dropping the window behind
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
