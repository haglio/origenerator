from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from origenerator.gui import media_overlay
from origenerator.gui.message import Message


def test_the_message_restacks_its_own_window_when_it_comes_up(qtbot, monkeypatch):
    raised = []
    monkeypatch.setattr(media_overlay, "raise_window_without_activating", raised.append)
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(800, 600)
    message = Message(host)
    host.show()

    message.say("scene one")

    assert raised == [int(message.winId())]
