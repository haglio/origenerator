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
from shared_ui.app_icon import CANVAS
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

APP_NAME = "Origenerator"

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
    home = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
    return home / APP_NAME


def _the_apps_mark(shown_as: Preview | None) -> Path:
    mark = _where_marks_live() / (
        "toast.png" if shown_as is None else "toast-preview.png")
    mark.parent.mkdir(parents=True, exist_ok=True)
    letter = render_icon()
    (letter if shown_as is None else in_preview_ink(letter)).save(mark)
    return mark


def _the_marks_beside_a_toast() -> dict[bool, Path | None]:
    marks: dict[bool, Path | None] = {}
    for landed, (name, level) in _TOAST_MARKS.items():
        mark = _where_marks_live() / name
        try:
            mark.parent.mkdir(parents=True, exist_ok=True)
            drawn = icon_pixmap_for(level, CANVAS)
            marks[landed] = mark if drawn.save(str(mark)) else None
        except Exception as e:
            logger.warning("No mark to draw beside a toast: %s", e)
            marks[landed] = None
    return marks


class Toasts(QObject):
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
            logger.warning("Toast identity unavailable: %s", e)

    def _answer_clicks_with_production(self) -> None:
        register_link_handler(
            app_link.SCHEME, name=APP_NAME,
            command=app_link.handler_command(
                checkout=PRODUCTION_CHECKOUT,
                interpreter=app_link.windowless_interpreter()))
