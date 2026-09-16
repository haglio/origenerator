from __future__ import annotations

from unittest.mock import MagicMock

from origenerator.gui import media_overlay
from origenerator.gui.show_hud import ShowHud, show_hud_model
from origenerator.gui.show_wiring import HudFacts
from origenerator.gui.slideshow_view import SlideshowView
from origenerator.slideshow import in_order


def _lit_order(model) -> list[str]:
    return [button.command for row in model.rows for button in row
            if button.command in ("portrait_shuffle", "portrait_latest") and button.lit]


def test_the_panel_lights_the_order_the_show_is_playing_in(qtbot):
    for order_label, lit in (("Latest", ["portrait_latest"]),
                             ("Shuffle", ["portrait_shuffle"]),
                             ("", [])):
        show = SlideshowView([("scene one.png", "image")], player=MagicMock(),
                             shuffle=in_order, hud=HudFacts(order_label=order_label))
        qtbot.addWidget(show)

        assert _lit_order(show_hud_model("portrait", show)) == lit, order_label


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


def test_the_hud_restacks_its_own_window_when_the_slide_it_lights_changes(qtbot, monkeypatch):
    raised = []
    monkeypatch.setattr(media_overlay, "raise_window_without_activating", raised.append)
    show = SlideshowView([("scene one.png", "image"), ("scene two.mp4", "video")],
                         player=MagicMock(), shuffle=in_order)
    qtbot.addWidget(show)
    show.show()
    hud = ShowHud(show, side="portrait", dashboard_cmd_file=None)
    show.adopt_hud(hud)
    show.step(1)
    raised.clear()

    hud._tick()

    assert raised == [int(hud.winId())]
