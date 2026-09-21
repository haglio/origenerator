from __future__ import annotations

from player_core.hud_placement import HudCorner
from player_core.satellite_hud import MARGIN
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QWheelEvent
from PyQt6.QtWidgets import QApplication

from origenerator.gui import media_overlay
from origenerator.gui.hud_queue import CANCEL, CLEAR, OPEN
from origenerator.gui.inflight import InFlightItem, RunReading
from origenerator.gui.motion_panel import MotionPanel
from origenerator.gui.osr2_control import Osr2Control
from origenerator.gui.show_hud import ShowHud, show_hud_model
from origenerator.gui.show_wiring import HudFacts, ShowActions
from origenerator.gui.slideshow_view import SlideshowView
from origenerator.slideshow import in_order
from origenerator.ui_scale import to_logical_size
from tests.motion_doubles import FakeMotion
from tests.show_surface_fakes import FakeEngine


def _inflight(key="j1", status="queued", cancel=None, **kw):
    reading = {name: kw.pop(name) for name in list(kw)
               if name in ("frame", "progress", "started_at", "typical_seconds")}
    return InFlightItem(key=key, caption="Alpha Workflow › a paper kite",
                        reading=RunReading(status=status, **reading),
                        reveal=kw.pop("reveal", lambda: None), cancel=cancel, **kw)


def _mouse(kind, x, y, buttons=Qt.MouseButton.LeftButton):
    return QMouseEvent(kind, QPointF(x, y), QPointF(x, y), Qt.MouseButton.LeftButton,
                       buttons, Qt.KeyboardModifier.NoModifier)


def _rect_of(hud, command):
    return next(rect for rect, button in hud._targets.buttons
                if button.command == command)


def _press_and_release(hud, command, travel=(0, 0)):
    """Press the panel where *command* was drawn, and let go *travel* away."""
    x, y, width, height = _rect_of(hud, command)
    start = (x + width // 2, y + height // 2)
    hud.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, *start))
    if travel != (0, 0):
        hud.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, start[0] + travel[0],
                                  start[1] + travel[1]))
    hud.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease,
                                 start[0] + travel[0], start[1] + travel[1],
                                 buttons=Qt.MouseButton.NoButton))


