"""Where a click on a notification reaches the running app.

Both ends meet here: what the handler Windows runs writes
(:func:`origenerator.app_link.hand_over`) and what the app hears. The write is
made from a thread of its own because the pipe holds it until this side reads,
which on one thread would be a wait that never ends.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
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


def test_a_click_on_a_notice_reaches_the_running_app(qtbot, tmp_path):
    asked = []
    listener = LinkListener(checkout=tmp_path, environ={})
    listener.answer_with(asked.append)

    _click(app_link.channel_for(tmp_path), "alpha-1")

    qtbot.waitUntil(lambda: asked == ["alpha-1"], timeout=5000)


def test_a_click_while_the_app_is_still_starting_is_answered_once_it_is_up(qtbot, tmp_path):
    # A launch here is slow -- ComfyUI's server, the whole library scanned --
    # and a click during it is a click the user made, not one to drop.
    asked = []
    listener = LinkListener(checkout=tmp_path, environ={})

    _click(app_link.channel_for(tmp_path), "alpha-1")
    qtbot.wait(300)
    assert asked == []

    listener.answer_with(asked.append)

    qtbot.waitUntil(lambda: asked == ["alpha-1"], timeout=5000)


def test_a_launch_a_click_started_opens_on_what_it_carried(qtbot, tmp_path):
    # Nothing was running to hand it to, so the generation rode in on the
    # launch's own environment (origenerator.app_link.start_the_app).
    asked = []
    environment = {app_link.CARRIED_IN: "alpha-1"}
    listener = LinkListener(checkout=tmp_path, environ=environment)

    listener.answer_with(asked.append)

    assert asked == ["alpha-1"]
    # Taken back out, or every child this app starts -- ComfyUI's server among
    # them -- inherits an instruction meant for this launch alone.
    assert environment == {}


def test_a_channel_carrying_anything_but_a_generation_is_ignored(qtbot, tmp_path):
    asked = []
    listener = LinkListener(checkout=tmp_path, environ={})
    listener.answer_with(asked.append)

    _click(app_link.channel_for(tmp_path), "../../windows/system32")
    qtbot.wait(300)

    assert asked == []


def test_a_launch_carrying_anything_but_a_generation_opens_on_nothing(qtbot, tmp_path):
    asked = []
    listener = LinkListener(checkout=tmp_path, environ={app_link.CARRIED_IN: "a b c"})

    listener.answer_with(asked.append)

    assert asked == []


def test_a_channel_that_cannot_be_opened_says_so(qtbot, tmp_path, caplog, monkeypatch):
    # Nothing on screen says whether clicks can be answered, so an app that
    # could not open its channel would look exactly like one whose notices
    # nobody has clicked.
    monkeypatch.setattr(QLocalServer, "listen", lambda *_a: False)

    with caplog.at_level("WARNING", logger="origenerator.gui.link_listener"):
        LinkListener(checkout=tmp_path, environ={})

    assert "clicks" in caplog.text.lower()
