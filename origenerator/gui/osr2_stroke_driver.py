"""Drive the OSR2 from a self-generated stroke — no video, no funscript.

The counterpart to :class:`~origenerator.gui.osr2_driver.Osr2Driver` for stills:
where that one follows a playing video's script, this one *is* the motion
source, advancing a :class:`~origenerator.stroke_engine.Stroke` on a clock
of its own and streaming each sampled position as T-code. Same broker etiquette,
too: it pauses genau while it drives, and parks the device + restores genau when
it stops. The gallery owns the one instance, app-global — every surface (the main
window, the fullscreen show) drives it through the shared
key cluster in :mod:`origenerator.gui.stroke_hud`, and the stroke outlives any
of them: closing a view leaves the device running until Space (or Esc in the
gallery) stops it.

Two things make the motion read as motion rather than as lurching, and both were
missing while this drove off a GUI-thread timer aimed at the present:

* **Its own clock.** A slideshow decodes a full-size image (and its neighbors)
  on the GUI thread every few seconds, and every such stall starves a timer
  living there. The device feels that as a freeze followed by a lunge to catch
  up. The clock here answers to nothing but the wall.
* **Aiming ahead.** Each command says *be at this place in this long*, so the
  place has to be one the stroke is due to reach when the time is up. Aimed at
  where the stroke already is, the device can only chase, and every wobble in
  the tick spacing becomes a stall and then a sprint.
"""

from __future__ import annotations

import logging
import threading
import time

from PyQt6.QtCore import QObject, pyqtSignal

from origenerator import stroke_engine
from origenerator.config import (
    OSR2_BROKER_HOST, OSR2_GENAU_ENABLED_FILE, OSR2_TCODE_UDP_PORT,
)
from origenerator.osr2 import Osr2Broker
from origenerator.stroke_engine import Stroke

logger = logging.getLogger(__name__)

_TICK_MS = 25  # the stroke's own clock — 40 Hz, a beat under genau's own loop
# How far ahead of now each command aims, and so how long the device is given to
# get there. Comfortably more than a tick, so a tick that runs a little late
# still finds the device short of its target and simply re-aims it — under a
# tick and the device arrives early, stands still, then sprints for the next.
_LOOKAHEAD_MS = 40
# The device is parked wherever the last thing to hold it left it, and the
# stroke's first target can be the length of the axis away. Every command inside
# this window is given a longer interval, easing out to the ordinary lookahead
# as the window closes, so the seam is a movement rather than a slam. (Genau's
# HandoffGlide, minus its cliff edge at the end.)
_HANDOFF_MS = 300


class _TickThread:
    """The stroke's clock, off the GUI thread.

    A plain sleeping loop rather than a ``QTimer``: it needs the wall clock, the
    stroke state and a datagram socket, none of which belong to Qt, and living
    outside the GUI thread is the whole point — see this module's docstring.
    """

    def __init__(self, tick, interval_s: float, *,
                 now=time.monotonic, sleep=time.sleep):
        self._tick = tick
        self._interval = interval_s
        self._now = now
        self._sleep = sleep
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._run, name="osr2-stroke",
                                        daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        """Ask the loop to finish and wait for it, so nothing is still in flight
        when the caller goes on to park the device."""
        self._stopping.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        due = self._now()
        while not self._stopping.is_set():
            due += self._interval
            now = self._now()
            if due < now - self._interval:
                # A long way behind — a machine suspend, say. Those ticks are
                # owed to nobody: firing the backlog would fling the device
                # through a burst of stale positions. Pick the beat up here.
                due = now + self._interval
            delay = due - now
            if delay > 0:
                self._sleep(delay)
            if self._stopping.is_set():
                return
            self._tick()