def _below(hud, command) -> int:
    """How far a press has to travel to let go over the lower half of that row."""
    row, target = _rect_of(hud, f"{OPEN}|j2"), _rect_of(hud, command)
    return target[1] + target[3] - 2 - (row[1] + row[3] // 2)


def _wheel(hud, command, delta):
    """Turn the wheel over the panel where *command* was drawn."""
    x, y, width, height = _rect_of(hud, command)
    where = QPointF(x + width // 2, y + height // 2)
    hud.wheelEvent(QWheelEvent(where, where, QPoint(0, 0), QPoint(0, delta),
                               Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                               Qt.ScrollPhase.NoScrollPhase, False))


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


def test_the_panel_carries_what_is_being_made_of_the_item_on_screen(qtbot):
    show = SlideshowView([("scene one.png", "image", "id-one")], engine=FakeEngine(),
                         shuffle=in_order)
    qtbot.addWidget(show)

    show.note_enhancing({"id-one": "running"})

    assert show_hud_model("portrait", show).item_note == "Enhancing…"


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
        assert self._show(qtbot).findChildren(MotionPanel) == []

    def _model(self, qtbot):
        show = self._show(qtbot)
        return show_hud_model("portrait", show, device=show.hud_device)

    def test_the_device_is_on_the_one_panel(self, qtbot):
        model = self._model(qtbot)

        assert model.osr2 != ""          # who has the device
        assert model.drive is not None   # and the motion it is being sent

    def test_the_osr2_line_carries_the_max_intensity_the_motion_is_held_to(self, qtbot):
        show = self._show(qtbot)
        show._motion.set_max_intensity(35)

        assert show_hud_model("portrait", show, device=show.hud_device).max_intensity == 35

    def test_a_show_that_is_not_driving_the_device_carries_no_max_intensity(self, qtbot):
        assert show_hud_model("portrait", self._show(qtbot)).max_intensity is None

    def test_the_pace_rides_with_the_rows_that_step_the_set(self, qtbot):
        """It sets how long an unheld slide stays up, which is about the set."""
        posted = [button.command for row in self._model(qtbot).rows for button in row]

        assert "genau_clip_seconds_up" in posted
        assert "robot_hand_cycle_shape" not in posted

    def test_everything_that_aims_the_device_rides_with_the_device(self, qtbot):
        """Cruise, human-inspired, the waveform, the quarter nudge and the four
        control states act on the OSR2, so they sit in its own block at the foot
        of the panel rather than up among the rows that act on the set."""
        model = self._model(qtbot)
        aiming = [button.command for row in model.osr2_rows for button in row]

        assert "robot_hand_toggle_cruise" in aiming
        assert "robot_hand_toggle_learned" in aiming
        assert "robot_hand_cycle_shape" in aiming
        assert "quarter_button" in aiming
        assert "osr2_control_off" in aiming

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

    def test_a_hosted_side_verb_still_goes_out_on_the_sessions_channel(self, qtbot, tmp_path):
        """The device rows are checked before the session's transport now, so a
        side verb that fell into them would be swallowed instead of posted."""
        show = self._show(qtbot)
        channel = tmp_path / "dashboard_cmd.txt"
        hud = ShowHud(show, side="portrait", dashboard_cmd_file=channel)
        qtbot.addWidget(hud)

        hud._deliver("portrait_next")

        assert channel.read_text(encoding="utf-8").split() == ["portrait_next"]

    def test_a_press_on_the_transport_still_reaches_the_show(self, qtbot):
        """The device rows sit beside the side's own band, not in place of it."""
        show = self._show(qtbot)
        hud = ShowHud(show, side="portrait", dashboard_cmd_file=None)
        qtbot.addWidget(hud)
        before = show._playlist.index

        hud._deliver("portrait_next")

        assert show._playlist.index != before


class TestWhereTheShowsPanelSits:
    """The room moves this panel round the corners of the show, and collapses it
    to a square with a plus on it."""

    @staticmethod
    def _show(qtbot):
        show = SlideshowView([("scene one.png", "image")], engine=FakeEngine(),
                             shuffle=in_order)
        qtbot.addWidget(show)
        show.resize(900, 600)
        show.show()
        return show

    def test_the_panel_moves_to_the_corner_it_is_given(self, qtbot):
        show = self._show(qtbot)
        hud = ShowHud(show, side="portrait", dashboard_cmd_file=None)
        show.adopt_hud(hud)

        hud.set_hud_place(HudCorner.LOWER_RIGHT, False)

        margin = to_logical_size(MARGIN)
        assert hud.pos().x() == show.width() - margin - hud.width()
        assert hud.pos().y() == show.height() - margin - hud.height()

    def test_a_collapsed_panel_is_the_plus_button_alone(self, qtbot):
        show = self._show(qtbot)
        hud = ShowHud(show, side="portrait", dashboard_cmd_file=None)
        show.adopt_hud(hud)
        wide = hud.width()

        hud.set_hud_place(HudCorner.UPPER_LEFT, True)

        assert hud.width() < wide
        assert [button.command for _rect, button in hud._targets.buttons] == [
            "portrait_hud_restore"]

    def test_a_standalone_press_on_the_minus_collapses_it_here(self, qtbot):
        show = self._show(qtbot)
        collapsed: list[bool] = []
        hud = ShowHud(show, side="portrait", dashboard_cmd_file=None,
                      collapse=collapsed.append)
        show.adopt_hud(hud)

        hud._deliver("portrait_hud_minimize")

        assert collapsed == [True]

    def test_a_click_landing_on_the_minus_is_what_collapses_it(self, qtbot):
        """The whole way in: a left button down on the square, where the panel
        drew it, and the panel is a plus by the time the button comes back up."""
        show = self._show(qtbot)
        collapsed: list[bool] = []
        hud = ShowHud(show, side="portrait", dashboard_cmd_file=None,
                      collapse=collapsed.append)
        show.adopt_hud(hud)
        (rect, _minus), = [(rect, button) for rect, button in hud._targets.buttons
                           if button.command.endswith("hud_minimize")]

        _click_at(hud, rect)

        assert collapsed == [True]

    def test_a_click_on_the_plus_asks_for_the_panel_back(self, qtbot):
        show = self._show(qtbot)
        collapsed: list[bool] = []
        hud = ShowHud(show, side="portrait", dashboard_cmd_file=None,
                      collapse=collapsed.append)
        show.adopt_hud(hud)
        hud.set_hud_place(HudCorner.UPPER_LEFT, True)
        (rect, _plus), = hud._targets.buttons

        _click_at(hud, rect)

        assert collapsed == [False]

    def test_a_hosted_press_on_the_minus_goes_out_on_the_sessions_channel(
            self, qtbot, tmp_path):
        show = self._show(qtbot)
        channel = tmp_path / "dashboard_cmd.txt"
        hud = ShowHud(show, side="portrait", dashboard_cmd_file=channel)
        show.adopt_hud(hud)

        hud._deliver("portrait_hud_minimize")

        assert channel.read_text(encoding="utf-8").split() == ["portrait_hud_minimize"]


def _click_at(widget, rect) -> None:
    """A left click at the middle of *rect*, in the panel's own pixels."""
    at = QPointF(rect[0] + rect[2] / 2, rect[1] + rect[3] / 2)
    for kind, buttons in ((QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
                          (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
        QApplication.sendEvent(widget, QMouseEvent(
            kind, at, at, Qt.MouseButton.LeftButton, buttons,
            Qt.KeyboardModifier.NoModifier))
def test_a_picture_still_being_generated_is_drawn_on_the_map_without_its_frame_bytes(qtbot):
    show = SlideshowView([("scene one.png", "image", "id-one")], engine=FakeEngine(),
                         shuffle=in_order)
    qtbot.addWidget(show)
    show.note_generating("id-run", b"\x89PNG frame bytes")
    show.step(1)

    corner = show_hud_model("portrait", show).corner

    assert (corner.path, corner.thumb) == ("", "")


class TestTheQueueOnTheOnePanel:
    """The lower strip's queue rides on the panel a show already wears.

    A show covers the strip, and a show is both when the line stops moving (its
    videos are held) and when the user keeps adding to it (locking a slide asks
    for an enhancement).  It used to float in the lower-left corner as a plate
    of its own, which is a second panel over the same picture.
    """

    @staticmethod
    def _show(qtbot, **actions):
        show = SlideshowView([("scene one.png", "image"), ("scene two.png", "image")],
                             engine=FakeEngine(), shuffle=in_order,
                             actions=ShowActions(**actions))
        qtbot.addWidget(show)
        return show

    def _hud(self, qtbot, show):
        hud = ShowHud(show, side="portrait", dashboard_cmd_file=None)
        qtbot.addWidget(hud)
        return hud

    def test_what_is_in_flight_is_a_block_of_the_panel(self, qtbot):
        show = self._show(qtbot)
        hud = self._hud(qtbot, show)
        show.set_queue([_inflight("j1", job_kind="Image", typical_seconds=30)], 0)

        hud._tick()

        assert [line.key for line in hud._model.foot.lines] == ["j1"]

    def test_a_panel_over_an_idle_queue_grows_no_block(self, qtbot):
        show = self._show(qtbot)
        hud = self._hud(qtbot, show)
        show.set_queue([], 0)

        hud._tick()

        assert hud._model.foot is None

    def test_a_press_on_a_row_button_throws_that_job_away(self, qtbot):
        stopped = []
        show = self._show(qtbot)
        hud = self._hud(qtbot, show)
        show.set_queue([_inflight("j1", cancel=lambda: stopped.append("j1"),
                                  typical_seconds=30)], 0)
        hud._tick()

        _press_and_release(hud, f"{CANCEL}|j1")

        assert stopped == ["j1"]

    def test_a_press_on_a_row_goes_to_the_folder_its_job_will_land_in(self, qtbot):
        opened = []
        show = self._show(qtbot)
        hud = self._hud(qtbot, show)
        show.set_queue([_inflight("j1", reveal=lambda: opened.append("j1"),
                                  typical_seconds=30)], 0)
        hud._tick()

        _press_and_release(hud, f"{OPEN}|j1")

        assert opened == ["j1"]

    def test_clear_drops_another_apps_work(self, qtbot):
        cleared = []
        show = self._show(qtbot, clear_queue=lambda: cleared.append(True))
        hud = self._hud(qtbot, show)
        show.set_queue([], 3)
        hud._tick()

        _press_and_release(hud, CLEAR)

        assert cleared == [True]

    def test_a_row_dragged_down_the_line_re_lines_the_queue(self, qtbot):
        asked = []
        show = self._show(qtbot, requeue=asked.append)
        hud = self._hud(qtbot, show)
        show.set_queue([_inflight("j1", status="running", typical_seconds=30),
                        _inflight("j2", typical_seconds=30),
                        _inflight("j3", typical_seconds=30)], 0)
        hud._tick()

        _press_and_release(hud, f"{OPEN}|j2", travel=(0, _below(hud, f"{OPEN}|j3")))

        assert asked == [["j1", "j3", "j2"]]

    def test_a_row_that_was_dragged_does_not_also_open_its_folder(self, qtbot):
        opened = []
        show = self._show(qtbot, requeue=lambda keys: None)
        hud = self._hud(qtbot, show)
        show.set_queue([_inflight("j1", typical_seconds=30),
                        _inflight("j2", reveal=lambda: opened.append("j2"),
                                  typical_seconds=30)], 0)
        hud._tick()

        _press_and_release(hud, f"{OPEN}|j2", travel=(0, -20))

        assert opened == []

    def test_the_job_being_made_cannot_be_picked_up(self, qtbot):
        """Nothing can be moved in front of what ComfyUI is already rendering,
        itself included."""
        asked = []
        show = self._show(qtbot, requeue=asked.append)
        hud = self._hud(qtbot, show)
        show.set_queue([_inflight("j1", status="running", typical_seconds=30),
                        _inflight("j2", typical_seconds=30)], 0)
        hud._tick()

        _press_and_release(hud, f"{OPEN}|j1", travel=(0, 40))

        assert asked == []

    def test_the_wheel_scrolls_a_line_longer_than_the_rows_drawn(self, qtbot):
        show = self._show(qtbot)
        hud = self._hud(qtbot, show)
        show.set_queue([_inflight(f"j{index}", typical_seconds=30)
                        for index in range(7)], 0)
        hud._tick()
        assert [line.key for line in hud._model.foot.drawn][0] == "j0"

        _wheel(hud, f"{OPEN}|j2", -120)

        assert [line.key for line in hud._model.foot.drawn][0] == "j1"
