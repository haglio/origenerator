from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from origenerator.gui import media_overlay
from origenerator.gui.position_caption import PositionCaption


def test_the_caption_restacks_its_own_window_when_it_says_a_position(qtbot, monkeypatch):
    raised = []
    monkeypatch.setattr(media_overlay, "raise_window_without_activating", raised.append)
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(800, 600)
    caption = PositionCaption(host)
    host.show()

    caption.show_position(3, 17)

    assert raised == [int(caption.winId())]
