"""StrokePanel — the marks it offers and what a press on one does.

Where the parts sit is player_core's (tested there); what this adds is the row
genau keeps in Fun Time's console — cruise control and the waveform — and the
wiring from a press to the driver.
"""

from origenerator.gui.stroke_panel import (
    CRUISE, PANEL_H, PANEL_W, SHAPE, StrokePanel, controls, tracks,
)
from origenerator.stroke_engine import Stroke
from player_core import drive_layout


class FakeStroke:
    """Stands in for the driver: records what the panel asked it to do."""

    def __init__(self):
        self.state = Stroke()
        self.active = False
        self.calls = []

    def toggle_cruise(self):
        self.calls.append("cruise")
        self.state.cruise.active = not self.state.cruise.active

    def cycle_shape(self):
        self.calls.append("shape")

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


def _press(panel, rect):
    x, y, w, h = rect
    panel._press_at(x + w // 2, y + h // 2)


def test_the_panel_carries_the_shared_marks_and_its_own_row():
    stroke = FakeStroke()
    actions = [c.action for c in controls(0, 0, stroke.state, False)]
    # genau's own six, from player_core, with the bare verbs this app calls
    for expected in ("speed_down", "speed_up", "amplitude_up", "amplitude_down",
                     "center_up", "center_down"):
        assert expected in actions
    # ...and the two Fun Time keeps in its console, which there is none of here
    assert CRUISE in actions and SHAPE in actions


def test_the_on_off_switch_is_not_on_the_panel():
    # It is a button in the window's toolbar now, and this panel is what appears
    # once that button is pressed.
    assert "power" not in [c.action for c in controls(0, 0, FakeStroke().state, True)]


def test_the_panel_is_tall_enough_for_the_row_it_added():
    assert PANEL_W >= drive_layout.SECTION_W
    assert PANEL_H > drive_layout.SECTION_H + drive_layout.CONTROL_SIZE


def test_the_cruise_mark_is_lit_only_while_cruise_has_the_dials(qtbot):
    stroke = FakeStroke()
    off = {c.action: c for c in controls(0, 0, stroke.state, True)}[CRUISE]
    assert off.dim  # unlit
    stroke.state.cruise.active = True
    on = {c.action: c for c in controls(0, 0, stroke.state, True)}[CRUISE]
    assert not on.dim


def test_pressing_a_mark_asks_the_driver_for_it(qtbot):
    stroke = FakeStroke()
    panel = StrokePanel(stroke)
    qtbot.addWidget(panel)
    marks = {c.action: c for c in controls(10, 10, stroke.state, False)}
    _press(panel, marks[CRUISE].rect)
    _press(panel, marks[SHAPE].rect)
    _press(panel, marks["speed_up"].rect)
    assert stroke.calls == ["cruise", "shape", ("speed", 5)]


def test_pressing_a_band_sets_the_level_drawn_under_the_pointer(qtbot):
    stroke = FakeStroke()
    panel = StrokePanel(stroke)
    qtbot.addWidget(panel)
    speed = {t.axis: t for t in tracks(10, 10, stroke.state)}[drive_layout.SPEED]
    x, y, w, _h = speed.rect
    panel._press_at(x + w - 1, y)
    assert stroke.calls == [("set_speed", 100)]


def test_the_panel_actually_paints(qtbot):
    # Nothing else here paints, and a NameError in paintEvent takes the whole app
    # down the first time the panel is shown — which is what shipped.
    stroke = FakeStroke()
    panel = StrokePanel(stroke)
    qtbot.addWidget(panel)
    panel.grab()
    stroke.active = True
    stroke.state.cruise.active = True
    panel.grab()  # and again in every state the marks are drawn differently in
