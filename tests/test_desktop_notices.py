from __future__ import annotations

from PIL import Image
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QSystemTrayIcon
from shared_ui.palette import PREVIEW_INK
from shared_ui.preview import Preview

from origenerator.generation_state import GenerationSource
from origenerator.gui import desktop_notices
from origenerator.gui.desktop_notices import DesktopNotices
from origenerator.run_notice import RunOutcome
from origenerator.win32 import APP_USER_MODEL_ID


def _outcome(**over):
    fields = dict(kind="Video", recipe="WAN 2.2 Image-to-Video", seconds=252.0,
                  ok=True, source=GenerationSource.GENERATED)
    return RunOutcome(**{**fields, **over})


def test_a_long_run_reaches_the_desktop_as_a_windows_notification(qapp, monkeypatch):
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


def test_it_tells_windows_what_to_call_this_app_and_what_mark_to_draw(qapp, monkeypatch, tmp_path):
    # Windows heads a notification with whatever is registered under the id the
    # process claims, and draws a generic glyph where it finds no mark.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    registered = []
    monkeypatch.setattr(desktop_notices, "register_notification_identity",
                        lambda app_id, **named: registered.append((app_id, named)))

    DesktopNotices(QIcon())

    app_id, named = registered[0]
    assert app_id == APP_USER_MODEL_ID
    assert named["name"] == "Origenerator"
    # The app's own O, as a real file — and outside any checkout, so the entry
    # outlives the copy of the app that wrote it.
    assert named["icon"].read_bytes().startswith(b"\x89PNG")
    assert tmp_path in named["icon"].parents


def test_a_previews_notices_are_headed_by_the_feature_it_demos_beside_the_amber_letter(
        qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    registered = []
    monkeypatch.setattr(desktop_notices, "register_notification_identity",
                        lambda app_id, **named: registered.append((app_id, named)))

    notices = DesktopNotices(QIcon(), shown_as=Preview(feature="the new seed row"))

    app_id, named = registered[0]
    assert app_id == f"{APP_USER_MODEL_ID}.Preview"
    assert named["name"] == notices._tray.toolTip() == "Origenerator \u2014 preview of the new seed row"
    with Image.open(named["icon"]) as mark:
        assert mark.convert("RGBA").getpixel((mark.width // 2, 40))[:3] == PREVIEW_INK
