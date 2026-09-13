from __future__ import annotations

from unittest.mock import MagicMock

from origenerator.gui import media_overlay
from origenerator.gui.show_hud import ShowHud
from origenerator.gui.slideshow_view import SlideshowView
from origenerator.slideshow import in_order


def test_the_hud_restacks_its_own_window_over_the_media_on_every_beat(qtbot, monkeypatch):
    raised = []
    monkeypatch.setattr(media_overlay, "raise_window_without_activating", raised.append)
    show = SlideshowView([("scene one.png", "image"), ("scene two.mp4", "video")],
                         player=MagicMock(), shuffle=in_order)
    qtbot.addWidget(show)
    show.show()
    hud = ShowHud(show, side="portrait", dashboard_cmd_file=None)
    show.adopt_hud(hud)
    raised.clear()

    hud._tick()
    hud._tick()

    assert raised == [int(hud.winId())] * 2
