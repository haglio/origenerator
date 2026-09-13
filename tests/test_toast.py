from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from origenerator.gui import media_overlay
from origenerator.gui.toast import Toast


def test_the_toast_restacks_its_own_window_when_it_comes_up(qtbot, monkeypatch):
    raised = []
    monkeypatch.setattr(media_overlay, "raise_window_without_activating", raised.append)
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(800, 600)
    toast = Toast(host)
    host.show()

    toast.say("scene one")

    assert raised == [int(toast.winId())]
