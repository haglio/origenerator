from __future__ import annotations

import pytest
from PySide6.QtWidgets import QWidget
from shared_ui.message_shape import MESSAGE_TOP_MARGIN

from origenerator.gui import media_overlay
from origenerator.gui.message import HEARD_MARK, Message, time_to_read_ms


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


_LONG = ("a model's answer that runs on and on about every change it made to the prompt, "
         "far longer than any slideshow is wide")


@pytest.mark.parametrize("mark", ["", HEARD_MARK])
def test_a_message_too_long_for_the_slideshow_is_elided_to_fit(qtbot, mark):
    host, message = _a_message_over_a_surface(qtbot)
    host.resize(400, 300)

    message.say(_LONG, mark=mark)

    assert (message.geometry().left() >= MESSAGE_TOP_MARGIN,
            message.geometry().right() < host.width() - MESSAGE_TOP_MARGIN,
            "…" in message.text()) == (True, True, True)


def test_a_message_follows_its_slideshow_when_the_slideshow_widens(qtbot):
    host, message = _a_message_over_a_surface(qtbot)
    host.resize(400, 300)
    message.say(_LONG)

    host.resize(4000, 300)
    message.reposition()

    assert message.text() == _LONG


def test_a_message_that_fits_is_shown_whole(qtbot):
    _host, message = _a_message_over_a_surface(qtbot)

    message.say("scene one")

    assert message.text() == "scene one"
