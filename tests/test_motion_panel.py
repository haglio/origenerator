"""MotionPanel — Genau's console, shown here, and what a press on it does.

The console is player_core's and tested there. What this covers is the two
things that are this app's: that the picture really is that console (not a
lookalike), and that each command it posts reaches the right thing here.
"""
from __future__ import annotations

import random

from player_core import drive_layout, wave_stack
from player_core.console import (
    OSR2_CONTROL_BUTTONS,
    OSR2_CONTROL_OFF,
    OSR2_DRIVING,
    OSR2_PARKED,
)
from player_core.console_hud import ConsolePainter
from player_core.drive_readout import DRIVEN_BY_NOTHING, DRIVEN_BY_ROBOT_HAND
from player_core.learned_model import LearnedModel, Phrase, classify
from player_core.modes import Osr2State
from player_core.robot_hand import PARK_CENTER, POSITION_MAX
from PyQt6.QtCore import QObject, pyqtSignal

from origenerator import motion_engine
from origenerator.gui.console import console_hud, drive_hud
from origenerator.gui.motion_panel import MotionPanel
from tests.motion_doubles import FakeMotion


def _panel(qtbot, motion=None, control=None):
    motion = motion if motion is not None else FakeMotion()
    panel = MotionPanel(motion, control=control)
    qtbot.addWidget(panel)
    return panel, motion


