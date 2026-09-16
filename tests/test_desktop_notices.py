from __future__ import annotations

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QSystemTrayIcon

from origenerator.generation_state import GenerationSource
from origenerator.gui.desktop_notices import DesktopNotices
from origenerator.run_notice import RunOutcome


def _outcome(**over):
    fields = dict(kind="Video", recipe="WAN 2.2 Image-to-Video", seconds=252.0,
                  ok=True, source=GenerationSource.GENERATED)
    return RunOutcome(**{**fields, **over})


def test_a_long_run_reaches_the_desktop_as_a_toast(qapp, monkeypatch):
    notices = DesktopNotices(QIcon())
    said = []
    monkeypatch.setattr(notices._tray, "showMessage", lambda *args: said.append(args))

    notices.note(_outcome())

    assert said == [("Video ready", "WAN 2.2 Image-to-Video · 4:12",
                     QSystemTrayIcon.MessageIcon.Information)]


def test_a_run_nobody_left_the_room_for_says_nothing(qapp, monkeypatch):
    notices = DesktopNotices(QIcon())
    said = []
    monkeypatch.setattr(notices._tray, "showMessage", lambda *args: said.append(args))

    notices.note(_outcome(kind="Image", recipe="SDXL Text-to-Image", seconds=9.0))

    assert said == []


def test_a_failed_run_wears_the_warning_mark(qapp, monkeypatch):
    notices = DesktopNotices(QIcon())
    said = []
    monkeypatch.setattr(notices._tray, "showMessage", lambda *args: said.append(args))

    notices.note(_outcome(ok=False))

    assert said[0][2] == QSystemTrayIcon.MessageIcon.Warning
