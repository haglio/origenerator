from __future__ import annotations

import threading

from PyQt6.QtNetwork import QLocalServer

from origenerator import app_link
from origenerator.gui.link_listener import LinkListener


def _click(channel: str, generation: str) -> threading.Thread:
    handler = threading.Thread(
        target=app_link.hand_over, args=(generation,), kwargs={"channel": channel})
    handler.start()
    return handler


def test_a_click_on_a_toast_reaches_the_running_app(qtbot, tmp_path):
    asked = []
    listener = LinkListener(checkout=tmp_path, environ={})
    listener.answer_with(asked.append)

    _click(app_link.channel_for(tmp_path), "alpha-1")

    qtbot.waitUntil(lambda: asked == ["alpha-1"], timeout=5000)


def test_a_click_while_the_app_is_still_starting_is_answered_once_it_is_up(qtbot, tmp_path):
    asked = []
    listener = LinkListener(checkout=tmp_path, environ={})

    _click(app_link.channel_for(tmp_path), "alpha-1")
    qtbot.wait(300)
    assert asked == []

    listener.answer_with(asked.append)

    qtbot.waitUntil(lambda: asked == ["alpha-1"], timeout=5000)


def test_a_launch_a_click_started_opens_on_what_it_carried(qtbot, tmp_path):
    asked = []
    environment = {app_link.CARRIED_IN: "alpha-1"}
    listener = LinkListener(checkout=tmp_path, environ=environment)

    listener.answer_with(asked.append)

    assert asked == ["alpha-1"]
    assert environment == {}, (
        "taken out of the environment, not merely read: every child this app starts would "
        "otherwise inherit an instruction meant for this launch")


def test_asking_whether_the_app_is_listening_hands_it_no_click(qtbot, tmp_path):
    asked = []
    assert not app_link.listening(app_link.channel_for(tmp_path))
    listener = LinkListener(checkout=tmp_path, environ={})
    listener.answer_with(asked.append)

    assert app_link.listening(app_link.channel_for(tmp_path))
    qtbot.wait(300)

    assert asked == []


def test_a_channel_carrying_anything_but_a_generation_is_ignored(qtbot, tmp_path):
    asked = []
    listener = LinkListener(checkout=tmp_path, environ={})
    listener.answer_with(asked.append)

    _click(app_link.channel_for(tmp_path), "../../windows/system32")
    qtbot.wait(300)

    assert asked == [], (
        "whatever arrives is read as strictly as the link it came from: a link is open to "
        "anything that can reach a shell")


def test_a_launch_carrying_anything_but_a_generation_opens_on_nothing(qtbot, tmp_path):
    asked = []
    listener = LinkListener(checkout=tmp_path, environ={app_link.CARRIED_IN: "a b c"})

    listener.answer_with(asked.append)

    assert asked == []


def test_a_channel_that_cannot_be_opened_says_so(qtbot, tmp_path, caplog, monkeypatch):
    monkeypatch.setattr(QLocalServer, "listen", lambda *_a: False)

    with caplog.at_level("WARNING", logger="origenerator.gui.link_listener"):
        LinkListener(checkout=tmp_path, environ={})

    assert "clicks" in caplog.text.lower()
