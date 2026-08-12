"""Drive the OSR2 from a self-generated stroke — no video, no funscript.

The counterpart to :class:`~origenerator.gui.osr2_driver.Osr2Driver` for stills:
where that one follows a playing video's script, this one *is* the motion
source, advancing a :class:`~origenerator.stroke_engine.StrokeState` on a timer
and streaming each sampled position as T-code. Same broker etiquette, too: it
pauses genau while it drives, and parks the device + restores genau when it
stops. The gallery owns the one instance, app-global — every surface (the main
window, the fullscreen viewer, both slideshows) drives it through the shared
key cluster in :mod:`origenerator.gui.stroke_hud`, and the stroke outlives any
of them: closing a view leaves the device running until Space (or Esc in the
gallery) stops it.
"""

from __future__ import annotations

import logging
import time

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from origenerator import stroke_engine
from origenerator.config import (
    OSR2_BROKER_HOST, OSR2_GENAU_ENABLED_FILE, OSR2_TCODE_UDP_PORT,
)
from origenerator.osr2 import Osr2Broker
from origenerator.stroke_engine import StrokeState

logger = logging.getLogger(__name__)

_TICK_MS = 33  # ~30 Hz — the cadence genau streams at


class Osr2StrokeDriver(QObject):
    # The device changed hands: the funscript reconcile stands down while the
    # stroke holds it, and every surface's caption follows along.
    active_changed = pyqtSignal(bool)

    def __init__(self, broker=None, *, interval_ms: int = _TICK_MS,
                 now_source=time.monotonic, parent=None):
        super().__init__(parent)
        self._broker = broker or Osr2Broker(
            OSR2_BROKER_HOST, OSR2_TCODE_UDP_PORT,
            genau_enabled_file=OSR2_GENAU_ENABLED_FILE,
        )
        self._state = StrokeState()
        self._active = False
        self._interval_ms = interval_ms
        self._now = now_source
        self._last_tick = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.poll)

    @property
    def active(self) -> bool:
        return self._active

    def toggle(self) -> bool:
        """Start or stop driving; returns whether the stroke is now running."""
        if self._active:
            self.stop()
        else:
            self.start()
        return self._active

    def start(self) -> None:
        """Take the device: pause genau and start streaming the stroke."""
        if self._active:
            return
        self._active = True
        self._last_tick = self._now()
        self._broker.pause_genau()
        self._timer.start()
        logger.info("OSR2 stroke engaged: %s", self.status_text())
        self.active_changed.emit(True)

    def stop(self) -> None:
        """Release the device: stop streaming, park it, and restore genau."""
        if not self._active:
            return
        self._active = False
        self._timer.stop()
        self._broker.park()
        self._broker.restore_genau()
        logger.info("OSR2 stroke released: parked, genau restored")
        self.active_changed.emit(False)

    def poll(self) -> None:
        """One tick: advance the phase by real elapsed time and send the position."""
        now = self._now()
        stroke_engine.advance(self._state, now - self._last_tick)
        self._last_tick = now
        self._broker.send_position(
            stroke_engine.position(self._state), self._interval_ms
        )

    # --- the knobs the slideshow's keys turn -------------------------------

    def adjust_speed(self, delta: int) -> None:
        stroke_engine.adjust_speed(self._state, delta)

    def adjust_amplitude(self, delta: int) -> None:
        stroke_engine.adjust_amplitude(self._state, delta)

    def adjust_center(self, delta: int) -> None:
        stroke_engine.adjust_center(self._state, delta)

    def cycle_shape(self) -> None:
        stroke_engine.cycle_shape(self._state)

    def status_text(self) -> str:
        """One line of what the device is (or would be) doing, for the
        slideshow's standing caption — the knobs read the same either way, so
        the stroke can be tuned before it's started."""
        state = self._state
        knobs = (f"{state.bpm:.0f}/min · {state.shape.value}"
                 f" · travel {state.amplitude} around {state.center}")
        return f"OSR2 · {knobs}" if self._active else f"OSR2 off · {knobs}"
