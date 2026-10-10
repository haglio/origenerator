"""A stand-in for the OSR2 motion a console acts on.

Shared because three surfaces press the same console verbs -- the panel in the
main window's foot, a show's own panel, and the keys -- and each was growing its
own half-driver to be pressed against.
"""
from __future__ import annotations

from origenerator import motion_engine
from origenerator.motion_engine import Motion


class FakeMotion:
    """Stands in for the driver: records what the console asked it to do."""

    def __init__(self):
        self.state = Motion()
        self.active = False
        self.calls = []

    def toggle(self):
        self.active = not self.active
        self.calls.append(("toggle", self.active))
        return self.active

    def toggle_cruise(self):
        self.calls.append("cruise")
        self.state.cruise.active = not self.state.cruise.active

    def toggle_learned(self):
        self.calls.append("learned")
        self.state.learned.active = not self.state.learned.active

    def cycle_shape(self):
        self.calls.append("shape")
        motion_engine.cycle_shape(self.state.state)

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

    held_at = None

    def hold(self, center):
        self.calls.append(("hold", center))

    def release(self):
        self.calls.append("release")

    def set_max_intensity(self, level):
        self.calls.append(("max_intensity", level))
        self.state.state.max_intensity = level
