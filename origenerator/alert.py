# Qt is imported inside the calls: the startup windows come through here before anything has imported Qt.

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

CHECKOUT = Path(__file__).resolve().parent.parent
ICON_FILE = CHECKOUT / "icon.ico"


def error(title: str, message: str) -> None:
    _show(title, message, "ERROR")


def warning(title: str, message: str) -> None:
    _show(title, message, "WARNING")


def information(title: str, message: str, *, copyable: bool = True) -> None:
    _show(title, message, "INFO", copyable=copyable)


def window_icon():
    from shared_ui.preview_icon import app_icon  # noqa: PLC0415

    from origenerator.branch_session import shown_as  # noqa: PLC0415

    return app_icon(ICON_FILE, shown_as(CHECKOUT))


def _show(title: str, message: str, level: str, *, copyable: bool = True) -> None:
    try:
        from shared_ui import alert  # noqa: PLC0415

        alert.show_alert(title, message, level=alert.Level[level], icon=window_icon(), copyable=copyable)
    except Exception:
        log.exception("Could not open the alert window: %s", title)
        _fall_back_to_windows(title, message)


def _fall_back_to_windows(title: str, message: str) -> None:
    try:
        from app_support.win32 import show_error_popup  # noqa: PLC0415

        show_error_popup(title, message, app_icon=ICON_FILE)
    except Exception:
        log.exception("Could not open the Windows window either: %s", title)
