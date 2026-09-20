from __future__ import annotations

from origenerator.gui import media_overlay
from origenerator.gui.osr2_control import Osr2Control
from origenerator.gui.show_hud import ShowHud, show_hud_model
from origenerator.gui.show_wiring import HudFacts, ShowActions
from origenerator.gui.slideshow_view import SlideshowView
from origenerator.slideshow import in_order
from tests.motion_doubles import FakeMotion
from tests.show_surface_fakes import FakeEngine


def _lit_order(model) -> list[str]:
    return [button.command for row in model.rows for button in row
            if button.command in ("portrait_shuffle", "portrait_latest") and button.lit]


def test_the_panel_lights_the_order_the_show_is_playing_in(qtbot):
    for order_label, lit in (("Latest", ["portrait_latest"]),
                             ("Shuffle", ["portrait_shuffle"]),
                             ("", [])):
        show = SlideshowView([("scene one.png", "image")], engine=FakeEngine(),
                             shuffle=in_order, hud=HudFacts(order_label=order_label))
        qtbot.addWidget(show)

        assert _lit_order(show_hud_model("portrait", show)) == lit, order_label


def test_the_hud_restacks_its_own_window_over_the_media_on_every_beat(qtbot, monkeypatch):
    raised = []
    monkeypatch.setattr(media_overlay, "raise_window_without_activating", raised.append)
    show = SlideshowView([("scene one.png", "image"), ("scene two.mp4", "video")],
                         engine=FakeEngine(), shuffle=in_order)
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
                         engine=FakeEngine(), shuffle=in_order)
    qtbot.addWidget(show)
    show.show()
    hud = ShowHud(show, side="portrait", dashboard_cmd_file=None)
    show.adopt_hud(hud)
    show.step(1)
    raised.clear()

    hud._tick()

    assert raised == [int(hud.winId())]


class TestTheOnePanelAShowWears:
    """A show used to wear TWO panels: the players' HUD for the set, and Genau's
    whole console seated under it for the device.  Between them the status was
    said twice and disagreed -- "Looping seeds · Shuffle" over "Unlocked · 4s" --
    and prev, next, lock and trash were drawn on both.

    One panel now: the players' HUD, carrying the device's line and the drive
    readout out of the console's own code.
    """

    @staticmethod
    def _show(qtbot, **kwargs):
        motion = FakeMotion()
        show = SlideshowView([("scene one.png", "image"), ("scene two.png", "image")],
                             engine=FakeEngine(), shuffle=in_order, motion=motion,
                             actions=ShowActions(osr2_control=Osr2Control(motion)),
                             **kwargs)
        qtbot.addWidget(show)
        return show

    def test_the_show_floats_no_second_panel(self, qtbot):
        from origenerator.gui.motion_panel import MotionPanel

        assert self._show(qtbot).findChildren(MotionPanel) == []

    def _model(self, qtbot):
        show = self._show(qtbot)
        return show_hud_model("portrait", show, device=show.hud_device)

    def test_the_device_is_on_the_one_panel(self, qtbot):
        model = self._model(qtbot)

        assert model.osr2 != ""          # who has the device
        assert model.drive is not None   # and the motion it is being sent

    def test_the_pace_and_the_motion_are_rows_on_it(self, qtbot):
        posted = [button.command for row in self._model(qtbot).rows for button in row]

        assert "genau_clip_seconds_up" in posted
        assert "robot_hand_cycle_shape" in posted
        assert "osr2_control_off" in posted

    def test_the_transport_is_drawn_once(self, qtbot):
        """The console's own prev/next/lock/trash row is off it: the side's
        four are already there, and they act on the very same show."""
        posted = [button.command for row in self._model(qtbot).rows for button in row]

        assert posted.count("portrait_prev") == 1
        assert "genau_prev_clip" not in posted
        assert "main_lock" not in posted
        assert "genau_weird_clip" not in posted

    def test_a_press_on_the_motion_row_reaches_the_motion(self, qtbot):
        show = self._show(qtbot)
        hud = ShowHud(show, side="portrait", dashboard_cmd_file=None)
        qtbot.addWidget(hud)

        hud._deliver("robot_hand_cycle_shape")

        assert "shape" in show._motion.calls

    def test_a_press_on_the_transport_still_reaches_the_show(self, qtbot):
        """The device rows sit beside the side's own band, not in place of it."""
        show = self._show(qtbot)
        hud = ShowHud(show, side="portrait", dashboard_cmd_file=None)
        qtbot.addWidget(hud)
        before = show._playlist.index

        hud._deliver("portrait_next")

        assert show._playlist.index != before
