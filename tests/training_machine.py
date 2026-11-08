from __future__ import annotations

import time
from pathlib import Path


class TrainingMachine:
    def __init__(self, waiting=(), memory=(), held=(False,), claims=(True,)):
        self.waiting = list(waiting)
        self.memory = list(memory)
        self.held = list(held)
        self.claims = list(claims)
        self.unloaded = self.claimed = self.released = 0
        self.slept: list[float] = []

    def graphics_card_held_by_another(self):
        return self.held.pop(0) if len(self.held) > 1 else self.held[0]

    def claim_graphics_card(self):
        self.claimed += 1
        return self.claims.pop(0) if len(self.claims) > 1 else self.claims[0]

    def release_graphics_card(self):
        self.released += 1

    def jobs_waiting(self):
        return self.waiting.pop(0) if len(self.waiting) > 1 else self.waiting[0]

    def unload_comfyui(self):
        self.unloaded += 1

    def graphics_card_memory_mib(self):
        return self.memory.pop(0) if len(self.memory) > 1 else self.memory[0]

    def sleep(self, seconds):
        self.slept.append(seconds)


class AComfyUIJobComesOnceAStateIsSaved(TrainingMachine):
    def __init__(self, state: Path):
        super().__init__(waiting=[0], memory=[100])
        self._state, self._came = state, False

    def jobs_waiting(self):
        if self._came or not self._state.is_dir():
            return 0
        self._came = True
        return 2

    def sleep(self, seconds):
        super().sleep(seconds)
        time.sleep(0.005)
