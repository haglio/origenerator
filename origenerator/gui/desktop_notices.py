"""Origenerator's voice outside its own window.

What it says is :mod:`origenerator.run_notice`'s; this is the saying of it.

Windows hands a desktop app a notification through its tray icon — Qt's
``showMessage`` is that call (``Shell_NotifyIcon``), and a tray icon that was
never shown has nothing to hang one on — so one lives here for as long as the
app does. The other route, WinRT's own toast API, wants the app registered in
the Start menu under the AppUserModelID the process claims
(:mod:`origenerator.win32`), and nothing installs Origenerator there.
"""
from __future__ import annotations

from PyQt6.QtCore import QObject
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QSystemTrayIcon

from origenerator.run_notice import RunOutcome, notice_for


class DesktopNotices(QObject):
    """The tray icon Windows' notifications come from, and what reaches it."""

    def __init__(self, icon: QIcon, parent=None):
        super().__init__(parent)
        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("Origenerator")
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray.show()

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
