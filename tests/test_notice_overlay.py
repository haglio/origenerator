from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from origenerator.gui import media_overlay
from origenerator.gui.notice_overlay import NoticeOverlay


def test_the_notice_restacks_its_own_window_when_it_comes_up(qtbot, monkeypatch):
    raised = []
    monkeypatch.setattr(media_overlay, "raise_window_without_activating", raised.append)
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(800, 600)
    notice = NoticeOverlay(host)
    host.show()

    notice.say("scene one")

    assert raised == [int(notice.winId())]
