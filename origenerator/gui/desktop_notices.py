"""Origenerator's voice outside its own window, and the way back in from it.

What it says is :mod:`origenerator.run_notice`'s; this is the saying of it, and
the answering of it.

A notification is a message to whoever comes back, which may be an hour later
with this app closed, so it is raised through Windows' own notification platform
(:mod:`origenerator.windows_toast`), which carries a link Windows follows
whenever it is answered (:mod:`origenerator.app_link`). The heading over it and
the mark beside it are read off the id the process claims, so this names the app
there too, and registers what a click runs beside it, because the copy that
raised a notice is the copy that should answer it.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from PyQt6.QtCore import QObject
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QStyle, QSystemTrayIcon
from shared_ui.preview import Preview, taskbar_identity, window_title
from shared_ui.preview_icon_pil import in_preview_ink

from origenerator import app_link
from origenerator.branch_session import is_branch_session
from origenerator.icon_design import render_icon
from origenerator.run_notice import RunOutcome, notice_for
from origenerator.win32 import (
    APP_USER_MODEL_ID,
    register_link_handler,
    register_notification_identity,
)
from origenerator.windows_toast import show as show_toast
from origenerator.windows_toast import toast_xml

logger = logging.getLogger(__name__)

# What Windows calls this app over a notification, and in its notification
# settings — the app's name, not the id the taskbar groups by.
APP_NAME = "Origenerator"

# The mark's size in pixels square. The master the .ico is cut from, so Windows
# scales it down to whatever the notification draws rather than up.
_MARK_PX = 256

# The glyph beside a notice, by whether the run landed: Windows' own two, which
# are what the tray icon's balloons drew for the same two answers.
_GLYPHS = {
    True: ("notice-ready.png", QStyle.StandardPixmap.SP_MessageBoxInformation),
    False: ("notice-failed.png", QStyle.StandardPixmap.SP_MessageBoxWarning),
}


def _where_marks_live() -> Path:
    """Outside the checkout on purpose. What is registered below outlives the
    copy of the app that registered it, and a branch preview's tree does not, so
    a mark named inside one would be gone by the next notification."""
    home = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
    return home / APP_NAME


def _the_apps_mark(shown_as: Preview | None) -> Path:
    """Origenerator's O, written where a notification can still find it later."""
    mark = _where_marks_live() / (
        "notification.png" if shown_as is None else "notification-preview.png")
    mark.parent.mkdir(parents=True, exist_ok=True)
    letter = render_icon(_MARK_PX)
    (letter if shown_as is None else in_preview_ink(letter)).save(mark)
    return mark


def _the_marks_beside_a_notice() -> dict[bool, Path | None]:
    """Windows' information and warning glyphs, written out where a toast can
    name them. ``None`` for one that could not be written: a notice with no
    glyph beside it still says what happened, which is what it is for."""
    marks: dict[bool, Path | None] = {}
    for landed, (name, glyph) in _GLYPHS.items():
        mark = _where_marks_live() / name
        try:
            mark.parent.mkdir(parents=True, exist_ok=True)
            drawn = QApplication.style().standardIcon(glyph).pixmap(_MARK_PX, _MARK_PX)
            marks[landed] = mark if drawn.save(str(mark)) else None
        except Exception as e:
            # Broad on purpose, as for the identity below: a notice with no
            # glyph beside it still says what happened.
            logger.warning("No mark to draw beside a notice: %s", e)
            marks[landed] = None
    return marks


class DesktopNotices(QObject):
    """What reaches the desktop when a run ends, and what a click on it does."""

    def __init__(self, icon: QIcon, parent=None, *, shown_as: Preview | None = None):
        super().__init__(parent)
        self._identity = taskbar_identity(APP_USER_MODEL_ID, shown_as)
        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip(window_title(APP_NAME, shown_as))
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray.show()
        self._marks = _the_marks_beside_a_notice()
        self._name_this_app_to_windows(shown_as)
        self._answer_clicks_here()

    def note(self, outcome: RunOutcome) -> None:
        """Say what a run came to, if it is one worth interrupting for."""
        notice = notice_for(outcome)
        if notice is None:
            return
        # Again per notice, not once per launch: a preview and the live app run
        # beside each other, and whichever raised THIS one is the one a click on
        # it should reach.
        self._answer_clicks_here()
        try:
            show_toast(self._identity,
                       toast_xml(notice.title, notice.body,
                                 link=app_link.link_to(notice.generation),
                                 mark=self._marks.get(notice.ok)))
        except OSError as e:
            # A run nobody hears about is a shame; a run that takes the app down
            # as it lands is worse.
            logger.warning("Windows would not raise the notification: %s", e)

    def _name_this_app_to_windows(self, shown_as: Preview | None) -> None:
        try:
            register_notification_identity(
                self._identity, name=window_title(APP_NAME, shown_as),
                icon=_the_apps_mark(shown_as))
        except Exception as e:
            # Broad on purpose: nothing about the heading over a notification is
            # worth a launch, and an unwritable mark fails in more ways than one.
            logger.warning("Notification identity unavailable: %s", e)

    def _answer_clicks_here(self) -> None:
        """Have a click on this app's notices run this copy of the app's handler,
        and start this copy where nothing is running."""
        register_link_handler(
            app_link.SCHEME, name=APP_NAME,
            command=app_link.handler_command(
                checkout=app_link.CHECKOUT,
                interpreter=app_link.windowless_interpreter(),
                launcher=(app_link.PREVIEW_LAUNCHER if is_branch_session()
                          else app_link.LIVE_LAUNCHER)))
