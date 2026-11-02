"""Osr2Controls — the Funestras' console's OSR2 section, shown here, and what a press on it does.

The console painter is funestra's and tested there. What this covers is the two
things that are this app's: that the drawing really is that console painter's (not a
lookalike), and that each command it posts reaches the right thing here.
"""
from __future__ import annotations

import itertools
import random

import pytest
from app_support.osr2_device import Osr2Mode, Osr2Trouble
from funestra import drive_layout
from funestra.console import (
    BROKER_PRESS,
    OSR2_CONTROL_BUTTONS,
    OSR2_CONTROL_UNANSWERED,
    OSR2_DRIVING,
    OSR2_PARKED,
)
from funestra.console_hud import ConsolePainter, hud_xy
from funestra.drive_readout import DRIVEN_BY_NOTHING, DRIVEN_BY_ROBOT_HAND
from funestra.learned_model import LearnedModel, Phrase, classify
from funestra.modes import Osr2State
from funestra.robot_hand import POSITION_MAX
from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from origenerator import motion_engine
from origenerator.gui.osr2_controls import Osr2Controls
from origenerator.gui.osr2_controls_state import drive_hud, osr2_controls_hud, osr2_controls_room
from tests.motion_doubles import FakeMotion


def _controls(qtbot, motion=None, control=None):
    motion = motion if motion is not None else FakeMotion()
    controls = Osr2Controls(motion, control=control)
    qtbot.addWidget(controls)
    return controls, motion


