from __future__ import annotations

import bisect
import logging
from contextlib import ExitStack
from dataclasses import dataclass, field
from functools import partial

from app_support.funscript import read_actions
from app_support.osr2_hold import PARK, RESUME
from funestra.funscript import Funscript
from funestra.robot_hand import FULL_INTENSITY
from PySide6.QtCore import QObject

from origenerator.config import OUTPUT_PLACES
from origenerator.funscript import funscript_of
from origenerator.osr2 import Osr2Broker
from origenerator.osr2_clock import TickThread
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


@dataclass(frozen=True)
class _Drive:
    player: object
    script: Funscript
    times: list[int] = field(init=False)
    duration_ms: int = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "times", [at for at, _pos in self.script.actions])
        object.__setattr__(self, "duration_ms", self.script.actions[-1][0])

    def folded(self, at_ms: int) -> int:
        return at_ms % self.duration_ms if self.duration_ms > 0 else at_ms

    def next_action_after(self, now_ms: int) -> tuple[int, int]:
        index = bisect.bisect_right(self.times, now_ms)
        if index < len(self.times):
            at = self.times[index]
            return at, max(1, at - now_ms)
        at = self.times[0]
        return at, max(1, self.duration_ms - now_ms + at)


class Osr2Driver(QObject):
    def __init__(self, broker=None, *, interval_ms: int = _POLL_INTERVAL_MS,
                 ticker_factory=None, parent=None):
        super().__init__(parent)
        self._broker = broker or Osr2Broker()
        self._drive: _Drive | None = None
        self._streaming = False
        self.max_intensity = FULL_INTENSITY
        self._interval_s = interval_ms / 1000.0
        self._make_ticker = ticker_factory or partial(TickThread, name="osr2-funscript")
        self._ticker = None
        self._frozen = False
        self._running_ahead = ExitStack()

    def set_frozen(self, frozen: bool) -> None:
        if frozen == self._frozen:
            return
        self._frozen = frozen
        if self._drive is None:
            return
        if frozen:
            self._stop_the_clock()
        self._broker.want(not frozen)
        self._broker.ask(PARK if frozen else RESUME)
        if not frozen:
            self._start_the_clock()

    @property
    def parked_by_the_pause(self) -> bool:
        return self._drive is not None and self._frozen

    def start(self, player, actions: list[dict]) -> None:
        self.stop()
        if not actions:
            return
        self._drive = _Drive(player, Funscript(sorted((int(a["at"]), int(a["pos"]))
                                                      for a in actions)))
        self._streaming = False
        self._broker.want(not self._frozen)
        self._broker.ask(PARK if self._frozen else RESUME)
        self._running_ahead.enter_context(ahead_while_playing())
        if not self._frozen:
            self._start_the_clock()
        logger.info("OSR2 drive engaged: %d actions, %d ms",
                    len(self._drive.times), self._drive.duration_ms)

    def stop(self) -> None:
        if self._drive is None:
            return
        self._stop_the_clock()
        self._running_ahead.close()
        self._drive = None
        self._broker.want(False)
        if not self._frozen:
            self._broker.ask(PARK)
        logger.info("OSR2 drive released: parked")

    def _start_the_clock(self) -> None:
        self._ticker = self._make_ticker(self.poll, self._interval_s)
        self._ticker.start()

    def _stop_the_clock(self) -> None:
        ticker, self._ticker = self._ticker, None
        if ticker is not None:
            ticker.stop()

    @property
    def active(self) -> bool:
        return self._drive is not None

    def trace(self, count: int, seconds: float) -> tuple[float, ...]:
        drive = self._drive
        if drive is None or count <= 0:
            return ()
        now = int(drive.player.position())
        step = seconds * 1000 / max(1, count - 1)
        return tuple(drive.script.paced_position_at(drive.folded(now + round(i * step)), 1.0,
                                                    max_intensity=self.max_intensity) / 100
                     for i in range(count))

    def poll(self) -> None:
        drive = self._drive
        if drive is None or self._frozen:
            return
        now_ms = drive.folded(int(drive.player.position()))
        at, interval = drive.next_action_after(now_ms)
        pos = round(drive.script.paced_position_at(at, 1.0, max_intensity=self.max_intensity))
        self._broker.send_position(pos, interval)
        if not self._streaming:
            self._streaming = True
            logger.info("OSR2 drive streaming: first T-code pos=%d interval=%d "
                        "(playhead %d ms)", pos, interval, now_ms)
