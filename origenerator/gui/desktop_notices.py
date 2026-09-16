"""Origenerator's voice outside its own window.

What it says is :mod:`origenerator.run_notice`'s; this is the saying of it.

Windows hands a desktop app a notification through its tray icon — Qt's
``showMessage`` is that call (``Shell_NotifyIcon``), and a tray icon that was
never shown has nothing to hang one on — so one lives here for as long as the
app does. The other route, WinRT's own toast API, wants the app registered in
the Start menu under the AppUserModelID the process claims
(:mod:`origenerator.win32`), and nothing installs Origenerator there.

The heading over that notification, and the mark beside it, are not the tray
icon's: Windows reads them off the id the process claims, and draws the id
itself and a generic glyph where it finds nothing registered. So this names the
app there too, in the same place every app on the desktop names itself.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from PyQt6.QtCore import QObject
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QSystemTrayIcon

from origenerator.icon_design import render_icon
from origenerator.run_notice import RunOutcome, notice_for
from origenerator.win32 import APP_USER_MODEL_ID, register_notification_identity

logger = logging.getLogger(__name__)

# What Windows calls this app over a notification, and in its notification
# settings — the app's name, not the id the taskbar groups by.
APP_NAME = "Origenerator"

# The mark's size in pixels square. The master the .ico is cut from, so Windows
# scales it down to whatever the notification draws rather than up.
_MARK_PX = 256


def _the_apps_mark() -> Path:
    """Origenerator's O, written where a notification can still find it later.

    Outside the checkout on purpose. What is registered below outlives the copy
    of the app that registered it, and a branch preview's tree does not, so a
    mark named inside one would be gone by the next notification.
    """
    home = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
    mark = home / APP_NAME / "notification.png"
    mark.parent.mkdir(parents=True, exist_ok=True)
    render_icon(_MARK_PX).save(mark)
    return mark


class DesktopNotices(QObject):
    """The tray icon Windows' notifications come from, and what reaches it."""

    def __init__(self, icon: QIcon, parent=None):
        super().__init__(parent)
        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip(APP_NAME)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray.show()
        self._name_this_app_to_windows()

    def note(self, outcome: RunOutcome) -> None:
        """Say what a run came to, if it is one worth interrupting for."""
        notice = notice_for(outcome)
        if notice is None:
            return
        self._tray.showMessage(
            notice.title, notice.body,
            QSystemTrayIcon.MessageIcon.Information if notice.ok
            else QSystemTrayIcon.MessageIcon.Warning,
        )

    def _name_this_app_to_windows(self) -> None:
        try:
            register_notification_identity(
                APP_USER_MODEL_ID, name=APP_NAME, icon=_the_apps_mark())
        except Exception as e:
            # Broad on purpose: nothing about the heading over a notification is
            # worth a launch, and an unwritable mark fails in more ways than one.
            logger.warning("Notification identity unavailable: %s", e)
