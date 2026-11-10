from __future__ import annotations

import logging
import threading
import time
from contextlib import ExitStack

from app_support.osr2_hold import PARK, RESUME
from funestra.main_hud import HOLD_VERB
from PyQt6.QtCore import QObject, pyqtSignal

from origenerator import motion_engine
from origenerator.motion_engine import Motion
from origenerator.osr2 import Osr2Broker
from origenerator.running_ahead import ahead_while_playing

logger = logging.getLogger(__name__)

_THE_MOTIONS_OWN_CLOCK_HZ = 40
_TICK_MS = 1000 // _THE_MOTIONS_OWN_CLOCK_HZ
_LOOKAHEAD_MS = 40
_HANDOFF_MS = 300


class _TickThread:
    def __init__(self, tick, interval_s: float, *,
                 now=time.monotonic, sleep=time.sleep):
        self._tick = tick
        self._interval = interval_s
        self._now = now
        self._sleep = sleep
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._run, name="osr2-motion",
                                        daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        due = self._now()
        while not self._stopping.is_set():
            due += self._interval
            now = self._now()
            if due < now - self._interval:
                due = now + self._interval
            delay = due - now
            if delay > 0:
                self._sleep(delay)
            if self._stopping.is_set():
                return
            self._tick()


class Osr2MotionDriver(QObject):
    active_changed = pyqtSignal(bool)

    def __init__(self, broker=None, *, interval_ms: int = _TICK_MS,
                 now_source=time.monotonic, ticker_factory=None, parent=None):
        super().__init__(parent)
        self._broker = broker or Osr2Broker()
        self._state = Motion()
        self._active = False
        self._streaming = False
        self._now = now_source
        self._last_tick = 0.0
        self._glide_until = 0.0
        # The bars are moved on Qt's GUI thread while the clock thread samples the state.
        self._lock = threading.RLock()
        self._interval_s = interval_ms / 1000.0
        self._make_ticker = ticker_factory or _TickThread
        self._ticker = None
        self._running_ahead = ExitStack()
        self._held: str | None = None
        self._frozen = False
        self._asked: str | None = None

    @property
    def active(self) -> bool:
        return self._active

    def set_frozen(self, frozen: bool) -> None:
        self._frozen = frozen
        self._run_the_clock_while_sending()

    def toggle(self) -> bool:
        if self._active:
            self.stop()
        else:
            self.start()
        return self._active

    def start(self) -> None:
        if self._active:
            return
        self._active = True
        self._state.state.playing = True
        self._streaming = False
        logger.info("OSR2 motion engaged: %s", self.status_text())
        self._run_the_clock_while_sending()
        self.active_changed.emit(True)

    def stop(self) -> None:
        if not self._active:
            return
        self._active = False
        self._state.state.playing = False
        self._stop_the_clock()
        self._broker.want(False)
        self._ask_the_broker(PARK)
        logger.info("OSR2 motion released: parked")
        self.active_changed.emit(False)

    def _sending(self) -> bool:
        return self._active and not self._frozen and self._held is None

    @property
    def parked_by_the_pause(self) -> bool:
        return self._active and self._frozen and self._held is None

    def _run_the_clock_while_sending(self) -> None:
        self._broker.want(self._sending())
        if self._sending():
            if self._ticker is None:
                self._hand_the_device_back()
                now = self._now()
                self._last_tick = now
                self._glide_from(now)
                self.poll()
                self._running_ahead.enter_context(ahead_while_playing())
                self._ticker = self._make_ticker(self.poll, self._interval_s)
                self._ticker.start()
        else:
            self._stop_the_clock()
            if self._active:
                self._ask_the_broker(HOLD_VERB[self._held] if self._held else PARK)

    def _ask_the_broker(self, verb: str) -> None:
        if verb != self._asked:
            self._asked = verb
            self._broker.ask(verb)

    def _hand_the_device_back(self) -> None:
        self._asked = None
        self._broker.ask(RESUME)

    def _stop_the_clock(self) -> None:
        ticker, self._ticker = self._ticker, None
        if ticker is not None:
            ticker.stop()
        self._running_ahead.close()

    def poll(self) -> None:
        if not self._sending():
            return
        now = self._now()
        lead_ms = self._lead_for(now)
        with self._lock:
            motion_engine.advance(self._state, now - self._last_tick)
            self._last_tick = now
            motion_engine.tick_learned_motion(self._state, now)
            pos = motion_engine.position_ahead(self._state, lead_ms / 1000.0)
        self._broker.send_position(pos, lead_ms)
        if not self._streaming:
            self._streaming = True
            logger.info("OSR2 motion streaming: first T-code pos=%.0f", pos)

    def _lead_for(self, now: float) -> int:
        left = self._glide_until - now
        if left <= 0:
            return _LOOKAHEAD_MS
        eased = left / (_HANDOFF_MS / 1000.0)
        return round(_LOOKAHEAD_MS + (_HANDOFF_MS - _LOOKAHEAD_MS) * eased)

    @property
    def state(self) -> Motion:
        return self._state

    def adjust_speed(self, delta: int) -> None:
        with self._lock:
            motion_engine.adjust_speed(self._state.state, delta)

    def adjust_amplitude(self, delta: int) -> None:
        with self._lock:
            motion_engine.adjust_amplitude(self._state.state, delta)

    def adjust_center(self, delta: int) -> None:
        with self._lock:
            motion_engine.adjust_center(self._state.state, delta)

    def set_speed(self, value: int) -> None:
        with self._lock:
            motion_engine.set_speed(self._state.state, value)

    def set_amplitude(self, value: int) -> None:
        with self._lock:
            motion_engine.set_amplitude(self._state.state, value)

    def set_center(self, value: int) -> None:
        with self._lock:
            motion_engine.set_center(self._state.state, value)

    def set_max_intensity(self, value: int) -> None:
        with self._lock:
            motion_engine.set_max_intensity(self._state.state, value)

    def cycle_shape(self, step: int = 1) -> None:
        with self._lock:
            motion_engine.cycle_shape(self._state.state, step)

    def settings(self) -> dict:
        with self._lock:
            return motion_engine.settings_of(self._state)

    def take_settings(self, saved) -> None:
        with self._lock:
            motion_engine.take_settings(self._state, saved)

    def toggle_learned(self) -> None:
        with self._lock:
            motion_engine.toggle_learned_motion(self._state)

    def set_learned(self, on: bool) -> None:
        with self._lock:
            if on:
                motion_engine.enable_learned_motion(self._state)
            else:
                motion_engine.disable_learned_motion(self._state)

    @property
    def held(self) -> str | None:
        return self._held

    def hold(self, control: str) -> None:
        self._held = control
        self._run_the_clock_while_sending()

    def release(self) -> None:
        self._held = None
        self._run_the_clock_while_sending()

    def _glide_from(self, now: float) -> None:
        self._glide_until = now + _HANDOFF_MS / 1000.0

    def status_text(self) -> str:
        state = self._state.state
        caption = (f"{self._state.bpm:.0f}/min · {state.shape.value}"
                 f" · travel {state.amplitude} around {state.center}")
        if self._state.learned.active:
            caption += " · human inspired"
        return f"OSR2 · {caption}" if self._active else f"Motion stopped · {caption}"
