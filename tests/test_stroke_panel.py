"""StrokePanel — Genau's console, shown here, and what a press on it does.

The console is player_core's and tested there. What this covers is the two
things that are this app's: that the picture really is that console (not a
lookalike), and that each command it posts reaches the right thing here.
"""

from player_core import wave_stack
from player_core.console import console_rows
from player_core.console_hud import ConsoleHud, ConsolePainter
from player_core.robot_hand import POSITION_MAX

from origenerator import stroke_engine
from origenerator.gui.stroke_panel import StrokePanel, console_hud, drive_hud
from origenerator.stroke_engine import Stroke


class FakeStroke:
    """Stands in for the driver: records what the console asked it to do."""

    def __init__(self):
        self.state = Stroke()
        self.active = False
        self.calls = []

    def toggle_cruise(self):
        self.calls.append("cruise")
        self.state.cruise.active = not self.state.cruise.active

    def cycle_shape(self):
        self.calls.append("shape")

    def quarter_offset(self):
        self.calls.append("quarter")

    def adjust_speed(self, delta):
        self.calls.append(("speed", delta))

    def adjust_amplitude(self, delta):
        self.calls.append(("amp", delta))

    def adjust_center(self, delta):
        self.calls.append(("center", delta))

    def set_speed(self, value):
        self.calls.append(("set_speed", value))

    def set_amplitude(self, value):
        self.calls.append(("set_amp", value))

    def set_center(self, value):
        self.calls.append(("set_center", value))


class FakeHost:
    """Stands in for the slideshow the transport and the pace act on."""

    def __init__(self):
        self.dwell_s = 4
        self.locked = True
        self.calls = []

    def stroke_step(self, delta):
        self.calls.append(("step", delta))

    def stroke_toggle_hold(self):
        self.calls.append("hold")

    def stroke_cull(self):
        self.calls.append("cull")

    def set_dwell_s(self, seconds):
        from origenerator.gui.slideshow_pace import MAX_S, MIN_S
        self.dwell_s = max(MIN_S, min(MAX_S, seconds))
        self.calls.append(("dwell", self.dwell_s))


def _panel(qtbot, stroke=None, host=None):
    stroke = stroke if stroke is not None else FakeStroke()
    host = host if host is not None else FakeHost()
    panel = StrokePanel(stroke, host=host)
    qtbot.addWidget(panel)
    return panel, stroke, host


