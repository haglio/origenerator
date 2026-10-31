"""MotionPanel — Genau's console, shown here, and what a press on it does.

The console is funestra's and tested there. What this covers is the two
things that are this app's: that the drawing really is that console (not a
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
from origenerator.gui.console import console_hud, drive_hud, panel_room
from origenerator.gui.motion_panel import MotionPanel
from tests.motion_doubles import FakeMotion


def _panel(qtbot, motion=None, control=None):
    motion = motion if motion is not None else FakeMotion()
    panel = MotionPanel(motion, control=control)
    qtbot.addWidget(panel)
    return panel, motion


def _press(panel, action):
    """Press whatever button posts *action*, at its own middle."""
    x, y, w, h = next(r for r, b in panel._painter.buttons if b.command == action)
    QTest.mousePress(panel, Qt.MouseButton.LeftButton, pos=QPoint(x + w // 2, y + h // 2))


def _slide(panel, along: float) -> None:
    max_intensity = next(t for t in panel._painter.tracks if t.axis == drive_layout.MAX_INTENSITY)
    x, y, w, h = max_intensity.rect
    QTest.mousePress(panel, Qt.MouseButton.LeftButton, pos=QPoint(x + round(along * (w - 1)), y + h // 2))


def test_the_console_carries_no_filter_switches_of_its_own(qtbot):
    # Over a slideshow the two switches saying what it may play are on the Funestras'
    # HUD this panel sits under, and a second pair here would be two switches
    # for one thing — so the console offers neither, the way Genau's own does.
    panel, _motion = _panel(qtbot)
    panel.drawing()
    for action in ("main_fmode", "genau_filter_enhanced"):
        assert action not in [b.command for _r, b in panel._painter.buttons]


def test_the_console_is_up_while_nothing_drives_since_its_switch_is_what_starts_driving(qtbot):
    panel, motion = _panel(qtbot)
    panel.show()

    assert motion.active is False
    assert panel.isVisible()
    assert not panel._repaint.isActive()   # nothing is moving, so nothing repaints

    motion.active = True
    panel.refresh()

    assert panel.isVisible()
    assert panel._repaint.isActive()       # the trace scrolls, so now it does


def test_the_drawing_is_the_console_funestra_paints(qtbot):
    # Not a repaint of the design, and not a third of it: the same painter, the
    # same rows, the same bitmap.
    panel, motion = _panel(qtbot)
    raw, size = panel.drawing()
    expected, expected_size = ConsolePainter(device_only=True).rgba(console_hud(motion))
    assert (raw, size) == (expected, expected_size)


def test_cores_console_is_its_osr2_section_alone(qtbot):
    panel, _motion = _panel(qtbot)
    panel.drawing()
    actions = [b.command for _rect, b in panel._painter.buttons]

    assert not any(a.endswith("_minimize") for a in actions)
    for gone in ("genau_prev_clip", "genau_next_clip", "main_lock", "genau_weird_clip",
                 "portrait_clip_seconds_down", "portrait_clip_seconds_up",
                 "landscape_clip_seconds_down", "landscape_clip_seconds_up"):
        assert gone not in actions, gone
    for kept in ("robot_hand_toggle_learned",
                 "robot_hand_cycle_shape", "robot_hand_release",
                 "robot_hand_speed_up", "robot_hand_amplitude_up", "robot_hand_center_up"):
        assert kept in actions, kept


def test_the_console_declares_the_buttons_this_app_answers(qtbot):
    _panel_, motion = _panel(qtbot)

    hud = console_hud(motion, control=OSR2_DRIVING)

    assert hud.console.rows == ()
    assert [[b.command for b in row if b.command] for row in hud.console.osr2_rows] == [
        ["robot_hand_park", "robot_hand_toggle_learned", "robot_hand_cycle_shape"],
    ]
    assert [b.command for b in hud.console.osr2_controls] == [BROKER_PRESS]


@pytest.mark.parametrize("running", [True, False])
def test_the_broker_button_is_lit_while_the_broker_runs_and_red_while_it_does_not(
        qtbot, monkeypatch, running):
    monkeypatch.setattr("origenerator.osr2.broker_running", lambda: running)
    panel, _motion = _panel(qtbot)

    panel.drawing()

    (broker,) = [b for _rect, b in panel._painter.buttons if b.command == BROKER_PRESS]
    assert (broker.lit, broker.warn) == (running, not running)


def test_a_press_on_the_broker_button_presses_the_broker(qtbot, monkeypatch):
    presses = []
    monkeypatch.setattr("origenerator.osr2.press_the_broker", lambda: presses.append(True))
    panel, _motion = _panel(qtbot)
    panel.drawing()

    _press(panel, BROKER_PRESS)

    assert presses == [True]


def test_a_room_paused_while_the_motion_has_the_device_sends_the_dot_home(qtbot):
    _panel_, motion = _panel(qtbot)
    motion.parked_by_the_pause = True

    assert console_hud(motion, control=OSR2_DRIVING).console.paused


def test_the_readouts_speed_amp_and_center_buttons_take_presses_while_the_room_is_paused(qtbot):
    motion = FakeMotion()
    motion.active = True
    motion.state.state.amplitude = 60
    motion.parked_by_the_pause = True
    painter = ConsolePainter()
    painter.rgba(console_hud(motion, control=OSR2_DRIVING))
    left, top = hud_xy()

    taken = [button.command for (x, y, w, h), button in painter.buttons
             if button.command.startswith(("robot_hand_speed", "robot_hand_amplitude", "robot_hand_center"))
             and painter.press_at(left + x + w // 2, top + y + h // 2) == button.command]

    assert len(taken) == 6


def test_every_button_the_console_declares_does_something_here(qtbot, monkeypatch):
    broker_presses = []
    monkeypatch.setattr("origenerator.osr2.press_the_broker", lambda: broker_presses.append(True))
    control = FakeControl()
    panel, motion = _panel(qtbot, control=control)
    motion.active = True
    panel.drawing()
    console = console_hud(motion, control=control.state()).console
    declared = [b.command for row in (*console.rows, *console.osr2_rows, console.osr2_controls)
                for b in row if b.command]

    for command in declared:
        before = len(motion.calls) + len(control.asked) + len(broker_presses)
        _press(panel, command)
        assert len(motion.calls) + len(control.asked) + len(broker_presses) > before, command


def test_the_motion_buttons_reach_the_driver(qtbot):
    panel, motion = _panel(qtbot)
    motion.active = True  # a parked device's marks are dimmed, and dim is unpressable
    # A full-travel motion has its center pinned, and a pinned mark is dim too.
    motion.state.state.amplitude = 40
    panel.drawing()
    for action in ("robot_hand_speed_up", "robot_hand_amplitude_down", "robot_hand_center_up",
                   "robot_hand_toggle_learned", "robot_hand_cycle_shape"):
        _press(panel, action)
    assert motion.calls == [("speed", 5), ("amp", -10), ("center", 5),
                            "learned", "shape"]


def test_each_press_on_the_waveform_button_changes_the_face_it_wears(qtbot):
    panel, _motion = _panel(qtbot)
    faces = []
    for _waveform in motion_engine.WaveformShape:
        panel.drawing()
        faces.append(next(b.glyph for _r, b in panel._painter.buttons
                          if b.command == "robot_hand_cycle_shape"))
        _press(panel, "robot_hand_cycle_shape")

    assert len(set(faces)) == len(motion_engine.WaveformShape)


class FakeControl(QObject):
    """The app's OSR2 switch reduced to what the console's group asks of one."""

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

    assert console_hud(motion).console.max_intensity == 35


def test_the_readout_carries_the_max_intensity_the_motion_is_held_to(qtbot):
    motion = FakeMotion()
    motion.set_max_intensity(40)

    assert drive_hud(motion.state, True).max_intensity == 40


def test_the_readout_under_a_funscript_carries_the_max_intensity_too(qtbot):
    script = FakeScript()
    control = FakeControl(script=script)
    panel, motion = _panel(qtbot, control=control)
    motion.set_max_intensity(40)

    drive = console_hud(motion, control=control.state(), script=script).drive

    assert (drive.driven, drive.max_intensity) == ("funscript", 40)


def test_the_speed_plus_dims_where_the_max_intensity_stops_the_speed(qtbot):
    panel, motion = _panel(qtbot)
    motion.active = True
    motion.set_max_intensity(40)
    motion_engine.set_speed(motion.state.state, motion_engine.MAX_SPEED)
    panel.drawing()

    plus, minus = (next(b for _r, b in panel._painter.buttons if b.command == command)
                   for command in ("robot_hand_speed_up", "robot_hand_speed_down"))
    assert plus.dim
    assert not minus.dim


def test_the_max_intensity_slider_asks_the_apps_one_switch_for_the_level(qtbot):
    control = FakeControl()
    panel, motion = _panel(qtbot, control=control)
    panel.drawing()

    _slide(panel, 1.0)

    assert control.max_intensities == [100]
    assert motion.calls == []


def test_a_panel_with_no_switch_hands_the_max_intensity_to_the_motion(qtbot):
    panel, motion = _panel(qtbot)
    panel.drawing()

    _slide(panel, 0.0)

    assert motion.calls == [("max_intensity", 0)]


def test_the_console_switch_is_the_apps_one_switch(qtbot):
    """A press while driving parks, and a press while parked drives -- which is
    what the separate toolbar one was replaced by."""
    control = FakeControl()
    panel, _motion = _panel(qtbot, control=control)

    panel.drawing()
    _press(panel, OSR2_CONTROL_BUTTONS[OSR2_PARKED])
    panel.drawing()
    _press(panel, OSR2_CONTROL_BUTTONS[OSR2_DRIVING])

    assert control.asked == [OSR2_PARKED, OSR2_DRIVING]


def test_the_group_lights_the_state_the_switch_is_in(qtbot):
    """The console draws the lit button; what this app owes it is the answer to
    which state, which nothing on the panel itself knows."""
    control = FakeControl(OSR2_PARKED)
    panel, motion = _panel(qtbot, control=control)

    hud = console_hud(motion, control=control.state())

    assert hud.console.osr2_control == OSR2_PARKED
    assert panel.drawing()[0]  # and it paints in that state


def test_a_panel_with_no_switch_still_holds_the_motion(qtbot):
    """A console outside a gallery -- a test's, and any future host that hands
    over no switch -- can still release what it does have."""
    panel, motion = _panel(qtbot)
    panel.drawing()

    _press(panel, OSR2_CONTROL_BUTTONS[OSR2_DRIVING])

    assert motion.calls == ["release"]


class FakeScript:
    """The funscript driver reduced to what the console asks of one: whether it
    has the device, and the line it is about to send."""

    parked_by_the_pause = False

    def __init__(self, active=True, heights=None):
        self.active = active
        self._heights = heights or tuple(i / 79 for i in range(80))

    def trace(self, count, seconds):
        return self._heights[:count]


def test_a_script_with_the_device_draws_its_own_line_in_green(qtbot):
    """The whole of what the console said before: nothing.  The motion is
    stopped while a script drives, so a console drawn from the motion showed a
    dead readout over a device that was working."""
    script = FakeScript()
    control = FakeControl(script=script)
    panel, motion = _panel(qtbot, control=control)

    hud = console_hud(motion, control=control.state(), script=script)

    assert hud.drive.driven == "funscript"
    assert hud.drive.waveform == script.trace(80, 12.0)
    assert hud.console.osr2 is Osr2State.FUNSCRIPT


def test_the_dot_sits_where_the_script_has_the_device_now(qtbot):
    script = FakeScript(heights=tuple([0.25] * 80))
    control = FakeControl(script=script)
    panel, motion = _panel(qtbot, control=control)

    hud = console_hud(motion, control=control.state(), script=script)

    assert hud.drive.position == round(0.25 * POSITION_MAX)


def test_the_motion_is_drawn_again_once_the_script_is_done(qtbot):
    script = FakeScript(active=False)
    control = FakeControl(script=script)
    panel, motion = _panel(qtbot, control=control)
    motion.active = True

    hud = console_hud(motion, control=control.state(), script=script)

    assert hud.drive.driven == "robot_hand"
    assert hud.console.osr2 is Osr2State.ROBOT_HAND


def test_with_its_switch_off_the_console_says_parked_over_a_device_that_is_on(qtbot):
    painter = ConsolePainter()
    hud = console_hud(FakeMotion(), device=Osr2Mode.CONTROLLED, control=OSR2_PARKED)
    painter.rgba(hud)

    assert painter._osr2_state(hud.console) == OSR2_PARKED


def test_a_device_that_is_not_answering_is_driven_by_nobody(qtbot):
    """The script streams into the air with the OSR2 switched off, and a green
    line would say it was arriving."""
    script = FakeScript()
    control = FakeControl(script=script)
    panel, motion = _panel(qtbot, control=control)

    hud = console_hud(motion, device=Osr2Mode.OFF, control=control.state(),
                      script=script)

    assert hud.console.osr2 is Osr2State.OFF


def test_a_parked_device_offers_none_of_the_motions_marks(qtbot):
    # A press that could do nothing is not offered — the readout is dimmed whole
    # while nothing is reaching the device, exactly as it is in Fun Time while a
    # funscript has it.
    panel, _motion = _panel(qtbot, control=FakeControl(state=OSR2_PARKED))
    panel.drawing()
    marks = [b for _r, b in panel._painter.buttons
             if b.command.startswith(("robot_hand_speed", "robot_hand_amplitude", "robot_hand_center"))]
    assert marks
    assert all(b.dim for b in marks)


def test_dragging_a_band_sets_the_level_under_the_pointer(qtbot):
    panel, motion = _panel(qtbot)
    motion.active = True
    panel.drawing()
    speed = next(t for t in panel._painter.tracks if t.axis == "speed")
    x, y, w, _h = speed.rect
    QTest.mousePress(panel, Qt.MouseButton.LeftButton, pos=QPoint(x + w - 1, y))
    assert motion.calls == [("set_speed", 100)]


def test_the_readout_is_the_motion_only_while_it_runs(qtbot):
    motion = FakeMotion()
    assert drive_hud(motion.state, False).driven == DRIVEN_BY_NOTHING
    assert drive_hud(motion.state, True).driven == DRIVEN_BY_ROBOT_HAND


def test_off_is_said_only_of_a_device_that_is_switched_off(qtbot):
    motion = FakeMotion()
    for running in (False, True):
        motion.active = running
        assert console_hud(motion).console.osr2 is Osr2State.ROBOT_HAND, running


def test_a_motion_with_the_osr2_switched_off_says_off_and_drives_nothing(qtbot):
    # The motion goes on with the device unplugged — it cannot see the
    # wire — so without this the console animated a blue wave nobody was riding.
    # Saying "off" is also what grays the readout and holds its trace still: the
    # painter reads who has the device off this one value (funestra).

    motion = FakeMotion()
    motion.active = True

    hud = console_hud(motion, device=Osr2Mode.OFF)

    assert hud.console.osr2 is Osr2State.OFF
    assert hud.drive.driven == DRIVEN_BY_NOTHING
    assert not hud.drive.live


@pytest.mark.parametrize(("trouble", "said"), [(Osr2Trouble.NOT_FOUND, Osr2State.UNPLUGGED),
                                               (Osr2Trouble.NOT_ANSWERING, Osr2State.NO_ANSWER)])
def test_an_osr2_the_broker_cannot_hear_says_why_and_drives_nothing(qtbot, trouble, said):
    motion = FakeMotion()
    motion.active = True

    hud = console_hud(motion, device=Osr2Mode.OFF, trouble=trouble)

    assert hud.console.osr2 is said
    assert hud.drive.driven == DRIVEN_BY_NOTHING
    assert not hud.drive.live


def test_the_panel_redraws_once_the_device_switches_under_what_it_drew(qtbot):
    device = {"on": False}
    panel = MotionPanel(FakeMotion(),
                        device=lambda: Osr2Mode.CONTROLLED if device["on"] else Osr2Mode.OFF,
                        control=FakeControl(state=OSR2_PARKED))
    qtbot.addWidget(panel)
    panel.drawing()

    assert panel._redraw_if_the_device_switched() is False
    device["on"] = True
    assert panel._redraw_if_the_device_switched() is True


def test_the_panel_redraws_once_the_broker_starts_or_stops(qtbot, monkeypatch):
    running = {"now": True}
    monkeypatch.setattr("origenerator.osr2.broker_running", lambda: running["now"])
    panel, _motion = _panel(qtbot, control=FakeControl(state=OSR2_PARKED))
    panel.drawing()

    assert panel._redraw_if_the_device_switched() is False
    running["now"] = False
    assert panel._redraw_if_the_device_switched() is True


def test_the_panel_redraws_once_the_broker_says_why_it_cannot_hear_the_osr2(qtbot):
    trouble = {"now": None}
    panel = MotionPanel(FakeMotion(), device=lambda: Osr2Mode.OFF,
                        trouble=lambda: trouble["now"], control=FakeControl(state=OSR2_PARKED))
    qtbot.addWidget(panel)
    panel.drawing()

    assert panel._redraw_if_the_device_switched() is False
    trouble["now"] = Osr2Trouble.NOT_FOUND
    assert panel._redraw_if_the_device_switched() is True


def test_the_panel_watches_the_device_for_as_long_as_it_is_shown(qtbot):
    panel, _motion = _panel(qtbot, control=FakeControl(state=OSR2_PARKED))

    panel.show()
    assert panel._device_watch.isActive()
    panel.hide()
    assert not panel._device_watch.isActive()


def test_the_panel_asks_whether_the_device_is_answering_on_every_draw(qtbot):
    # Asked per draw rather than once: the OSR2 is switched on and off without
    # this app's back, so a console that read it at build time would go on
    # claiming whatever was true when it opened.
    answers = [Osr2Mode.OFF, Osr2Mode.CONTROLLED]
    motion = FakeMotion()
    motion.active = True
    panel = MotionPanel(motion, device=lambda: answers.pop(0))
    qtbot.addWidget(panel)

    panel.drawing()
    assert answers == [Osr2Mode.CONTROLLED]  # it asked
    panel.drawing()
    assert answers == []      # and asked again rather than reusing the answer


def _first_named_button(panel) -> tuple[int, int, int, int]:
    panel.grab()  # lays the buttons out
    return next(rect for rect, button in panel._painter.buttons if button.tooltip)


def _ground_lightness(panel, rect) -> int:
    x, y, _w, h = rect
    return panel.grab().toImage().pixelColor(x + 2, y + h // 2).lightness()


def _move_onto(panel, rect) -> None:
    x, y, w, h = rect
    at = QPointF(x + w // 2, y + h // 2)
    QApplication.sendEvent(panel, QMouseEvent(
        QEvent.Type.MouseMove, at, QPointF(panel.mapToGlobal(at.toPoint())),
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))


def test_the_panel_hears_the_pointer_move_with_no_button_held(qtbot):
    # Qt hands a widget a plain move only when it asks for every move; without
    # that, the panel heard the pointer only while a button was held.
    panel, _motion = _panel(qtbot)

    assert panel.hasMouseTracking()


def test_the_button_under_the_pointer_lights_up(qtbot):
    # The panel over a Slideshow lit the button under the pointer and this one
    # did not, though the same painter draws both: nothing told it where the
    # pointer was.
    panel, _motion = _panel(qtbot)
    button = _first_named_button(panel)
    at_rest = _ground_lightness(panel, button)

    _move_onto(panel, button)

    assert _ground_lightness(panel, button) > at_rest


def test_the_button_goes_back_once_the_pointer_leaves(qtbot):
    panel, _motion = _panel(qtbot)
    button = _first_named_button(panel)
    at_rest = _ground_lightness(panel, button)
    _move_onto(panel, button)

    QApplication.sendEvent(panel, QEvent(QEvent.Type.Leave))

    assert _ground_lightness(panel, button) == at_rest


def test_no_tooltip_of_the_panels_own_comes_up_over_a_buttons_name(qtbot):
    panel, _motion = _panel(qtbot)

    assert panel.toolTip() == ""


def test_the_panel_actually_paints(qtbot):
    # A NameError in paintEvent takes the whole app down the first time the
    # panel is shown — which is what shipped once.
    panel, motion = _panel(qtbot)

    assert not panel.grab().isNull()

    motion.active = True
    motion.state.learned.active = True

    assert not panel.grab().isNull()  # and again with every reading lit


def test_the_panel_keeps_the_room_its_console_takes_at_its_widest(qtbot):
    panel, motion = _panel(qtbot)
    panel.show()
    panel.grab()  # a paint of the console as it stands, narrower than at its widest

    assert (panel.width(), panel.height()) == panel_room(motion)


def test_no_state_draws_the_console_outside_the_room_kept_for_it():
    motion = FakeMotion()
    room_width, room_height = panel_room(motion)

    for control, active, device, script in itertools.product(
            (*OSR2_CONTROL_BUTTONS, OSR2_CONTROL_UNANSWERED), (False, True), Osr2Mode,
            (None, FakeScript())):
        motion.active = active
        _raw, (width, height) = ConsolePainter(device_only=True).rgba(
            console_hud(motion, device=device, control=control, script=script))

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

    assert console_hud(motion, device=Osr2Mode.AUTO).console.osr2 is Osr2State.AUTO


def test_the_panel_redraws_once_the_osr2_goes_into_its_own_auto_mode(qtbot):
    device = {"mode": Osr2Mode.CONTROLLED}
    panel = MotionPanel(FakeMotion(), device=lambda: device["mode"],
                        control=FakeControl(state=OSR2_DRIVING))
    qtbot.addWidget(panel)
    panel.drawing()

    device["mode"] = Osr2Mode.AUTO

    assert panel._redraw_if_the_device_switched() is True
