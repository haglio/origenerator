"""Origenerator's voice outside its own window, and the way back in from it.

What it says is :mod:`origenerator.run_toast`'s; this is the saying of it, and
the answering of it.

A toast is a message to whoever comes back, which may be an hour later
with this app closed, so it is raised through Windows' own toast platform
(:mod:`origenerator.windows_toast`), which carries a link Windows follows
whenever it is answered (:mod:`origenerator.app_link`). The heading over it and
the mark beside it are read off the id the process claims, so this names the app
there too, and registers what a click runs beside it: production Origenerator,
whichever copy raised the toast.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from app_support.win32 import seconds_since_input
from PyQt6.QtCore import QObject, Qt, QTimer
from PyQt6.QtGui import QGuiApplication, QIcon
from PyQt6.QtWidgets import QSystemTrayIcon
from shared_ui.alert import Level, icon_pixmap_for
from shared_ui.preview import Preview, taskbar_identity, window_title
from shared_ui.preview_icon_pil import in_preview_ink

from origenerator import app_link
from origenerator.config import PRODUCTION_CHECKOUT
from origenerator.icon_design import render_icon
from origenerator.run_toast import RunOutcome, toast_for
from origenerator.toast_raising import raise_toast, take_back_toast
from origenerator.win32 import (
    APP_USER_MODEL_ID,
    register_link_handler,
    register_toast_identity,
)

logger = logging.getLogger(__name__)

# What Windows calls this app over a toast, and in its Notifications
# settings — the app's name, not the id the taskbar groups by.
APP_NAME = "Origenerator"

# The mark's size in pixels square. The master the .ico is cut from, so Windows
# scales it down to whatever the toast draws rather than up.
_MARK_PX = 256

# The mark beside a toast, by whether the run landed: the family's information
# and warning marks, which its alert dialogs wear for the same two answers.
_TOAST_MARKS = {
    True: ("toast-ready.png", Level.INFO),
    False: ("toast-failed.png", Level.WARNING),
}

AWAY_AFTER_S = 120.0
_LOOK_EVERY_MS = 2000


def app_in_front() -> bool:
    return QGuiApplication.applicationState() == Qt.ApplicationState.ApplicationActive


def _away() -> bool:
    try:
        return seconds_since_input() > AWAY_AFTER_S
    except OSError:
        return True


def _where_marks_live() -> Path:
    """Outside the checkout on purpose. What is registered below outlives the
    copy of the app that registered it, and a branch preview's tree does not, so
    a mark named inside one would be gone by the next toast."""
    home = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
    return home / APP_NAME


def _the_apps_mark(shown_as: Preview | None) -> Path:
    """Origenerator's O, written where a toast can still find it later."""
    mark = _where_marks_live() / (
        "toast.png" if shown_as is None else "toast-preview.png")
    mark.parent.mkdir(parents=True, exist_ok=True)
    letter = render_icon(_MARK_PX)
    (letter if shown_as is None else in_preview_ink(letter)).save(mark)
    return mark


def _the_marks_beside_a_toast() -> dict[bool, Path | None]:
    """The family's information and warning marks, written out where a toast can
    name them. ``None`` for one that could not be written: a toast with no
    glyph beside it still says what happened, which is what it is for."""
    marks: dict[bool, Path | None] = {}
    for landed, (name, level) in _TOAST_MARKS.items():
        mark = _where_marks_live() / name
        try:
            mark.parent.mkdir(parents=True, exist_ok=True)
            drawn = icon_pixmap_for(level, _MARK_PX)
            marks[landed] = mark if drawn.save(str(mark)) else None
        except Exception as e:
            # Broad on purpose, as for the identity below: a toast with no
            # glyph beside it still says what happened.
            logger.warning("No mark to draw beside a toast: %s", e)
            marks[landed] = None
    return marks


class Toasts(QObject):
    """What reaches the desktop when a run ends, what a click on it does, and
    taking it back once its video has been watched here."""

    def __init__(self, icon: QIcon, parent=None, *, shown_as: Preview | None = None,
                 video_in_front=lambda: None):
        super().__init__(parent)
        self._identity = taskbar_identity(APP_USER_MODEL_ID, shown_as)
        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip(window_title(APP_NAME, shown_as))
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray.show()
        self._marks = _the_marks_beside_a_toast()
        self._name_this_app_to_windows(shown_as)
        self._answer_clicks_with_production()
        self._video_in_front = video_in_front
        self._watched: set[str] = set()
        self._looks = QTimer(self)
        self._looks.timeout.connect(self.look)
        self._looks.start(_LOOK_EVERY_MS)

    def note(self, outcome: RunOutcome) -> None:
        """Say what a run came to, if it is one worth interrupting for."""
        toast = toast_for(outcome)
        if toast is None:
            return
        self._watched.discard(toast.generation)
        raise_toast(self._identity, toast, mark=self._marks.get(toast.ok))

    def look(self) -> None:
        video = self._video_in_front()
        if video is None or video in self._watched:
            return
        if not app_in_front() or _away():
            return
        self._watched.add(video)
        take_back_toast(self._identity, video)

    def _name_this_app_to_windows(self, shown_as: Preview | None) -> None:
        try:
            register_toast_identity(
                self._identity, name=window_title(APP_NAME, shown_as),
                icon=_the_apps_mark(shown_as))
        except Exception as e:
            # Broad on purpose: nothing about the heading over a toast is
            # worth a launch, and an unwritable mark fails in more ways than one.
            logger.warning("Toast identity unavailable: %s", e)

    def _answer_clicks_with_production(self) -> None:
        register_link_handler(
            app_link.SCHEME, name=APP_NAME,
            command=app_link.handler_command(
                checkout=PRODUCTION_CHECKOUT,
                interpreter=app_link.windowless_interpreter()))
