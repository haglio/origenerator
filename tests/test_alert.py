from __future__ import annotations

from unittest.mock import MagicMock, patch

from app_support.testing import error_popup
from shared_ui.alert import Level
from shared_ui.testing import alert_shown

from origenerator import alert
from tests.alert_windows import Alert


def test_an_error_is_the_familys_red_x_window(qapp, alerts):
    alert.error("Sample title", "Something made up went wrong.")

    assert alerts == [Alert("Sample title", "Something made up went wrong.", Level.ERROR)]


def test_a_warning_is_the_familys_yellow_triangle_window(qapp, alerts):
    alert.warning("Sample title", "Open a made-up window first.")

    assert alerts == [Alert("Sample title", "Open a made-up window first.", Level.WARNING)]


def test_the_alert_wears_the_apps_icon(qapp):
    icon = MagicMock()

    with alert_shown() as shown, patch.object(alert, "window_icon", return_value=icon):
        alert.warning("Sample title", "A made-up warning.")

    assert shown.call_args.kwargs["icon"] is icon


def test_an_alert_qt_cannot_open_is_said_in_a_windows_window_instead(qapp):
    with alert_shown(side_effect=RuntimeError("no Qt today")), error_popup() as windows:
        alert.error("Sample title", "A made-up error.")

    windows.assert_called_once_with("Sample title", "A made-up error.", app_icon=alert.ICON_FILE)
