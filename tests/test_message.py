from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from origenerator.gui import media_overlay
from origenerator.gui.message import Message, time_to_read_ms


def _a_message_over_a_surface(qtbot) -> tuple[QWidget, Message]:
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(800, 600)
    message = Message(host)
    host.show()
    return host, message


def test_the_message_restacks_its_own_window_when_it_comes_up(qtbot, monkeypatch):
    raised = []
    monkeypatch.setattr(media_overlay, "raise_window_without_activating", raised.append)
    _host, message = _a_message_over_a_surface(qtbot)

    message.say("scene one")

    assert raised == [int(message.winId())]


def test_the_message_is_a_child_of_the_surface_it_is_about(qtbot):
    host, message = _a_message_over_a_surface(qtbot)

    message.say("scene one")

    assert (message.parentWidget() is host, message.isWindow()) == (True, False), (
        "the surface the message is about is this app's own, so the message is its child rather "
        "than a window of its own, as Fun Time's is over another app's Funestra")


def test_a_message_stays_up_until_something_says_otherwise(qtbot):
    _host, message = _a_message_over_a_surface(qtbot)
    message.say("scene one")

    qtbot.wait(time_to_read_ms("scene one") + 200)

    assert message.isVisible(), (
        "a message puts its text up and keeps it up: what takes it down is up to whatever put "
        "it there")
