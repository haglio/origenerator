"""Osr2StrokeDriver — broker etiquette and the self-generated position stream."""

import threading
import time

from origenerator import stroke_engine
from origenerator.gui.osr2_stroke_driver import (
    _HANDOFF_MS, _LOOKAHEAD_MS, Osr2StrokeDriver, _TickThread,
)


class FakeBroker:
    def __init__(self):
        self.positions = []
        self.parked = 0
        self.paused = 0
        self.restored = 0

    def send_position(self, pos, interval_ms):
        self.positions.append((pos, interval_ms))

    def park(self):
        self.parked += 1

    def pause_genau(self):
        self.paused += 1

    def restore_genau(self):
        self.restored += 1


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class FakeTicker:
    """Stands in for the clock thread: the test ticks by calling poll itself."""

    def __init__(self, tick, interval_s):
        self.tick = tick
        self.interval_s = interval_s
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1


def _driver(qtbot):
    broker, clock = FakeBroker(), FakeClock()
    tickers = []

    def factory(tick, interval_s):
        tickers.append(FakeTicker(tick, interval_s))
        return tickers[-1]

    driver = Osr2StrokeDriver(broker, now_source=clock, ticker_factory=factory)
    driver.tickers = tickers
    return driver, broker, clock


def test_starting_takes_the_device_and_pauses_genau(qtbot):
    driver, broker, _clock = _driver(qtbot)
    handovers = []
    driver.active_changed.connect(handovers.append)
    assert driver.toggle() is True
    assert driver.active
    assert broker.paused == 1
    assert broker.parked == 0  # taking the device isn't parking it
    assert handovers == [True]  # announced, so the funscript drive stands down
    assert driver.tickers[0].started == 1  # and the clock is running


def test_each_command_aims_as_far_ahead_as_the_time_it_gives(qtbot):
    # Aimed at where the stroke already is, the device can only ever chase: by
    # the time the command lands the stroke has moved on. Every command names
    # the place the stroke will have reached when its own interval runs out —
    # through the takeover glide as much as after it, so being given longer
    # means being sent further rather than being left behind.
    driver, broker, clock = _driver(qtbot)
    driver.start()
    for step in (0.025, 0.025, 0.5, 0.025):
        clock.t += step
        driver.poll()
        pos, interval = broker.positions[-1]
        assert pos == stroke_engine.position_ahead(driver.state, interval / 1000)
    assert interval == _LOOKAHEAD_MS  # the last one, well past the glide
    assert pos > stroke_engine.position(driver.state)  # ahead, on the way up


def test_the_takeover_keeps_streaming_and_eases_its_interval_out(qtbot):
    # The device is parked wherever the last thing to hold it left it, so the
    # first target can be the length of the axis away. Holding the stream back
    # for the glide is what turned the seam into a slam: the device sat still
    # while the stroke ran on, then had to cover all of it in one tick.
    driver, broker, clock = _driver(qtbot)
    driver.start()
    assert broker.positions[0][1] == _HANDOFF_MS  # the whole glide to arrive
    for _ in range(4):
        clock.t += 0.025
        driver.poll()
    intervals = [i for _pos, i in broker.positions]
    assert intervals == sorted(intervals, reverse=True)  # eases out, never steps
    assert all(i >= _LOOKAHEAD_MS for i in intervals)
    clock.t += 0.5
    driver.poll()
    assert broker.positions[-1][1] == _LOOKAHEAD_MS  # glide over: ordinary again


def test_a_late_tick_still_sends_over_the_lookahead(qtbot):
    # The interval is what the device is *given*, not what just elapsed: handing
    # it the gap that already went by asks it to spend a long stall crawling and
    # then sprint when the next tick lands early.
    driver, broker, clock = _driver(qtbot)
    driver.start()
    clock.t += 0.5
    for late_by in (0.025, 0.2, 0.031):
        clock.t += late_by
        driver.poll()
    assert [i for _pos, i in broker.positions[-3:]] == [_LOOKAHEAD_MS] * 3
    assert all(0.0 <= pos <= 100.0 for pos, _i in broker.positions)


def test_stopping_parks_the_device_and_restores_genau(qtbot):
    driver, broker, _clock = _driver(qtbot)
    driver.start()
    handovers = []
    driver.active_changed.connect(handovers.append)
    assert driver.toggle() is False
    assert driver.tickers[0].stopped == 1  # the clock is waited out...
    assert broker.parked == 1              # ...before the park, so it sticks
    assert broker.restored == 1
    assert handovers == [False]  # announced, so the funscript drive may re-aim
    driver.stop()  # already stopped: releasing again must not park twice
    assert broker.parked == 1
    assert handovers == [False]  # and a redundant stop announces nothing


def test_the_clock_runs_off_the_gui_thread(qtbot):
    # A slideshow decodes a full-size image on the GUI thread every few seconds;
    # a tick living there is starved for as long as that takes, and the device
    # feels it as a freeze and then a lunge.
    seen = []
    ticker = _TickThread(lambda: seen.append(threading.current_thread()), 0.001)
    ticker.start()
    deadline = time.monotonic() + 2.0
    while not seen and time.monotonic() < deadline:
        time.sleep(0.01)
    ticker.stop()
    assert seen, "the clock never ticked"
    assert all(t is not threading.main_thread() for t in seen)


def test_a_long_stall_picks_the_beat_up_from_now_instead_of_firing_a_backlog():
    # A machine that suspends (or a laptop lid) comes back seconds behind. The
    # loop owes those ticks to nobody: firing them all at once would fling the
    # device through a burst of stale positions.
    stalls, clock, ticks = [1.0], [0.0], []

    def now():
        return clock[0]

    def sleep(seconds):
        clock[0] += seconds + (stalls.pop(0) if stalls else 0.0)

    ticker = None

    def tick():
        ticks.append(clock[0])
        if len(ticks) >= 4:
            ticker.stop()

    ticker = _TickThread(tick, 0.025, now=now, sleep=sleep)
    ticker._run()  # the loop itself, on this thread, against a scripted clock
    gaps = [b - a for a, b in zip(ticks, ticks[1:])]
    assert gaps and all(abs(g - 0.025) < 1e-9 for g in gaps)


def test_the_knobs_shape_the_status_line(qtbot):
    driver, _broker, _clock = _driver(qtbot)
    driver.start()
    driver.adjust_speed(50)          # dial to the top: 200 strokes/min
    driver.adjust_amplitude(-40)     # 100 -> 60
    driver.adjust_center(-100)       # slides down to the sweep's floor (30)
    driver.cycle_shape()             # sine -> triangle
    assert driver.status_text() == "OSR2 · 200/min · triangle · travel 60 around 30"


def test_the_status_line_reads_off_but_keeps_the_knobs_while_stopped(qtbot):
    # The slideshow shows this line before the stroke ever starts, so the knobs
    # must be readable (and tunable) while the device is still parked.
    driver, _broker, _clock = _driver(qtbot)
    driver.adjust_speed(50)
    assert driver.status_text() == "OSR2 off · 200/min · sine · travel 100 around 50"
