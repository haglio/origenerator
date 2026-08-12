"""StrokePanel — genau's drive readout copied: marks step, bands set, power toggles."""

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QMouseEvent

from origenerator.gui import stroke_panel
from origenerator.gui.stroke_panel import _PAD, StrokePanel
from origenerator.stroke_engine import StrokeState


class FakeStroke:
    """Records what the panel asks of the driver, over a real StrokeState."""

    def __init__(self):
        self.active = False
        self.state = StrokeState()
        self.calls = []

    def toggle(self):
        self.active = not self.active
        self.calls.append(("toggle", self.active))
        return self.active

    def adjust_speed(self, delta):
        self.calls.append(("adjust_speed", delta))

    def adjust_amplitude(self, delta):
        self.calls.append(("adjust_amplitude", delta))

    def adjust_center(self, delta):
        self.calls.append(("adjust_center", delta))

    def set_speed(self, value):
        self.calls.append(("set_speed", value))

    def set_amplitude(self, value):
        self.calls.append(("set_amplitude", value))

    def set_center(self, value):
        self.calls.append(("set_center", value))


def _press_at(panel, x, y):
    panel.mousePressEvent(QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPointF(x, y),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    ))


def _center_of(rect):
    x, y, w, h = rect
    return x + w // 2, y + h // 2


def _control_rect(state, action, active=False):
    for control in stroke_panel.controls(_PAD, _PAD, state, active):
        if control.action == action:
            return control.rect
    raise AssertionError(f"no control named {action}")


def _track_rect(state, axis):
    for track in stroke_panel.tracks(_PAD, _PAD, state):
        if track.axis == axis:
            return track
    raise AssertionError(f"no track named {axis}")


def test_the_marks_step_their_axes(qtbot):
    stroke = FakeStroke()
    panel = StrokePanel(stroke)
    qtbot.addWidget(panel)
    for action, expected in (
        ("speed_up", ("adjust_speed", 5)),
        ("speed_down", ("adjust_speed", -5)),
        ("amp_up", ("adjust_amplitude", 10)),
        ("amp_down", ("adjust_amplitude", -10)),
        ("center_up", ("adjust_center", 5)),
        ("center_down", ("adjust_center", -5)),
    ):
        _press_at(panel, *_center_of(_control_rect(stroke.state, action)))
        assert stroke.calls[-1] == expected


def test_the_power_square_toggles_the_stroke(qtbot):
    stroke = FakeStroke()
    panel = StrokePanel(stroke)
    qtbot.addWidget(panel)
    _press_at(panel, *_center_of(_control_rect(stroke.state, "power")))
    assert stroke.calls == [("toggle", True)]


def test_a_press_on_the_speed_bar_sets_the_rate_drawn_under_it(qtbot):
    stroke = FakeStroke()
    panel = StrokePanel(stroke)
    qtbot.addWidget(panel)
    track = _track_rect(stroke.state, stroke_panel.SPEED)
    x, y, w, h = track.rect
    _press_at(panel, x + (w - 1) * 3 // 4, y + h // 2)  # three quarters along
    name, value = stroke.calls[-1]
    assert name == "set_speed"
    assert 70 <= value <= 80


def test_a_press_in_the_trace_sets_the_center_at_that_height(qtbot):
    stroke = FakeStroke()
    panel = StrokePanel(stroke)
    qtbot.addWidget(panel)
    track = _track_rect(stroke.state, stroke_panel.CENTER)
    x, y, w, h = track.rect
    _press_at(panel, x + w // 2, y)  # the very top of the trace
    assert stroke.calls[-1] == ("set_center", 100)


def test_a_press_on_the_amplitude_bar_sets_the_reach_to_that_height(qtbot):
    stroke = FakeStroke()
    stroke.state.amplitude = 50  # center stays 50; pressing the top asks for 100
    panel = StrokePanel(stroke)
    qtbot.addWidget(panel)
    track = _track_rect(stroke.state, stroke_panel.AMPLITUDE)
    x, y, w, h = track.rect
    _press_at(panel, x + w // 2, y)  # the top of the bar: full reach
    assert stroke.calls[-1] == ("set_amplitude", 100)


def test_the_panel_is_genaus_block_size(qtbot):
    # The copy keeps genau's drive_hud geometry — same block, plus the slab pad.
    panel = StrokePanel(FakeStroke())
    qtbot.addWidget(panel)
    assert panel.width() == stroke_panel.SECTION_W + 2 * _PAD
    assert panel.height() == stroke_panel.SECTION_H + 2 * _PAD
