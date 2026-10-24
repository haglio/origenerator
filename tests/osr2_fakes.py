from __future__ import annotations

from app_support.osr2_hold import PARK


class FakeBroker:
    def __init__(self):
        self.positions = []
        self.asked = []

    def send_position(self, pos, interval_ms):
        self.positions.append((pos, interval_ms))

    def ask(self, verb):
        self.asked.append(verb)

    @property
    def parked(self):
        return self.asked.count(PARK)
