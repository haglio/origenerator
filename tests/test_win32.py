"""Tests for origenerator.win32 taskbar identity helpers."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from origenerator.win32 import stamp_pinned_shortcuts


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
