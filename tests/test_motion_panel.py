"""MotionPanel — Genau's console, shown here, and what a press on it does.

The console is player_core's and tested there. What this covers is the two
things that are this app's: that the picture really is that console (not a
lookalike), and that each command it posts reaches the right thing here.
"""
from __future__ import annotations

from player_core import drive_layout, wave_stack
from player_core.console import (
    OSR2_CONTROL_BUTTONS,
    OSR2_CONTROL_OFF,
    OSR2_DRIVING,
    OSR2_PARKED,
)
from player_core.console_hud import ConsoleHud, ConsolePainter
from player_core.modes import Osr2State
from player_core.robot_hand import PARK_CENTER, POSITION_MAX
from PyQt6.QtCore import QObject, pyqtSignal

from origenerator import motion_engine
from origenerator.gui.console import console_hud, drive_hud
from origenerator.gui.motion_panel import MotionPanel
from tests.motion_doubles import FakeHost, FakeMotion


def _panel(qtbot, motion=None, host=None, control=None):
    motion = motion if motion is not None else FakeMotion()
    host = host if host is not None else FakeHost()
    panel = MotionPanel(motion, host=host, control=control)
    qtbot.addWidget(panel)
    return panel, motion, host


def _press(panel, action):
    """Press whatever button posts *action*, at its own middle.

    The painter takes window coordinates and its rects are panel ones, so the
    margin goes back on — the same conversion the widget does with the pointer.
    """
    rect = next(r for r, b in panel._painter.buttons if b.command == action)
    x, y, w, h = rect
    margin = MotionPanel.MARGIN
    panel._post(panel._painter.press_at(x + w // 2 + margin, y + h // 2 + margin))


def test_the_console_carries_no_filter_switches_of_its_own(qtbot):
    # Over a show the two switches saying what it may play are on the players'
    # HUD this panel sits under, and a second pair here would be two switches
    # for one thing — so the console offers neither, the way Genau's own does.
    panel, _motion, _host = _panel(qtbot)
    panel.render_console()
    for action in ("main_fmode", "genau_filter_enhanced"):
        assert action not in [b.command for _r, b in panel._painter.buttons]


def test_the_console_is_here_whether_or_not_a_motion_is_running(qtbot):
    # Part of what is on it is not about a running motion at all — the pace an
    # unheld slide moves on at. A panel that appeared only once the device was
    # driven made that reachable only by starting a motion.
    panel, motion, _host = _panel(qtbot)
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
    panel, motion, host = _panel(qtbot)
    raw, size = panel.render_console()
    expected, expected_size = ConsolePainter().rgba(console_hud(motion, host))
    assert (raw, size) == (expected, expected_size)


def test_the_mode_row_is_the_only_thing_left_off(qtbot):
    # This console lives inside another app's window, so it is not one of the
    # three players that row switches between and has none of its own to park.
    panel, motion, host = _panel(qtbot)
    panel.render_console()
    actions = [b.command for _rect, b in panel._painter.buttons]
    assert "main_minimize" not in actions
    assert not any(a.endswith("_activate") for a in actions)
    for kept in ("genau_prev_clip", "genau_next_clip", "main_lock",
                 "genau_weird_clip", "genau_clip_seconds_down", "genau_clip_seconds_up",
                 "robot_hand_toggle_cruise", "robot_hand_toggle_learned",
                 "robot_hand_cycle_shape", "quarter_button",
                 "robot_hand_speed_up", "robot_hand_amplitude_up", "robot_hand_center_up"):
        assert kept in actions, kept


def test_the_console_declares_the_buttons_this_app_answers(qtbot):
    """Genau's transport, its pace and the motion's own row -- declared here
    rather than left to the players' stock set, which offers verbs this app
    has no answer for."""
    _panel_, motion, host = _panel(qtbot)

    hud = console_hud(motion, host, control=OSR2_DRIVING)

    assert [[b.command for b in row] for row in hud.console.rows] == [
        ["genau_prev_clip", "genau_next_clip", "main_lock", "genau_weird_clip"],
        ["", "genau_clip_seconds_down", "", "genau_clip_seconds_up"],
        ["robot_hand_toggle_cruise", "robot_hand_toggle_learned", "robot_hand_cycle_shape",
         "quarter_button", "osr2_control_off", "robot_hand_park", "robot_hand_retract",
         "robot_hand_release"],
    ]
    assert hud.console.osr2_controls == ()


def test_every_button_the_console_declares_does_something_here(qtbot):
    control = FakeControl()
    panel, motion, host = _panel(qtbot, control=control)
    motion.active = True
    panel.render_console()
    declared = [b.command for row in console_hud(motion, host, control=control.state()).console.rows
                for b in row if b.command]

    for command in declared:
        before = len(motion.calls) + len(host.calls) + len(control.asked)
        _press(panel, command)
        assert len(motion.calls) + len(host.calls) + len(control.asked) > before, command


def test_the_motion_buttons_reach_the_driver(qtbot):
    panel, motion, _host = _panel(qtbot)
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


class FakeControl(QObject):
    """The app's OSR2 switch reduced to what the console's group asks of one."""

    changed = pyqtSignal()
    settled = pyqtSignal()

    def __init__(self, state=OSR2_DRIVING, script=None):
        super().__init__()
        self._state = state
        self.script = script
        self.asked = []

    def source(self):
        if self.script is not None and self.script.active:
            return "funscript"
        return "robot_hand"

    def state(self):
        return self._state

    def set_state(self, state):
        self._state = state
        self.asked.append(state)


def test_the_control_group_asks_the_apps_one_switch(qtbot):
    """The four buttons are the app's OSR2 switch now, on every surface -- which
    is what the separate toolbar one was replaced by."""
    control = FakeControl()
    panel, _motion, _host = _panel(qtbot, control=control)
    panel.render_console()

    for action in OSR2_CONTROL_BUTTONS.values():
        _press(panel, action)

    assert control.asked == list(OSR2_CONTROL_BUTTONS)


def test_the_group_lights_the_state_the_switch_is_in(qtbot):
    """The console draws the lit button; what this app owes it is the answer to
    which state, which nothing on the panel itself knows."""
    control = FakeControl(OSR2_CONTROL_OFF)
    panel, motion, host = _panel(qtbot, control=control)

    hud = console_hud(motion, host, control=control.state())

    assert hud.console.osr2_control == OSR2_CONTROL_OFF
    assert panel.render_console()[0]  # and it paints in that state


def test_a_panel_with_no_switch_still_holds_the_motion(qtbot):
    """A console outside a gallery -- a test's, and any future host that hands
    over no switch -- can still park and release what it does have."""
    panel, motion, _host = _panel(qtbot)
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
    panel, motion, host = _panel(qtbot, control=control)

    hud = console_hud(motion, host, control=control.state(), script=script)

    assert hud.drive.driven == "funscript"
    assert hud.drive.waveform == script.trace(80, 12.0)
    assert hud.console.osr2 is Osr2State.FUNSCRIPT


def test_the_dot_sits_where_the_script_has_the_device_now(qtbot):
    script = FakeScript(heights=tuple([0.25] * 80))
    control = FakeControl(script=script)
    panel, motion, host = _panel(qtbot, control=control)

    hud = console_hud(motion, host, control=control.state(), script=script)

    assert hud.drive.position == round(0.25 * POSITION_MAX)


def test_the_motion_is_drawn_again_once_the_script_is_done(qtbot):
    script = FakeScript(active=False)
    control = FakeControl(script=script)
    panel, motion, host = _panel(qtbot, control=control)
    motion.active = True

    hud = console_hud(motion, host, control=control.state(), script=script)

    assert hud.drive.driven == "robot_hand"
    assert hud.console.osr2 is Osr2State.ROBOT_HAND


def test_a_device_that_is_not_answering_is_driven_by_nobody(qtbot):
    """The script streams into the air with the OSR2 switched off, and a green
    line would say it was arriving."""
    script = FakeScript()
    control = FakeControl(script=script)
    panel, motion, host = _panel(qtbot, control=control)

    hud = console_hud(motion, host, device_on=False, control=control.state(),
                      script=script)

    assert hud.console.osr2 is Osr2State.OFF


def test_the_transport_and_the_pace_reach_the_slideshow(qtbot):
    # Genau's transport steps its clips and its clip-seconds pair paces them;
    # here the clips are the slides, which is what makes the same row mean
    # something rather than being drawn dead.
    panel, _motion, host = _panel(qtbot)
    panel.render_console()
    for action in ("genau_next_clip", "genau_prev_clip", "main_lock",
                   "genau_weird_clip", "genau_clip_seconds_up"):
        _press(panel, action)
    assert host.calls == [("step", 1), ("step", -1), "lock", "cull", ("dwell", 5)]


def test_a_parked_device_offers_none_of_the_motions_marks(qtbot):
    # A press that could do nothing is not offered — the readout is dimmed whole
    # while nothing is reaching the device, exactly as it is in Fun Time while a
    # funscript has it.
    panel, motion, _host = _panel(qtbot)
    panel.render_console()
    marks = [b for _r, b in panel._painter.buttons
             if b.command.startswith(("robot_hand_speed", "robot_hand_amplitude", "robot_hand_center"))]
    assert marks and all(b.dim for b in marks)


def test_the_pace_stops_at_its_ends(qtbot):
    from origenerator.gui.slideshow_pace import MAX_S, MIN_S

    panel, _motion, host = _panel(qtbot)
    host.dwell_s = MIN_S
    panel.render_console()
    _press(panel, "genau_clip_seconds_down")
    assert host.dwell_s == MIN_S
    host.dwell_s = MAX_S
    panel.render_console()
    _press(panel, "genau_clip_seconds_up")
    assert host.dwell_s == MAX_S


def test_dragging_a_band_sets_the_level_under_the_pointer(qtbot):
    panel, motion, _host = _panel(qtbot)
    motion.active = True
    panel.render_console()
    speed = next(t for t in panel._painter.tracks if t.axis == "speed")
    x, y, w, _h = speed.rect
    margin = MotionPanel.MARGIN
    panel._post(panel._painter.press_at(x + w - 1 + margin, y + margin))
    assert motion.calls == [("set_speed", 100)]


def test_the_console_says_the_device_is_parked_while_it_is(qtbot):
    from player_core.drive_readout import DRIVEN_BY_NOTHING, DRIVEN_BY_ROBOT_HAND

    motion = FakeMotion()
    assert drive_hud(motion.state, False).driven == DRIVEN_BY_NOTHING
    assert drive_hud(motion.state, True).driven == DRIVEN_BY_ROBOT_HAND
    assert console_hud(motion, FakeHost()).console.osr2 is Osr2State.OFF
    motion.active = True
    assert console_hud(motion, FakeHost()).console.osr2 is Osr2State.ROBOT_HAND


def test_a_motion_with_the_osr2_switched_off_says_off_and_drives_nothing(qtbot):
    # The motion goes on with the device unplugged — it cannot see the
    # wire — so without this the console animated a blue wave nobody was riding.
    # Saying "off" is also what greys the readout and holds its trace still: the
    # painter reads who has the device off this one value (player_core).
    from player_core.drive_readout import DRIVEN_BY_NOTHING

    motion = FakeMotion()
    motion.active = True

    hud = console_hud(motion, FakeHost(), device_on=False)

    assert hud.console.osr2 is Osr2State.OFF
    assert hud.drive.driven == DRIVEN_BY_NOTHING and not hud.drive.live


def test_the_panel_asks_whether_the_device_is_answering_on_every_draw(qtbot):
    # Asked per draw rather than once: the OSR2 is switched on and off without
    # this app's back, so a console that read it at build time would go on
    # claiming whatever was true when it opened.
    answers = [False, True]
    motion = FakeMotion()
    motion.active = True
    panel = MotionPanel(motion, host=FakeHost(), device_on=lambda: answers.pop(0))
    qtbot.addWidget(panel)

    panel.render_console()
    assert answers == [True]  # it asked
    panel.render_console()
    assert answers == []      # and asked again rather than reusing the answer


def test_the_slideshows_pace_rides_the_console(qtbot):
    panel, motion, host = _panel(qtbot)
    host.dwell_s = 7
    hud = console_hud(motion, host)
    assert hud.console.advance_interval == 7
    assert hud.drive.advance_interval == 7
    assert isinstance(hud, ConsoleHud)
    assert len(hud.console.rows) == 3


def test_the_panel_actually_paints(qtbot):
    # A NameError in paintEvent takes the whole app down the first time the
    # panel is shown — which is what shipped once.
    panel, motion, _host = _panel(qtbot)

    assert not panel.grab().isNull()

    motion.active = True
    motion.state.cruise.active = True

    assert not panel.grab().isNull()  # and again with every reading lit


def test_the_pace_starts_at_the_slideshows_own_default(qtbot):
    # It read 0s, which is not a pace at all — the console has to open on the
    # number the slideshow actually uses, whether or not one is running.
    from origenerator.gui.slideshow_pace import PaceOnlyHost, SlideshowPace
    from origenerator.slideshow import DEFAULT_IMAGE_DWELL_MS

    pace = SlideshowPace()
    assert pace.seconds == DEFAULT_IMAGE_DWELL_MS // 1000
    panel = MotionPanel(FakeMotion(), host=PaceOnlyHost(pace))
    qtbot.addWidget(panel)
    assert console_hud(panel._motion, panel._host).console.advance_interval == pace.seconds


def test_setting_the_pace_with_nothing_playing_is_what_the_next_one_opens_at(qtbot):
    from origenerator.gui.slideshow_pace import PaceOnlyHost, SlideshowPace
    from origenerator.gui.slideshow_view import SlideshowView

    pace = SlideshowPace()
    panel = MotionPanel(FakeMotion(), host=PaceOnlyHost(pace))
    qtbot.addWidget(panel)
    panel.render_console()
    _press(panel, "genau_clip_seconds_up")
    view = SlideshowView([("a.png", "image", 1)], shuffle=lambda items: None,
                         pace=pace)
    qtbot.addWidget(view)
    assert view._playlist.image_dwell_ms == pace.seconds * 1000


def test_turning_the_pace_up_changes_a_running_slideshow(qtbot):
    from origenerator.gui.slideshow_pace import SlideshowPace
    from origenerator.gui.slideshow_view import SlideshowView

    pace = SlideshowPace()
    view = SlideshowView([("a.png", "image", 1), ("b.png", "image", 2)],
                         shuffle=lambda items: None, pace=pace)
    qtbot.addWidget(view)
    pace.set_seconds(9)
    assert view._playlist.image_dwell_ms == 9000
    assert view.dwell_s == 9


def test_the_readout_shows_the_summed_motion_while_cruise_has_it(qtbot):
    # Cruise control hands the device several waves summed, and the readout is
    # meant to be the motion rather than a drawing of it — so the bar is the
    # whole motion's travel and center, and the trace is the sum, not whichever
    # wave happens to be the big one.
    import random

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

    dials = wave_stack.dials(live.cruise.stack, live.clock)
    hud = drive_hud(live, active=True)
    assert hud.amplitude == round(dials.travel)
    assert abs(hud.center - dials.center) <= 1
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
    import random

    from player_core.learned_model import LearnedModel, Phrase, classify

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