def _press(panel, action):
    """Press whatever button posts *action*, at its own middle.

    The painter takes window coordinates and its rects are panel ones, so the
    margin goes back on — the same conversion the widget does with the pointer.
    """
    rect = next(r for r, b in panel._painter.buttons if b.command == action)
    x, y, w, h = rect
    margin = MotionPanel.MARGIN
    panel._post(panel._painter.press_at(x + w // 2 + margin, y + h // 2 + margin))


def _slide(panel, along: float) -> None:
    max_intensity = next(t for t in panel._painter.tracks if t.axis == drive_layout.MAX_INTENSITY)
    x, y, w, h = max_intensity.rect
    margin = MotionPanel.MARGIN
    panel._post(panel._painter.press_at(x + round(along * (w - 1)) + margin,
                                        y + h // 2 + margin))


def test_the_console_carries_no_filter_switches_of_its_own(qtbot):
    # Over a show the two switches saying what it may play are on the players'
    # HUD this panel sits under, and a second pair here would be two switches
    # for one thing — so the console offers neither, the way Genau's own does.
    panel, _motion = _panel(qtbot)
    panel.render_console()
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


def test_the_picture_is_the_console_player_core_paints(qtbot):
    # Not a repaint of the design, and not a third of it: the same painter, the
    # same rows, the same bitmap.
    panel, motion = _panel(qtbot)
    raw, size = panel.render_console()
    expected, expected_size = ConsolePainter(device_only=True).rgba(console_hud(motion))
    assert (raw, size) == (expected, expected_size)


def test_the_main_windows_console_is_its_osr2_section_alone(qtbot):
    panel, _motion = _panel(qtbot)
    panel.render_console()
    actions = [b.command for _rect, b in panel._painter.buttons]

    assert not any(a.endswith("_minimize") for a in actions)
    for gone in ("genau_prev_clip", "genau_next_clip", "main_lock", "genau_weird_clip",
                 "genau_clip_seconds_down", "genau_clip_seconds_up"):
        assert gone not in actions, gone
    for kept in ("robot_hand_toggle_cruise", "robot_hand_toggle_learned",
                 "robot_hand_cycle_shape", "quarter_button", "robot_hand_park",
                 "robot_hand_retract", "robot_hand_release",
                 "robot_hand_speed_up", "robot_hand_amplitude_up", "robot_hand_center_up"):
        assert kept in actions, kept


def test_the_console_declares_the_buttons_this_app_answers(qtbot):
    """The motion's own row -- declared here rather than left to the players'
    stock set, which offers verbs this app has no answer for."""
    _panel_, motion = _panel(qtbot)

    hud = console_hud(motion, control=OSR2_DRIVING)

    assert hud.console.rows == ()
    assert [[b.command for b in row] for row in hud.console.osr2_rows] == [
        ["robot_hand_toggle_cruise", "robot_hand_toggle_learned", "robot_hand_cycle_shape",
         "quarter_button", "osr2_control_off", "robot_hand_park", "robot_hand_retract",
         "robot_hand_release"],
    ]
    assert hud.console.osr2_controls == ()


def test_every_button_the_console_declares_does_something_here(qtbot):
    control = FakeControl()
    panel, motion = _panel(qtbot, control=control)
    motion.active = True
    panel.render_console()
    console = console_hud(motion, control=control.state()).console
    declared = [b.command for row in (*console.rows, *console.osr2_rows) for b in row if b.command]

    for command in declared:
        before = len(motion.calls) + len(control.asked)
        _press(panel, command)
        assert len(motion.calls) + len(control.asked) > before, command


def test_the_motion_buttons_reach_the_driver(qtbot):
    panel, motion = _panel(qtbot)
    motion.active = True  # a parked device's marks are dimmed, and dim is unpressable
    # A full-travel motion has its center pinned, and a pinned mark is dim too.
    motion.state.state.amplitude = 40
    panel.render_console()
    for action in ("robot_hand_speed_up", "robot_hand_amplitude_down", "robot_hand_center_up",
                   "robot_hand_toggle_cruise", "robot_hand_toggle_learned",
                   "robot_hand_cycle_shape", "quarter_button"):
        _press(panel, action)
    assert motion.calls == [("speed", 5), ("amp", -10), ("center", 5),
                            "cruise", "learned", "shape", "quarter"]


def test_each_press_on_the_waveform_button_changes_the_face_it_wears(qtbot):
    panel, _motion = _panel(qtbot)
    faces = []
    for _waveform in motion_engine.WaveformShape:
        panel.render_console()
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


def test_the_max_intensity_slider_asks_the_apps_one_switch_for_the_level(qtbot):
    control = FakeControl()
    panel, motion = _panel(qtbot, control=control)
    panel.render_console()

    _slide(panel, 1.0)

    assert control.max_intensities == [100] and motion.calls == []


def test_a_panel_with_no_switch_hands_the_max_intensity_to_the_motion(qtbot):
    panel, motion = _panel(qtbot)
    panel.render_console()

    _slide(panel, 0.0)

    assert motion.calls == [("max_intensity", 0)]


def test_the_control_group_asks_the_apps_one_switch(qtbot):
    """The four buttons are the app's OSR2 switch now, on every surface -- which
    is what the separate toolbar one was replaced by."""
    control = FakeControl()
    panel, _motion = _panel(qtbot, control=control)
    panel.render_console()

    for action in OSR2_CONTROL_BUTTONS.values():
        _press(panel, action)

    assert control.asked == list(OSR2_CONTROL_BUTTONS)


def test_the_group_lights_the_state_the_switch_is_in(qtbot):
    """The console draws the lit button; what this app owes it is the answer to
    which state, which nothing on the panel itself knows."""
    control = FakeControl(OSR2_CONTROL_OFF)
    panel, motion = _panel(qtbot, control=control)

    hud = console_hud(motion, control=control.state())

    assert hud.console.osr2_control == OSR2_CONTROL_OFF
    assert panel.render_console()[0]  # and it paints in that state


def test_a_panel_with_no_switch_still_holds_the_motion(qtbot):
    """A console outside a gallery -- a test's, and any future host that hands
    over no switch -- can still park and release what it does have."""
    panel, motion = _panel(qtbot)
    panel.render_console()

    _press(panel, OSR2_CONTROL_BUTTONS[OSR2_PARKED])
    _press(panel, OSR2_CONTROL_BUTTONS[OSR2_DRIVING])

    assert motion.calls == [("hold", PARK_CENTER), "release"]


class FakeScript:
    """The funscript driver reduced to what the console asks of one: whether it
    has the device, and the line it is about to send."""

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


def test_a_device_that_is_not_answering_is_driven_by_nobody(qtbot):
    """The script streams into the air with the OSR2 switched off, and a green
    line would say it was arriving."""
    script = FakeScript()
    control = FakeControl(script=script)
    panel, motion = _panel(qtbot, control=control)

    hud = console_hud(motion, device_on=False, control=control.state(),
                      script=script)

    assert hud.console.osr2 is Osr2State.OFF


def test_a_parked_device_offers_none_of_the_motions_marks(qtbot):
    # A press that could do nothing is not offered — the readout is dimmed whole
    # while nothing is reaching the device, exactly as it is in Fun Time while a
    # funscript has it.
    panel, motion = _panel(qtbot)
    panel.render_console()
    marks = [b for _r, b in panel._painter.buttons
             if b.command.startswith(("robot_hand_speed", "robot_hand_amplitude", "robot_hand_center"))]
    assert marks and all(b.dim for b in marks)


def test_dragging_a_band_sets_the_level_under_the_pointer(qtbot):
    panel, motion = _panel(qtbot)
    motion.active = True
    panel.render_console()
    speed = next(t for t in panel._painter.tracks if t.axis == "speed")
    x, y, w, _h = speed.rect
    margin = MotionPanel.MARGIN
    panel._post(panel._painter.press_at(x + w - 1 + margin, y + margin))
    assert motion.calls == [("set_speed", 100)]


def test_the_console_says_the_device_is_parked_while_it_is(qtbot):
    motion = FakeMotion()
    assert drive_hud(motion.state, False).driven == DRIVEN_BY_NOTHING
    assert drive_hud(motion.state, True).driven == DRIVEN_BY_ROBOT_HAND
    assert console_hud(motion).console.osr2 is Osr2State.OFF
    motion.active = True
    assert console_hud(motion).console.osr2 is Osr2State.ROBOT_HAND


def test_a_motion_with_the_osr2_switched_off_says_off_and_drives_nothing(qtbot):
    # The motion goes on with the device unplugged — it cannot see the
    # wire — so without this the console animated a blue wave nobody was riding.
    # Saying "off" is also what grays the readout and holds its trace still: the
    # painter reads who has the device off this one value (player_core).

    motion = FakeMotion()
    motion.active = True

    hud = console_hud(motion, device_on=False)

    assert hud.console.osr2 is Osr2State.OFF
    assert hud.drive.driven == DRIVEN_BY_NOTHING and not hud.drive.live


def test_the_panel_asks_whether_the_device_is_answering_on_every_draw(qtbot):
    # Asked per draw rather than once: the OSR2 is switched on and off without
    # this app's back, so a console that read it at build time would go on
    # claiming whatever was true when it opened.
    answers = [False, True]
    motion = FakeMotion()
    motion.active = True
    panel = MotionPanel(motion, device_on=lambda: answers.pop(0))
    qtbot.addWidget(panel)

    panel.render_console()
    assert answers == [True]  # it asked
    panel.render_console()
    assert answers == []      # and asked again rather than reusing the answer


def test_the_panel_actually_paints(qtbot):
    # A NameError in paintEvent takes the whole app down the first time the
    # panel is shown — which is what shipped once.
    panel, motion = _panel(qtbot)

    assert not panel.grab().isNull()

    motion.active = True
    motion.state.cruise.active = True

    assert not panel.grab().isNull()  # and again with every reading lit


def test_the_readout_shows_the_summed_motion_while_cruise_has_it(qtbot):
    # Cruise control hands the device several waves summed, and the readout is
    # meant to be the motion rather than a drawing of it — so the bar is the
    # whole motion's travel and center, and the trace is the sum, not whichever
    # wave happens to be the big one.

    motion = FakeMotion()
    live = motion.state
    live.state.playing = True
    live.cruise.rng = random.Random(4)
    motion_engine.toggle_cruise_control(live)
    now = 1000.0
    for _ in range(400):
        now += 0.05
        motion_engine.advance(live, 0.05)
        motion_engine.tick_cruise_control(live, now)

    bars = wave_stack.bars(live.cruise.stack, live.clock)
    hud = drive_hud(live, active=True)
    assert hud.amplitude == round(bars.travel)
    assert abs(hud.center - bars.center) <= 1
    assert hud.position == round(
        POSITION_MAX * wave_stack.position(live.cruise.stack, live.clock) / 100)
    assert len(set(hud.waveform)) > 20  # a live trace, not a held line
    assert len(hud.waveform) == drive_layout.TRACE_SAMPLES
    assert hud.edge is not None and 0.0 <= hud.slide < 1.0


def test_the_readout_holds_the_waves_picture_still_between_knots(qtbot):
    motion = FakeMotion()
    live = motion.state
    live.state.playing = True
    motion_engine.advance(live, 0.05)
    before = drive_hud(live, active=True)

    motion_engine.advance(live, 0.05)
    after = drive_hud(live, active=True)

    assert after.waveform == before.waveform
    assert after.slide > before.slide


def test_the_readout_holds_the_learned_motions_picture_still_between_knots(qtbot):
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
