"""What this app says on the desktop, and the way back in from what it says.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

from PIL import Image
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QWidget
from shared_ui.palette import PREVIEW_INK
from shared_ui.preview import Preview

from origenerator import app_link, toast_raising
from origenerator.generation_state import GenerationSource
from origenerator.gui import toasts as toasts_module
from origenerator.gui.toasts import Toasts
from origenerator.run_toast import RunOutcome
from origenerator.win32 import APP_USER_MODEL_ID


def _outcome(**over):
    fields = dict(kind="Video", display_name="WAN 2.2 I2V", seconds=252.0,
                  ok=True, source=GenerationSource.GENERATED,
                  generation="7f0c9b2e-1111-4444-8888-aaaabbbbcccc")
    return RunOutcome(**{**fields, **over})


def _raised(monkeypatch):
    said = []
    monkeypatch.setattr(toast_raising, "show",
                        lambda app_id, xml, **_filing: said.append((app_id, xml)))
    return said


def _toast(said):
    return ElementTree.fromstring(said[0][1])


def _lines(said):
    return [text.text for text in _toast(said).findall("./visual/binding/text")]


def test_a_long_run_reaches_the_desktop_as_a_windows_notification(qapp, monkeypatch):
    toasts = Toasts(QIcon())
    said = _raised(monkeypatch)

    toasts.note(_outcome())

    assert said[0][0] == APP_USER_MODEL_ID
    assert _lines(said) == ["Video ready", "WAN 2.2 I2V · 4:12"]


def test_a_run_nobody_left_the_room_for_says_nothing(qapp, monkeypatch):
    toasts = Toasts(QIcon())
    said = _raised(monkeypatch)

    toasts.note(_outcome(seconds=9.0))

    assert said == []


def test_a_failed_run_wears_the_warning_mark(qapp, monkeypatch):
    toasts = Toasts(QIcon())
    said = _raised(monkeypatch)

    toasts.note(_outcome(ok=False))
    failed = _toast(said).find("./visual/binding/image").get("src")
    said.clear()
    toasts.note(_outcome(ok=True))

    assert failed.endswith("toast-failed.png")
    assert _toast(said).find("./visual/binding/image").get("src").endswith("toast-ready.png")


def test_a_toast_carries_the_way_back_to_what_it_is_about(qapp, monkeypatch):
    # The whole of what a click has to go on: the run is over, the app may be
    # closed by the time anyone answers, and Windows keeps nothing but the link.
    toasts = Toasts(QIcon())
    said = _raised(monkeypatch)

    toasts.note(_outcome())

    assert app_link.generation_in(_toast(said).get("launch")) == \
        "7f0c9b2e-1111-4444-8888-aaaabbbbcccc"


def test_a_click_on_a_toast_runs_production_origenerators_handler_whichever_copy_raised_it(
        qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("ORIGENERATOR_BRANCH_SESSION", "1")
    monkeypatch.setattr(toasts_module, "PRODUCTION_CHECKOUT", tmp_path / "production")
    registered = []
    monkeypatch.setattr(toasts_module, "register_link_handler",
                        lambda scheme, **named: registered.append((scheme, named)))
    toasts = Toasts(QIcon())
    _raised(monkeypatch)

    toasts.note(_outcome())

    scheme, named = registered[-1]
    assert scheme == app_link.SCHEME
    assert str(tmp_path / "production" / app_link.HANDLER) in named["command"]
    assert named["command"].endswith('"%1"')


def test_a_click_with_no_copy_open_starts_production_origenerator_even_from_a_preview(
        qapp, monkeypatch):
    monkeypatch.setenv("ORIGENERATOR_BRANCH_SESSION", "1")
    registered = []
    monkeypatch.setattr(toasts_module, "register_link_handler",
                        lambda scheme, **named: registered.append(named))

    Toasts(QIcon())

    assert f'"{app_link.LIVE_LAUNCHER}"' in registered[0]["command"]


def test_the_handler_windows_runs_is_one_that_opens_no_console(qapp, monkeypatch):
    registered = []
    monkeypatch.setattr(toasts_module, "register_link_handler",
                        lambda scheme, **named: registered.append(named))

    Toasts(QIcon())

    assert registered[0]["command"].startswith('"')
    assert Path(registered[0]["command"].split('"')[1]).name == "pythonw.exe"


def test_windows_refusing_the_notification_costs_the_app_nothing(qapp, monkeypatch, caplog):
    def refuse(app_id, xml, **_filing):
        raise OSError("the toast platform is not listening")

    toasts = Toasts(QIcon())
    monkeypatch.setattr(toast_raising, "show", refuse)

    with caplog.at_level("WARNING", logger="origenerator.toast_raising"):
        toasts.note(_outcome())

    assert "not listening" in caplog.text


def test_it_tells_windows_what_to_call_this_app_and_what_mark_to_draw(qapp, monkeypatch, tmp_path):
    # Windows heads a toast with whatever is registered under the id the
    # process claims, and draws a generic glyph where it finds no mark.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    registered = []
    monkeypatch.setattr(toasts_module, "register_toast_identity",
                        lambda app_id, **named: registered.append((app_id, named)))

    Toasts(QIcon())

    app_id, named = registered[0]
    assert app_id == APP_USER_MODEL_ID
    assert named["name"] == "Origenerator"
    # The app's own O, as a real file — and outside any checkout, so the entry
    # outlives the copy of the app that wrote it.
    assert named["icon"].read_bytes().startswith(b"\x89PNG")
    assert tmp_path in named["icon"].parents


def test_a_previews_toasts_are_headed_by_the_feature_it_demos_beside_the_yellow_letter(
        qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    registered = []
    monkeypatch.setattr(toasts_module, "register_toast_identity",
                        lambda app_id, **named: registered.append((app_id, named)))

    toasts = Toasts(QIcon(), shown_as=Preview(feature="the new seed row"))

    app_id, named = registered[0]
    assert app_id == f"{APP_USER_MODEL_ID}.Preview"
    assert named["name"] == toasts._tray.toolTip() == "Origenerator \u2014 preview of the new seed row"
    with Image.open(named["icon"]) as mark:
        assert mark.convert("RGBA").getpixel((mark.width // 2, 40))[:3] == PREVIEW_INK


def test_the_marks_beside_a_toast_outlive_the_copy_that_wrote_them(
        qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    toasts = Toasts(QIcon())
    said = _raised(monkeypatch)

    toasts.note(_outcome())

    mark = Path(_toast(said).find("./visual/binding/image").get("src")[len("file:///"):])
    assert mark.read_bytes().startswith(b"\x89PNG")
    assert tmp_path in mark.parents


def test_a_mark_that_cannot_be_written_leaves_the_toast_to_speak_for_itself(
        qapp, monkeypatch, tmp_path):
    # Every failure here is Windows' side of the fence: what matters is that the
    # run is announced at all, so a missing glyph must not swallow the toast.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "unwritable"))
    (tmp_path / "unwritable").write_text("not a directory", encoding="utf-8")
    toasts = Toasts(QIcon())
    said = _raised(monkeypatch)

    toasts.note(_outcome())

    assert _lines(said) == ["Video ready", "WAN 2.2 I2V · 4:12"]
    assert _toast(said).find("./visual/binding/image") is None


# --- a toast taken back once its video has been watched ----------------------

_RUN = "7f0c9b2e-1111-4444-8888-aaaabbbbcccc"


def _watching(monkeypatch, *, app_in_front=True, since_input=1.0):
    taken_back = []
    monkeypatch.setattr(toasts_module, "app_in_front", lambda: app_in_front)
    monkeypatch.setattr(toasts_module, "seconds_since_input", lambda: since_input)
    monkeypatch.setattr(toast_raising, "take_back",
                        lambda app_id, **filing: taken_back.append((app_id, filing["tag"])))
    return taken_back


def _filed_tag(monkeypatch, toasts):
    raised = []
    monkeypatch.setattr(toast_raising, "show",
                        lambda app_id, xml, **filing: raised.append((app_id, filing["tag"])))
    toasts.note(_outcome(generation=_RUN))
    return raised[-1]


def test_a_video_watched_in_the_app_in_front_takes_its_toast_back(qapp, monkeypatch):
    toasts = Toasts(QIcon(), video_in_front=lambda: _RUN)
    filed = _filed_tag(monkeypatch, toasts)
    taken_back = _watching(monkeypatch)

    toasts.look()

    assert taken_back == [filed]


def test_a_video_playing_while_another_app_is_in_front_keeps_its_toast(qapp, monkeypatch):
    toasts = Toasts(QIcon(), video_in_front=lambda: _RUN)
    taken_back = _watching(monkeypatch, app_in_front=False)

    toasts.look()

    assert taken_back == []


def test_a_video_playing_while_the_user_is_away_keeps_its_toast(qapp, monkeypatch):
    toasts = Toasts(QIcon(), video_in_front=lambda: _RUN)
    taken_back = _watching(monkeypatch, since_input=toasts_module.AWAY_AFTER_S + 1)

    toasts.look()

    assert taken_back == []


def test_a_user_whose_time_away_windows_will_not_say_is_taken_to_be_away(qapp, monkeypatch):
    def refuse():
        raise OSError("GetLastInputInfo failed")

    toasts = Toasts(QIcon(), video_in_front=lambda: _RUN)
    taken_back = _watching(monkeypatch)
    monkeypatch.setattr(toasts_module, "seconds_since_input", refuse)

    toasts.look()

    assert taken_back == []


def test_nothing_is_taken_back_while_no_video_is_in_front(qapp, monkeypatch):
    toasts = Toasts(QIcon(), video_in_front=lambda: None)
    taken_back = _watching(monkeypatch)

    toasts.look()

    assert taken_back == []


def test_a_video_watched_on_and_on_is_taken_back_once(qapp, monkeypatch):
    toasts = Toasts(QIcon(), video_in_front=lambda: _RUN)
    taken_back = _watching(monkeypatch)

    toasts.look()
    toasts.look()

    assert len(taken_back) == 1


def test_a_toast_raised_for_a_video_already_watched_is_taken_back_too(qapp, monkeypatch):
    # The run lands in the tab being watched: what is on screen may be looked at
    # a moment before the toast for it is raised.
    toasts = Toasts(QIcon(), video_in_front=lambda: _RUN)
    taken_back = _watching(monkeypatch)
    toasts.look()

    filed = _filed_tag(monkeypatch, toasts)
    toasts.look()

    assert taken_back[-1] == filed
    assert len(taken_back) == 2


def test_the_app_looks_on_its_own_every_few_seconds(qtbot, monkeypatch):
    window = QWidget()
    qtbot.addWidget(window)
    Toasts(QIcon(), window, video_in_front=lambda: _RUN)
    taken_back = _watching(monkeypatch)

    qtbot.waitUntil(lambda: bool(taken_back), timeout=5000)