def _press(panel, action):
    """Press whatever button posts *action*, at its own middle.

    The painter takes window coordinates and its rects are panel ones, so the
    margin goes back on — the same conversion the widget does with the pointer.
    """
    rect = next(r for r, b in panel._painter.buttons if b.action == action)
    x, y, w, h = rect
    margin = StrokePanel.MARGIN
    panel._post(panel._painter.press_at(x + w // 2 + margin, y + h // 2 + margin))


def test_the_console_carries_no_filter_switches_of_its_own(qtbot):
    # Over a show the two switches saying what it may play are on the players'
    # HUD this panel sits under, and a second pair here would be two switches
    # for one thing — so the console offers neither, the way Genau's own does.
    panel, _stroke, _host = _panel(qtbot)
    panel.render_console()
    for action in ("main_fmode", "genau_filter_enhanced"):
        assert action not in [b.action for _r, b in panel._painter.buttons]


def test_the_console_seats_itself_under_a_panel_already_in_the_corner(qtbot):
    # A show wears the players' HUD in the corner this console takes, so given
    # that HUD's rect the console goes directly beneath it, flush with its left
    # edge and a panel-inset apart — one column of panels, neither over the other.
    from PyQt6.QtCore import QRect
    from PyQt6.QtWidgets import QWidget

    parent = QWidget()
    qtbot.addWidget(parent)
    panel = StrokePanel(FakeStroke(), parent, host=FakeHost())

    panel.reposition()
    assert (panel.x(), panel.y()) == (StrokePanel.MARGIN, StrokePanel.MARGIN)

    panel.reposition(below=QRect(12, 12, 300, 140))
    assert (panel.x(), panel.y()) == (12, 12 + 140 + 12)


def test_the_console_is_a_native_window_that_does_not_ask_for_a_translucent_surface(qtbot):
    # Native, so it stacks over a clip's video surface like the HUD does; and
    # like the HUD it leaves the translucent-surface flag alone.  A native child
    # that asked for one drew twice over a show on Windows -- once where Qt
    # painted it and once more at double its offset -- while its see-through
    # ground needs nothing but the RGBA picture over the parent's own paint.
    from PyQt6.QtCore import Qt

    panel, _stroke, _host = _panel(qtbot)
    assert panel.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)
    assert not panel.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


def test_the_console_is_here_whether_or_not_a_stroke_is_running(qtbot):
    # Part of what is on it is not about a running stroke at all — the pace an
    # unheld slide moves on at. A panel that appeared only once the device was
    # driven made that reachable only by starting a stroke.
    panel, stroke, _host = _panel(qtbot)
    panel.show()

    assert stroke.active is False
    assert panel.isVisible()
    assert not panel._repaint.isActive()   # nothing is moving, so nothing repaints

    stroke.active = True
    panel.refresh()

    assert panel.isVisible()
    assert panel._repaint.isActive()       # the trace scrolls, so now it does


def test_the_picture_is_the_console_player_core_paints(qtbot):
    # Not a repaint of the design, and not a third of it: the same painter, the
    # same rows, the same bitmap.
    panel, stroke, host = _panel(qtbot)
    raw, size = panel.render_console()
    expected, expected_size = ConsolePainter().rgba(console_hud(stroke, host))
    assert (raw, size) == (expected, expected_size)


def test_the_mode_row_is_the_only_thing_left_off(qtbot):
    # This console lives inside another app's window, so it is not one of the
    # three players that row switches between and has none of its own to park.
    panel, stroke, host = _panel(qtbot)
    panel.render_console()
    actions = [b.action for _rect, b in panel._painter.buttons]
    assert "main_minimize" not in actions
    assert not any(a.endswith("_activate") for a in actions)
    for kept in ("genau_prev_clip", "genau_next_clip", "main_lock",
                 "genau_weird_clip", "genau_advance_down", "genau_advance_up",
                 "robot_hand_toggle_cruise", "robot_hand_cycle_shape", "quarter_button",
                 "robot_hand_speed_up", "robot_hand_amplitude_up", "robot_hand_center_up"):
        assert kept in actions, kept


def test_the_stroke_buttons_reach_the_driver(qtbot):
    panel, stroke, _host = _panel(qtbot)
    stroke.active = True  # a parked device's marks are dimmed, and dim is unpressable
    # A full-travel stroke has its center pinned, and a pinned mark is dim too.
    stroke.state.state.amplitude = 40
    panel.render_console()
    for action in ("robot_hand_speed_up", "robot_hand_amplitude_down", "robot_hand_center_up",
                   "robot_hand_toggle_cruise", "robot_hand_cycle_shape", "quarter_button"):
        _press(panel, action)
    assert stroke.calls == [("speed", 5), ("amp", -10), ("center", 5),
                            "cruise", "shape", "quarter"]


def test_the_transport_and_the_pace_reach_the_slideshow(qtbot):
    # Genau's transport steps its clips and its clip-seconds pair paces them;
    # here the clips are the slides, which is what makes the same row mean
    # something rather than being drawn dead.
    panel, _stroke, host = _panel(qtbot)
    panel.render_console()
    for action in ("genau_next_clip", "genau_prev_clip", "main_lock",
                   "genau_weird_clip", "genau_advance_up"):
        _press(panel, action)
    assert host.calls == [("step", 1), ("step", -1), "hold", "cull", ("dwell", 5)]


def test_a_parked_device_offers_none_of_the_strokes_marks(qtbot):
    # A press that could do nothing is not offered — the readout is dimmed whole
    # while nothing is reaching the device, exactly as it is in Fun Time while a
    # funscript has it.
    panel, stroke, _host = _panel(qtbot)
    panel.render_console()
    marks = [b for _r, b in panel._painter.buttons
             if b.action.startswith(("robot_hand_speed", "robot_hand_amplitude", "robot_hand_center"))]
    assert marks and all(b.dim for b in marks)


def test_the_pace_stops_at_its_ends(qtbot):
    from origenerator.gui.slideshow_pace import MAX_S, MIN_S

    panel, _stroke, host = _panel(qtbot)
    host.dwell_s = MIN_S
    panel.render_console()
    _press(panel, "genau_advance_down")
    assert host.dwell_s == MIN_S
    host.dwell_s = MAX_S
    panel.render_console()
    _press(panel, "genau_advance_up")
    assert host.dwell_s == MAX_S


def test_dragging_a_band_sets_the_level_under_the_pointer(qtbot):
    panel, stroke, _host = _panel(qtbot)
    stroke.active = True
    panel.render_console()
    speed = next(t for t in panel._painter.tracks if t.axis == "speed")
    x, y, w, _h = speed.rect
    margin = StrokePanel.MARGIN
    panel._post(panel._painter.press_at(x + w - 1 + margin, y + margin))
    assert stroke.calls == [("set_speed", 100)]


def test_the_console_says_the_device_is_parked_while_it_is(qtbot):
    from player_core.drive_readout import DRIVEN_BY_NOTHING, DRIVEN_BY_ROBOT_HAND

    stroke = FakeStroke()
    assert drive_hud(stroke.state, False).driven == DRIVEN_BY_NOTHING
    assert drive_hud(stroke.state, True).driven == DRIVEN_BY_ROBOT_HAND
    assert console_hud(stroke, FakeHost()).console.osr2 == "off"
    stroke.active = True
    assert console_hud(stroke, FakeHost()).console.osr2 == "robot_hand"


def test_a_stroke_with_the_osr2_switched_off_says_off_and_drives_nothing(qtbot):
    # The stroke goes on stroking with the device unplugged — it cannot see the
    # wire — so without this the console animated a blue wave nobody was riding.
    # Saying "off" is also what greys the readout and holds its trace still: the
    # painter reads who has the device off this one value (player_core).
    from player_core.drive_readout import DRIVEN_BY_NOTHING

    stroke = FakeStroke()
    stroke.active = True

    hud = console_hud(stroke, FakeHost(), device_on=False)

    assert hud.console.osr2 == "off"
    assert hud.drive.driven == DRIVEN_BY_NOTHING and not hud.drive.live


def test_the_panel_asks_whether_the_device_is_answering_on_every_draw(qtbot):
    # Asked per draw rather than once: the OSR2 is switched on and off behind
    # this app's back, so a console that read it at build time would go on
    # claiming whatever was true when it opened.
    answers = [False, True]
    stroke = FakeStroke()
    stroke.active = True
    panel = StrokePanel(stroke, host=FakeHost(), device_on=lambda: answers.pop(0))
    qtbot.addWidget(panel)

    panel.render_console()
    assert answers == [True]  # it asked
    panel.render_console()
    assert answers == []      # and asked again rather than reusing the answer


def test_the_slideshows_pace_rides_the_console(qtbot):
    panel, stroke, host = _panel(qtbot)
    host.dwell_s = 7
    hud = console_hud(stroke, host)
    assert hud.console.advance_interval == 7
    assert hud.drive.advance_interval == 7
    assert isinstance(hud, ConsoleHud) and not hud.modes_row
    assert len(console_rows(hud.console, modes=False)) == 3


def test_the_panel_actually_paints(qtbot):
    # A NameError in paintEvent takes the whole app down the first time the
    # panel is shown — which is what shipped once.
    panel, stroke, _host = _panel(qtbot)

    assert not panel.grab().isNull()

    stroke.active = True
    stroke.state.cruise.active = True

    assert not panel.grab().isNull()  # and again with every reading lit


def test_the_pace_starts_at_the_slideshows_own_default(qtbot):
    # It read 0s, which is not a pace at all — the console has to open on the
    # number the slideshow actually uses, whether or not one is running.
    from origenerator.gui.slideshow_pace import PaceOnlyHost, SlideshowPace
    from origenerator.slideshow import DEFAULT_IMAGE_DWELL_MS

    pace = SlideshowPace()
    assert pace.seconds == DEFAULT_IMAGE_DWELL_MS // 1000
    panel = StrokePanel(FakeStroke(), host=PaceOnlyHost(pace))
    qtbot.addWidget(panel)
    assert console_hud(panel._stroke, panel._host).console.advance_interval == pace.seconds


def test_setting_the_pace_with_nothing_playing_is_what_the_next_one_opens_at(qtbot):
    from origenerator.gui.slideshow_pace import PaceOnlyHost, SlideshowPace
    from origenerator.gui.slideshow_view import SlideshowView

    pace = SlideshowPace()
    panel = StrokePanel(FakeStroke(), host=PaceOnlyHost(pace))
    qtbot.addWidget(panel)
    panel.render_console()
    _press(panel, "genau_advance_up")
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


def test_the_readout_shows_the_summed_stroke_while_cruise_has_it(qtbot):
    # Cruise control hands the device several waves summed, and the readout is
    # meant to be the motion rather than a drawing of it — so the bar is the
    # whole stroke's travel and center, and the trace is the sum, not whichever
    # wave happens to be the big one.
    import random

    stroke = FakeStroke()
    live = stroke.state
    live.state.playing = True
    live.cruise.rng = random.Random(4)
    stroke_engine.toggle_cruise_control(live)
    now = 1000.0
    for _ in range(400):
        now += 0.05
        stroke_engine.advance(live, 0.05)
        stroke_engine.tick_cruise_control(live, now)

    dials = wave_stack.dials(live.cruise.stack, live.clock)
    hud = drive_hud(live, active=True)
    assert hud.amplitude == round(dials.travel)
    assert abs(hud.center - dials.center) <= 1
    assert hud.position == round(
        POSITION_MAX * wave_stack.position(live.cruise.stack, live.clock) / 100)
    assert len(set(hud.waveform)) > 20  # a live trace, not a held line
