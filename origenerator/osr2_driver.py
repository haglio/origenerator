from __future__ import annotations

import logging
from contextlib import ExitStack

from app_support.funscript import read_actions
from app_support.osr2_hold import PARK, RESUME
from funestra.funscript import Funscript
from funestra.robot_hand import FULL_INTENSITY
from PyQt6.QtCore import QObject, QTimer

from origenerator.config import OUTPUT_PLACES
from origenerator.funscript import funscript_of
from origenerator.osr2 import Osr2Broker
from origenerator.running_ahead import ahead_while_playing

logger = logging.getLogger(__name__)

_POLL_INTERVAL_MS = 50


def drive_target_for(video_path, player):
    if video_path is None:
        return None
    actions = read_actions(funscript_of(video_path, places=OUTPUT_PLACES))
    if not actions:
        return None
    return video_path, player, actions


class Osr2Driver(QObject):
    def __init__(self, broker=None, *, interval_ms: int = _POLL_INTERVAL_MS, parent=None):
        super().__init__(parent)
        self._broker = broker or Osr2Broker()
        self._player = None
        self._script: Funscript | None = None
        self._duration_ms = 0
        self._streaming = False
        self.max_intensity = FULL_INTENSITY
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.poll)
        self._frozen = False
        self._running_ahead = ExitStack()

    def set_frozen(self, frozen: bool) -> None:
        if frozen == self._frozen:
            return
        self._frozen = frozen
        if self._player is not None:
            self._broker.want(not frozen)
            self._broker.ask(PARK if frozen else RESUME)

    @property
    def parked_by_the_pause(self) -> bool:
        return self._player is not None and self._frozen

    def start(self, player, actions: list[dict]) -> None:
        self.stop()
        if not actions:
            return
        self._player = player
        self._script = Funscript(sorted((int(a["at"]), int(a["pos"])) for a in actions))
        self._duration_ms = self._script.actions[-1][0]
        self._streaming = False
        self._broker.want(not self._frozen)
        self._broker.ask(PARK if self._frozen else RESUME)
        self._running_ahead.enter_context(ahead_while_playing())
        self._timer.start()
        logger.info("OSR2 drive engaged: %d actions, %d ms",
                    len(self._script.actions), self._duration_ms)

    def stop(self) -> None:
        if self._player is None:
            return
        self._timer.stop()
        self._running_ahead.close()
        self._player = None
        self._script = None
        self._duration_ms = 0
        self._broker.want(False)
        if not self._frozen:
            self._broker.ask(PARK)
        logger.info("OSR2 drive released: parked")

    @property
    def active(self) -> bool:
        return self._player is not None

    def trace(self, count: int, seconds: float) -> tuple[float, ...]:
        if self._script is None or self._player is None or count <= 0:
            return ()
        now = int(self._player.position())
        step = seconds * 1000 / max(1, count - 1)
        return tuple(self._script.paced_position_at(self._folded(now + round(i * step)), 1.0,
                                                    max_intensity=self.max_intensity) / 100
                     for i in range(count))

    def _folded(self, at_ms: int) -> int:
        return at_ms % self._duration_ms if self._duration_ms > 0 else at_ms

    def poll(self) -> None:
        player = self._player
        if player is None or self._frozen:
            return
        now_ms = self._folded(int(player.position()))
        pos, interval = self._next_target(now_ms)
        self._broker.send_position(pos, interval)
        if not self._streaming:
            self._streaming = True
            logger.info("OSR2 drive streaming: first T-code pos=%d interval=%d "
                        "(playhead %d ms)", pos, interval, now_ms)

    def _next_target(self, now_ms: int) -> tuple[int, int]:
        actions = self._script.actions
        for at, _pos in actions:
            if at > now_ms:
                return self._aimed_at(at), max(1, at - now_ms)
        at = actions[0][0]
        return self._aimed_at(at), max(1, self._duration_ms - now_ms + at)

    def _aimed_at(self, at_ms: int) -> int:
        return round(self._script.paced_position_at(at_ms, 1.0, max_intensity=self.max_intensity))
