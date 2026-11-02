from __future__ import annotations

from origenerator import motion_engine
from origenerator.motion_engine import Motion


class FakeMotion:
    def __init__(self):
        self.state = Motion()
        self.active = False
        self.calls = []

    def toggle(self):
        self.active = not self.active
        self.calls.append(("toggle", self.active))
        return self.active

    def toggle_learned(self):
        self.calls.append("learned")
        self.state.learned.active = not self.state.learned.active

    def cycle_shape(self):
        self.calls.append("shape")
        motion_engine.cycle_shape(self.state.state)

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

    held = None
    parked_by_the_pause = False

    def hold(self, control):
        self.calls.append(("hold", control))

    def release(self):
        self.calls.append("release")

    def set_max_intensity(self, level):
        self.calls.append(("max_intensity", level))
        self.state.state.max_intensity = level
