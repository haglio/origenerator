"""What this app says on the desktop, and the way back in from what it says.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

from PIL import Image
from PyQt6.QtGui import QIcon
from shared_ui.palette import PREVIEW_INK
from shared_ui.preview import Preview

from origenerator import app_link, notice_toast
from origenerator.generation_state import GenerationSource
from origenerator.gui import desktop_notices
from origenerator.gui.desktop_notices import DesktopNotices
from origenerator.run_notice import RunOutcome
from origenerator.win32 import APP_USER_MODEL_ID


def _outcome(**over):
    fields = dict(kind="Video", recipe="WAN 2.2 Image-to-Video", seconds=252.0,
                  ok=True, source=GenerationSource.GENERATED,
                  generation="7f0c9b2e-1111-4444-8888-aaaabbbbcccc")
    return RunOutcome(**{**fields, **over})


def _raised(monkeypatch):
    said = []
    monkeypatch.setattr(notice_toast, "show",
                        lambda app_id, xml, **_filing: said.append((app_id, xml)))
    return said


def _toast(said):
    return ElementTree.fromstring(said[0][1])


def _lines(said):
    return [text.text for text in _toast(said).findall("./visual/binding/text")]


def test_a_long_run_reaches_the_desktop_as_a_windows_notification(qapp, monkeypatch):
    notices = DesktopNotices(QIcon())
    said = _raised(monkeypatch)

    notices.note(_outcome())

    assert said[0][0] == APP_USER_MODEL_ID
    assert _lines(said) == ["Video ready", "WAN 2.2 Image-to-Video · 4:12"]


def test_a_run_nobody_left_the_room_for_says_nothing(qapp, monkeypatch):
    notices = DesktopNotices(QIcon())
    said = _raised(monkeypatch)

    notices.note(_outcome(seconds=9.0))

    assert said == []


def test_a_failed_run_wears_the_warning_mark(qapp, monkeypatch):
    notices = DesktopNotices(QIcon())
    said = _raised(monkeypatch)

    notices.note(_outcome(ok=False))
    failed = _toast(said).find("./visual/binding/image").get("src")
    said.clear()
    notices.note(_outcome(ok=True))

    assert failed.endswith("notice-failed.png")
    assert _toast(said).find("./visual/binding/image").get("src").endswith("notice-ready.png")


def test_a_notice_carries_the_way_back_to_what_it_is_about(qapp, monkeypatch):
    # The whole of what a click has to go on: the run is over, the app may be
    # closed by the time anyone answers, and Windows keeps nothing but the link.
    notices = DesktopNotices(QIcon())
    said = _raised(monkeypatch)

    notices.note(_outcome())

    assert app_link.generation_in(_toast(said).get("launch")) == \
        "7f0c9b2e-1111-4444-8888-aaaabbbbcccc"


def test_the_copy_that_raises_a_notice_is_the_copy_a_click_on_it_reaches(
        qapp, monkeypatch):
    # A branch preview runs beside the live app, and its notices are the only
    # ones that can show what the branch does: the click has to land in the
    # preview's own code, which is the only copy that has the change in it.
    registered = []
    monkeypatch.setattr(desktop_notices, "register_link_handler",
                        lambda scheme, **named: registered.append((scheme, named)))
    notices = DesktopNotices(QIcon())
    _raised(monkeypatch)

    notices.note(_outcome())

    scheme, named = registered[-1]
    assert scheme == app_link.SCHEME
    assert str(app_link.CHECKOUT / app_link.HANDLER) in named["command"]
    assert named["command"].endswith('"%1"')


def test_a_preview_answers_its_click_by_starting_the_preview(qapp, monkeypatch):
    registered = []
    monkeypatch.setattr(desktop_notices, "register_link_handler",
                        lambda scheme, **named: registered.append(named))
    monkeypatch.setattr(desktop_notices, "is_branch_session", lambda: True)

    DesktopNotices(QIcon())

    assert app_link.PREVIEW_LAUNCHER in registered[0]["command"]


def test_the_handler_windows_runs_is_one_that_opens_no_console(qapp, monkeypatch):
    registered = []
    monkeypatch.setattr(desktop_notices, "register_link_handler",
                        lambda scheme, **named: registered.append(named))

    DesktopNotices(QIcon())

    assert registered[0]["command"].startswith('"')
    assert Path(registered[0]["command"].split('"')[1]).name == "pythonw.exe"


def test_windows_refusing_the_notification_costs_the_app_nothing(qapp, monkeypatch, caplog):
    def refuse(app_id, xml, **_filing):
        raise OSError("the notification platform is not listening")

    notices = DesktopNotices(QIcon())
    monkeypatch.setattr(notice_toast, "show", refuse)

    with caplog.at_level("WARNING", logger="origenerator.notice_toast"):
        notices.note(_outcome())

    assert "not listening" in caplog.text


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


def test_the_marks_beside_a_notice_outlive_the_copy_that_wrote_them(
        qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    notices = DesktopNotices(QIcon())
    said = _raised(monkeypatch)

    notices.note(_outcome())

    mark = Path(_toast(said).find("./visual/binding/image").get("src")[len("file:///"):])
    assert mark.read_bytes().startswith(b"\x89PNG")
    assert tmp_path in mark.parents


def test_a_mark_that_cannot_be_written_leaves_the_notice_to_speak_for_itself(
        qapp, monkeypatch, tmp_path):
    # Every failure here is Windows' side of the fence: what matters is that the
    # run is announced at all, so a missing glyph must not swallow the notice.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "unwritable"))
    (tmp_path / "unwritable").write_text("not a directory", encoding="utf-8")
    notices = DesktopNotices(QIcon())
    said = _raised(monkeypatch)

    notices.note(_outcome())

    assert _lines(said) == ["Video ready", "WAN 2.2 Image-to-Video · 4:12"]
    assert _toast(said).find("./visual/binding/image") is None