def _press(controls, action):
    """Press whatever button posts *action*, at its own middle."""
    x, y, w, h = next(r for r, b in controls._painter.buttons if b.command == action)
    QTest.mousePress(controls, Qt.MouseButton.LeftButton, pos=QPoint(x + w // 2, y + h // 2))


def _slide(controls, along: float) -> None:
    max_intensity = next(t for t in controls._painter.tracks if t.axis == drive_layout.MAX_INTENSITY)
    x, y, w, h = max_intensity.rect
    QTest.mousePress(controls, Qt.MouseButton.LeftButton, pos=QPoint(x + round(along * (w - 1)), y + h // 2))


def test_the_osr2_controls_carry_no_filter_switches_of_their_own(qtbot):
    # Over a slideshow the two switches saying what it may play are on the Funestras'
    # HUD this controls sits under, and a second pair here would be two switches
    # for one thing — so the OSR2 controls offer neither, the way Genau's own do.
    controls, _motion = _controls(qtbot)
    controls.drawing()
    for action in ("main_fmode", "genau_filter_enhanced"):
        assert action not in [b.command for _r, b in controls._painter.buttons]


def test_the_osr2_controls_are_up_while_nothing_drives_since_their_switch_is_what_starts_driving(qtbot):
    controls, motion = _controls(qtbot)
    controls.show()

    assert motion.active is False
    assert controls.isVisible()
    assert not controls._repaint.isActive()   # nothing is moving, so nothing repaints

    motion.active = True
    controls.refresh()

    assert controls.isVisible()
    assert controls._repaint.isActive()       # the trace scrolls, so now it does


def test_the_drawing_is_the_one_funestras_console_painter_paints(qtbot):
    # Not a repaint of the design, and not a third of it: the same painter, the
    # same rows, the same bitmap.
    controls, motion = _controls(qtbot)
    raw, size = controls.drawing()
    expected, expected_size = ConsolePainter(device_only=True).rgba(osr2_controls_hud(motion))
    assert (raw, size) == (expected, expected_size)


def test_cores_osr2_controls_are_the_consoles_osr2_section_alone(qtbot):
    controls, _motion = _controls(qtbot)
    controls.drawing()
    actions = [b.command for _rect, b in controls._painter.buttons]

    assert not any(a.endswith("_minimize") for a in actions)
    for gone in ("genau_prev_clip", "genau_next_clip", "main_lock", "genau_weird_clip",
                 "portrait_clip_seconds_down", "portrait_clip_seconds_up",
                 "landscape_clip_seconds_down", "landscape_clip_seconds_up"):
        assert gone not in actions, gone
    for kept in ("robot_hand_toggle_learned",
                 "robot_hand_cycle_shape", "robot_hand_release",
                 "robot_hand_speed_up", "robot_hand_amplitude_up", "robot_hand_center_up"):
        assert kept in actions, kept


def test_the_osr2_controls_declare_the_buttons_this_app_answers(qtbot):
    _panel_, motion = _controls(qtbot)

    hud = osr2_controls_hud(motion, control=OSR2_DRIVING)

    assert hud.console.rows == ()
    assert [[b.command for b in row if b.command] for row in hud.console.osr2_rows] == [
        ["robot_hand_park", "robot_hand_toggle_learned", "robot_hand_cycle_shape"],
    ]
    assert [b.command for b in hud.console.osr2_controls] == [BROKER_PRESS]


@pytest.mark.parametrize("running", [True, False])
def test_the_broker_button_is_lit_while_the_broker_runs_and_red_while_it_does_not(
        qtbot, monkeypatch, running):
    monkeypatch.setattr("origenerator.osr2.broker_running", lambda: running)
    controls, _motion = _controls(qtbot)

    controls.drawing()

    (broker,) = [b for _rect, b in controls._painter.buttons if b.command == BROKER_PRESS]
    assert (broker.lit, broker.warn) == (running, not running)


def test_a_press_on_the_broker_button_presses_the_broker(qtbot, monkeypatch):
    presses = []
    monkeypatch.setattr("origenerator.osr2.press_the_broker", lambda: presses.append(True))
    controls, _motion = _controls(qtbot)
    controls.drawing()

    _press(controls, BROKER_PRESS)

    assert presses == [True]


def test_a_room_paused_while_the_motion_has_the_device_sends_the_dot_home(qtbot):
    _panel_, motion = _controls(qtbot)
    motion.parked_by_the_pause = True

    assert osr2_controls_hud(motion, control=OSR2_DRIVING).console.paused


def test_the_readouts_speed_amp_and_center_buttons_take_presses_while_the_room_is_paused(qtbot):
    motion = FakeMotion()
    motion.active = True
    motion.state.state.amplitude = 60
    motion.parked_by_the_pause = True
    painter = ConsolePainter()
    painter.rgba(osr2_controls_hud(motion, control=OSR2_DRIVING))
    left, top = hud_xy()

    taken = [button.command for (x, y, w, h), button in painter.buttons
             if button.command.startswith(("robot_hand_speed", "robot_hand_amplitude", "robot_hand_center"))
             and painter.press_at(left + x + w // 2, top + y + h // 2) == button.command]

    assert len(taken) == 6


def test_every_button_the_osr2_controls_declare_does_something_here(qtbot, monkeypatch):
    broker_presses = []
    monkeypatch.setattr("origenerator.osr2.press_the_broker", lambda: broker_presses.append(True))
    control = FakeControl()
    controls, motion = _controls(qtbot, control=control)
    motion.active = True
    controls.drawing()
    console = osr2_controls_hud(motion, control=control.state()).console
    declared = [b.command for row in (*console.rows, *console.osr2_rows, console.osr2_controls)
                for b in row if b.command]

    for command in declared:
        before = len(motion.calls) + len(control.asked) + len(broker_presses)
        _press(controls, command)
        assert len(motion.calls) + len(control.asked) + len(broker_presses) > before, command


def test_the_motion_buttons_reach_the_driver(qtbot):
    controls, motion = _controls(qtbot)
    motion.active = True  # a parked device's marks are dimmed, and dim is unpressable
    # A full-travel motion has its center pinned, and a pinned mark is dim too.
    motion.state.state.amplitude = 40
    controls.drawing()
    for action in ("robot_hand_speed_up", "robot_hand_amplitude_down", "robot_hand_center_up",
                   "robot_hand_toggle_learned", "robot_hand_cycle_shape"):
        _press(controls, action)
    assert motion.calls == [("speed", 5), ("amp", -10), ("center", 5),
                            "learned", "shape"]


def test_each_press_on_the_waveform_button_changes_the_face_it_wears(qtbot):
    controls, _motion = _controls(qtbot)
    faces = []
    for _waveform in motion_engine.WaveformShape:
        controls.drawing()
        faces.append(next(b.glyph for _r, b in controls._painter.buttons
                          if b.command == "robot_hand_cycle_shape"))
        _press(controls, "robot_hand_cycle_shape")

    assert len(set(faces)) == len(motion_engine.WaveformShape)


class FakeControl(QObject):
    """The app's OSR2 switch reduced to what the OSR2 controls' group asks of one."""

    changed = pyqtSignal()
    settled = pyqtSignal()

    def __init__(self, state=OSR2_DRIVING, script=None):
        super().__init__()
        self._state = state
        self.script = script
        self.asked = []
        self.max_intensities = []

    def source(self):
        if self.script is not None and self.script.active:
            return "funscript"
        return "robot_hand"

    def state(self):
        return self._state

    def set_state(self, state):
        self._state = state
        self.asked.append(state)

    def set_max_intensity(self, level):
        self.max_intensities.append(level)


def test_the_osr2_line_carries_the_max_intensity_the_motion_is_held_to(qtbot):
    motion = FakeMotion()
    motion.set_max_intensity(35)

    assert osr2_controls_hud(motion).console.max_intensity == 35


def test_the_readout_carries_the_max_intensity_the_motion_is_held_to(qtbot):
    motion = FakeMotion()
    motion.set_max_intensity(40)

    assert drive_hud(motion.state, True).max_intensity == 40


def test_the_readout_under_a_funscript_carries_the_max_intensity_too(qtbot):
    script = FakeScript()
    control = FakeControl(script=script)
    controls, motion = _controls(qtbot, control=control)
    motion.set_max_intensity(40)

    drive = osr2_controls_hud(motion, control=control.state(), script=script).drive

    assert (drive.driven, drive.max_intensity) == ("funscript", 40)


def test_the_speed_plus_dims_where_the_max_intensity_stops_the_speed(qtbot):
    controls, motion = _controls(qtbot)
    motion.active = True
    motion.set_max_intensity(40)
    motion_engine.set_speed(motion.state.state, motion_engine.MAX_SPEED)
    controls.drawing()

    plus, minus = (next(b for _r, b in controls._painter.buttons if b.command == command)
                   for command in ("robot_hand_speed_up", "robot_hand_speed_down"))
    assert plus.dim
    assert not minus.dim


def test_the_max_intensity_slider_asks_the_apps_one_switch_for_the_level(qtbot):
    control = FakeControl()
    controls, motion = _controls(qtbot, control=control)
    controls.drawing()

    _slide(controls, 1.0)

    assert control.max_intensities == [100]
    assert motion.calls == []


def test_a_panel_with_no_switch_hands_the_max_intensity_to_the_motion(qtbot):
    controls, motion = _controls(qtbot)
    controls.drawing()

    _slide(controls, 0.0)

    assert motion.calls == [("max_intensity", 0)]


def test_the_osr2_controls_switch_is_the_apps_one_switch(qtbot):
    """A press while driving parks, and a press while parked drives -- which is
    what the separate Gallery pane button was replaced by."""
    control = FakeControl()
    controls, _motion = _controls(qtbot, control=control)

    controls.drawing()
    _press(controls, OSR2_CONTROL_BUTTONS[OSR2_PARKED])
    controls.drawing()
    _press(controls, OSR2_CONTROL_BUTTONS[OSR2_DRIVING])

    assert control.asked == [OSR2_PARKED, OSR2_DRIVING]


def test_the_group_lights_the_state_the_switch_is_in(qtbot):
    """The OSR2 controls draw the lit button; what this app owes them is the answer to
    which state, which nothing on the controls itself knows."""
    control = FakeControl(OSR2_PARKED)
    controls, motion = _controls(qtbot, control=control)

    hud = osr2_controls_hud(motion, control=control.state())

    assert hud.console.osr2_control == OSR2_PARKED
    assert controls.drawing()[0]  # and it paints in that state


def test_a_panel_with_no_switch_still_holds_the_motion(qtbot):
    """OSR2 controls outside a gallery -- a test's, and any future host that hands
    over no switch -- can still release what it does have."""
    controls, motion = _controls(qtbot)
    controls.drawing()

    _press(controls, OSR2_CONTROL_BUTTONS[OSR2_DRIVING])

    assert motion.calls == ["release"]


class FakeScript:
    """The funscript driver reduced to what the OSR2 controls ask of one: whether it
    has the device, and the line it is about to send."""

    parked_by_the_pause = False

    def __init__(self, active=True, heights=None):
        self.active = active
        self._heights = heights or tuple(i / 79 for i in range(80))

    def trace(self, count, seconds):
        return self._heights[:count]


def test_a_script_with_the_device_draws_its_own_line_in_green(qtbot):
    """The whole of what the OSR2 controls said before: nothing.  The motion is
    stopped while a script drives, so OSR2 controls drawn from the motion showed a
    dead readout over a device that was working."""
    script = FakeScript()
    control = FakeControl(script=script)
    controls, motion = _controls(qtbot, control=control)

    hud = osr2_controls_hud(motion, control=control.state(), script=script)

    assert hud.drive.driven == "funscript"
    assert hud.drive.waveform == script.trace(80, 12.0)
    assert hud.console.osr2 is Osr2State.FUNSCRIPT


def test_the_dot_sits_where_the_script_has_the_device_now(qtbot):
    script = FakeScript(heights=tuple([0.25] * 80))
    control = FakeControl(script=script)
    controls, motion = _controls(qtbot, control=control)

    hud = osr2_controls_hud(motion, control=control.state(), script=script)

    assert hud.drive.position == round(0.25 * POSITION_MAX)


def test_the_motion_is_drawn_again_once_the_script_is_done(qtbot):
    script = FakeScript(active=False)
    control = FakeControl(script=script)
    controls, motion = _controls(qtbot, control=control)
    motion.active = True

    hud = osr2_controls_hud(motion, control=control.state(), script=script)

    assert hud.drive.driven == "robot_hand"
    assert hud.console.osr2 is Osr2State.ROBOT_HAND


def test_with_their_switch_off_the_osr2_controls_say_parked_over_a_device_that_is_on(qtbot):
    painter = ConsolePainter()
    hud = osr2_controls_hud(FakeMotion(), device=Osr2Mode.CONTROLLED, control=OSR2_PARKED)
    painter.rgba(hud)

    assert painter._osr2_state(hud.console) == OSR2_PARKED


def test_a_device_that_is_not_answering_is_driven_by_nobody(qtbot):
    """The script streams into the air with the OSR2 switched off, and a green
    line would say it was arriving."""
    script = FakeScript()
    control = FakeControl(script=script)
    controls, motion = _controls(qtbot, control=control)

    hud = osr2_controls_hud(motion, device=Osr2Mode.OFF, control=control.state(),
                      script=script)

    assert hud.console.osr2 is Osr2State.OFF


def test_a_parked_device_offers_none_of_the_motions_marks(qtbot):
    # A press that could do nothing is not offered — the readout is dimmed whole
    # while nothing is reaching the device, exactly as it is in Fun Time while a
    # funscript has it.
    controls, _motion = _controls(qtbot, control=FakeControl(state=OSR2_PARKED))
    controls.drawing()
    marks = [b for _r, b in controls._painter.buttons
             if b.command.startswith(("robot_hand_speed", "robot_hand_amplitude", "robot_hand_center"))]
    assert marks
    assert all(b.dim for b in marks)


def test_dragging_a_band_sets_the_level_under_the_pointer(qtbot):
    controls, motion = _controls(qtbot)
    motion.active = True
    controls.drawing()
    speed = next(t for t in controls._painter.tracks if t.axis == "speed")
    x, y, w, _h = speed.rect
    QTest.mousePress(controls, Qt.MouseButton.LeftButton, pos=QPoint(x + w - 1, y))
    assert motion.calls == [("set_speed", 100)]


def test_the_readout_is_the_motion_only_while_it_runs(qtbot):
    motion = FakeMotion()
    assert drive_hud(motion.state, False).driven == DRIVEN_BY_NOTHING
    assert drive_hud(motion.state, True).driven == DRIVEN_BY_ROBOT_HAND


def test_off_is_said_only_of_a_device_that_is_switched_off(qtbot):
    motion = FakeMotion()
    for running in (False, True):
        motion.active = running
        assert osr2_controls_hud(motion).console.osr2 is Osr2State.ROBOT_HAND, running


def test_a_motion_with_the_osr2_switched_off_says_off_and_drives_nothing(qtbot):
    # The motion goes on with the device unplugged — it cannot see the
    # wire — so without this the OSR2 controls animated a blue wave nobody was riding.
    # Saying "off" is also what grays the readout and holds its trace still: the
    # painter reads who has the device off this one value (funestra).

    motion = FakeMotion()
    motion.active = True

    hud = osr2_controls_hud(motion, device=Osr2Mode.OFF)

    assert hud.console.osr2 is Osr2State.OFF
    assert hud.drive.driven == DRIVEN_BY_NOTHING
    assert not hud.drive.live


@pytest.mark.parametrize(("trouble", "said"), [(Osr2Trouble.NOT_FOUND, Osr2State.UNPLUGGED),
                                               (Osr2Trouble.NOT_ANSWERING, Osr2State.NO_ANSWER)])
def test_an_osr2_the_broker_cannot_hear_says_why_and_drives_nothing(qtbot, trouble, said):
    motion = FakeMotion()
    motion.active = True

    hud = osr2_controls_hud(motion, device=Osr2Mode.OFF, trouble=trouble)

    assert hud.console.osr2 is said
    assert hud.drive.driven == DRIVEN_BY_NOTHING
    assert not hud.drive.live


def test_the_panel_redraws_once_the_device_switches_under_what_it_drew(qtbot):
    device = {"on": False}
    controls = Osr2Controls(FakeMotion(),
                        device=lambda: Osr2Mode.CONTROLLED if device["on"] else Osr2Mode.OFF,
                        control=FakeControl(state=OSR2_PARKED))
    qtbot.addWidget(controls)
    controls.drawing()

    assert controls._redraw_if_the_device_switched() is False
    device["on"] = True
    assert controls._redraw_if_the_device_switched() is True


def test_the_panel_redraws_once_the_broker_starts_or_stops(qtbot, monkeypatch):
    running = {"now": True}
    monkeypatch.setattr("origenerator.osr2.broker_running", lambda: running["now"])
    controls, _motion = _controls(qtbot, control=FakeControl(state=OSR2_PARKED))
    controls.drawing()

    assert controls._redraw_if_the_device_switched() is False
    running["now"] = False
    assert controls._redraw_if_the_device_switched() is True


def test_the_panel_redraws_once_the_broker_says_why_it_cannot_hear_the_osr2(qtbot):
    trouble = {"now": None}
    controls = Osr2Controls(FakeMotion(), device=lambda: Osr2Mode.OFF,
                        trouble=lambda: trouble["now"], control=FakeControl(state=OSR2_PARKED))
    qtbot.addWidget(controls)
    controls.drawing()

    assert controls._redraw_if_the_device_switched() is False
    trouble["now"] = Osr2Trouble.NOT_FOUND
    assert controls._redraw_if_the_device_switched() is True


def test_the_panel_watches_the_device_for_as_long_as_it_is_shown(qtbot):
    controls, _motion = _controls(qtbot, control=FakeControl(state=OSR2_PARKED))

    controls.show()
    assert controls._device_watch.isActive()
    controls.hide()
    assert not controls._device_watch.isActive()


def test_the_panel_asks_whether_the_device_is_answering_on_every_draw(qtbot):
    # Asked per draw rather than once: the OSR2 is switched on and off without
    # this app's back, so OSR2 controls that read it at build time would go on
    # claiming whatever was true when it opened.
    answers = [Osr2Mode.OFF, Osr2Mode.CONTROLLED]
    motion = FakeMotion()
    motion.active = True
    controls = Osr2Controls(motion, device=lambda: answers.pop(0))
    qtbot.addWidget(controls)

    controls.drawing()
    assert answers == [Osr2Mode.CONTROLLED]  # it asked
    controls.drawing()
    assert answers == []      # and asked again rather than reusing the answer


def _first_named_button(controls) -> tuple[int, int, int, int]:
    controls.grab()  # lays the buttons out
    return next(rect for rect, button in controls._painter.buttons if button.tooltip)


def _ground_lightness(controls, rect) -> int:
    x, y, _w, h = rect
    return controls.grab().toImage().pixelColor(x + 2, y + h // 2).lightness()


def _move_onto(controls, rect) -> None:
    x, y, w, h = rect
    at = QPointF(x + w // 2, y + h // 2)
    QApplication.sendEvent(controls, QMouseEvent(
        QEvent.Type.MouseMove, at, QPointF(controls.mapToGlobal(at.toPoint())),
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))


def test_the_panel_hears_the_pointer_move_with_no_button_held(qtbot):
    # Qt hands a widget a plain move only when it asks for every move; without
    # that, the controls heard the pointer only while a button was held.
    controls, _motion = _controls(qtbot)

    assert controls.hasMouseTracking()


def test_the_button_under_the_pointer_lights_up(qtbot):
    # The controls over a Slideshow lit the button under the pointer and this one
    # did not, though the same painter draws both: nothing told it where the
    # pointer was.
    controls, _motion = _controls(qtbot)
    button = _first_named_button(controls)
    at_rest = _ground_lightness(controls, button)

    _move_onto(controls, button)

    assert _ground_lightness(controls, button) > at_rest


def test_the_button_goes_back_once_the_pointer_leaves(qtbot):
    controls, _motion = _controls(qtbot)
    button = _first_named_button(controls)
    at_rest = _ground_lightness(controls, button)
    _move_onto(controls, button)

    QApplication.sendEvent(controls, QEvent(QEvent.Type.Leave))

    assert _ground_lightness(controls, button) == at_rest


def test_no_tooltip_of_the_panels_own_comes_up_over_a_buttons_name(qtbot):
    controls, _motion = _controls(qtbot)

    assert controls.toolTip() == ""


def test_the_panel_actually_paints(qtbot):
    # A NameError in paintEvent takes the whole app down the first time the
    # controls is shown — which is what shipped once.
    controls, motion = _controls(qtbot)

    assert not controls.grab().isNull()

    motion.active = True
    motion.state.learned.active = True

    assert not controls.grab().isNull()  # and again with every reading lit


def test_the_osr2_controls_keep_the_room_they_take_at_their_widest(qtbot):
    controls, motion = _controls(qtbot)
    controls.show()
    controls.grab()  # a paint of the OSR2 controls as they stand, narrower than at their widest

    assert (controls.width(), controls.height()) == osr2_controls_room(motion)


def test_no_state_draws_the_osr2_controls_outside_the_room_kept_for_them():
    motion = FakeMotion()
    room_width, room_height = osr2_controls_room(motion)

    for control, active, device, script in itertools.product(
            (*OSR2_CONTROL_BUTTONS, OSR2_CONTROL_UNANSWERED), (False, True), Osr2Mode,
            (None, FakeScript())):
        motion.active = active
        _raw, (width, height) = ConsolePainter(device_only=True).rgba(
            osr2_controls_hud(motion, device=device, control=control, script=script))

        fit = (control, active, device)
        assert width <= room_width, fit
        assert height <= room_height, fit


def test_the_readout_holds_the_waves_drawing_still_between_knots(qtbot):
    motion = FakeMotion()
    live = motion.state
    live.state.playing = True
    motion_engine.advance(live, 0.05)
    before = drive_hud(live, active=True)

    motion_engine.advance(live, 0.05)
    after = drive_hud(live, active=True)

    assert after.waveform == before.waveform
    assert after.slide > before.slide


def test_the_readout_holds_the_learned_motions_drawing_still_between_knots(qtbot):
    # The learned motion is read on knots: a tick later the same heights are
    # drawn, shifted left by the fraction of a knot the clock has moved.


    phrase = Phrase(tuple((500, 80 if i % 2 == 0 else 20) for i in range(16)))
    motion = FakeMotion()
    live = motion.state
    live.state.playing = True
    live.learned.model = LearnedModel(phrases={classify(phrase): [phrase]},
                                      seen={classify(phrase): 1})
    live.learned.rng = random.Random(1)
    motion_engine.enable_learned_motion(live)
    motion_engine.tick_learned_motion(live, 1000.0)
    before = drive_hud(live, active=True)
    motion_engine.tick_learned_motion(live, 1000.02)

    after = drive_hud(live, active=True)

    assert after.waveform == before.waveform
    assert after.slide > before.slide
    assert after.edge == before.edge


def test_with_the_osr2_running_its_own_auto_mode_the_line_says_auto(qtbot):
    motion = FakeMotion()
    motion.active = True

    assert osr2_controls_hud(motion, device=Osr2Mode.AUTO).console.osr2 is Osr2State.AUTO


def test_the_panel_redraws_once_the_osr2_goes_into_its_own_auto_mode(qtbot):
    device = {"mode": Osr2Mode.CONTROLLED}
    controls = Osr2Controls(FakeMotion(), device=lambda: device["mode"],
                        control=FakeControl(state=OSR2_DRIVING))
    qtbot.addWidget(controls)
    controls.drawing()

    device["mode"] = Osr2Mode.AUTO

    assert controls._redraw_if_the_device_switched() is True