class Osr2StrokeDriver(QObject):
    # The device changed hands: the funscript reconcile stands down while the
    # stroke holds it, and every surface's caption follows along.
    active_changed = pyqtSignal(bool)

    def __init__(self, broker=None, *, interval_ms: int = _TICK_MS,
                 now_source=time.monotonic, ticker_factory=None, parent=None):
        super().__init__(parent)
        self._broker = broker or Osr2Broker(
            OSR2_BROKER_HOST, OSR2_TCODE_UDP_PORT,
            genau_enabled_file=OSR2_GENAU_ENABLED_FILE,
        )
        self._state = Stroke()
        self._active = False
        self._streaming = False  # a one-shot "first T-code sent" log per start
        self._now = now_source
        self._last_tick = 0.0
        self._glide_until = 0.0  # takeover: intervals ease out until this passes
        # The knobs are turned on the GUI thread while the clock samples the
        # state on its own, so both go through this.
        self._lock = threading.RLock()
        self._interval_s = interval_ms / 1000.0
        self._make_ticker = ticker_factory or _TickThread
        self._ticker = None

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
        self._state.state.playing = True
        self._streaming = False
        now = self._now()
        self._last_tick = now
        self._glide_until = now + _HANDOFF_MS / 1000.0
        self._broker.pause_genau()
        logger.info("OSR2 stroke engaged: %s", self.status_text())
        self.poll()  # move on the keypress, not a tick later
        self._ticker = self._make_ticker(self.poll, self._interval_s)
        self._ticker.start()
        self.active_changed.emit(True)

    def stop(self) -> None:
        """Release the device: stop streaming, park it, and restore genau."""
        if not self._active:
            return
        self._active = False
        self._state.state.playing = False
        ticker, self._ticker = self._ticker, None
        if ticker is not None:
            ticker.stop()  # waits, so no tick can land after the park below
        self._broker.park()
        self._broker.restore_genau()
        logger.info("OSR2 stroke released: parked, genau restored")
        self.active_changed.emit(False)

    def poll(self) -> None:
        """One tick: carry the phase up to now, then name where the stroke will
        be when the time this command is given runs out.

        The place and the time are the same number twice — aim as far ahead as
        the device is allowed to take. That is what keeps it on the stroke
        rather than behind it, through the glide as much as after it: given
        longer, it is also sent further, so it arrives where the stroke has got
        to instead of where the stroke was when the command left.
        """
        now = self._now()
        lead_ms = self._lead_for(now)
        with self._lock:
            # Cruise control moves the dials before the phase is sampled, so a
            # tick sends the stroke it just asked for rather than the one before.
            stroke_engine.tick_cruise_control(
                self._state.state, self._state.cruise, now)
            stroke_engine.advance(self._state, now - self._last_tick)
            self._last_tick = now
            pos = stroke_engine.position_ahead(self._state, lead_ms / 1000.0)
        self._broker.send_position(pos, lead_ms)
        if not self._streaming:
            self._streaming = True
            logger.info("OSR2 stroke streaming: first T-code pos=%.0f", pos)

    def _lead_for(self, now: float) -> int:
        """How far ahead this command aims, and so how long the device is given
        to get there: the ordinary lookahead, stretched while the takeover glide
        is still running and easing back to it as the glide closes — so there's
        no step at the moment it ends."""
        left = self._glide_until - now
        if left <= 0:
            return _LOOKAHEAD_MS
        eased = left / (_HANDOFF_MS / 1000.0)
        return round(_LOOKAHEAD_MS + (_HANDOFF_MS - _LOOKAHEAD_MS) * eased)

    # --- the knobs the keys and the drive panel turn -----------------------

    @property
    def state(self) -> Stroke:
        """The live stroke, for the drive panel to draw. Read-only by
        convention — the setters below are how it changes."""
        return self._state

    def adjust_speed(self, delta: int) -> None:
        with self._lock:
            stroke_engine.adjust_speed(self._state.state, delta)

    def adjust_amplitude(self, delta: int) -> None:
        with self._lock:
            stroke_engine.adjust_amplitude(self._state.state, delta)

    def adjust_center(self, delta: int) -> None:
        with self._lock:
            stroke_engine.adjust_center(self._state.state, delta)

    def set_speed(self, value: int) -> None:
        with self._lock:
            stroke_engine.set_speed(self._state.state, value)

    def set_amplitude(self, value: int) -> None:
        with self._lock:
            stroke_engine.set_amplitude(self._state.state, value)

    def set_center(self, value: int) -> None:
        with self._lock:
            stroke_engine.set_center(self._state.state, value)

    def cycle_shape(self, step: int = 1) -> None:
        with self._lock:
            stroke_engine.cycle_shape(self._state.state, step)

    def toggle_cruise(self) -> None:
        """Hands off: cruise control varies amplitude, centre, speed and shape
        for you (genau's ``/``). It only moves the dials while the stroke is
        actually running, so arming it against a parked device changes nothing
        until the device is taken."""
        with self._lock:
            stroke_engine.toggle_cruise_control(self._state.cruise)

    @property
    def cruising(self) -> bool:
        return self._state.cruise.active

    def quarter_offset(self) -> None:
        r"""Shift the stroke a quarter cycle (genau's ``\``)."""
        with self._lock:
            stroke_engine.quarter_offset(self._state)

    def status_text(self) -> str:
        """One line of what the device is (or would be) doing, for the
        slideshow's standing caption — the knobs read the same either way, so
        the stroke can be tuned before it's started."""
        state = self._state.state
        knobs = (f"{self._state.bpm:.0f}/min · {state.shape.value}"
                 f" · travel {state.amplitude} around {state.center}")
        if self._state.cruise.active:
            knobs += " · cruise"
        return f"OSR2 · {knobs}" if self._active else f"OSR2 off · {knobs}"
