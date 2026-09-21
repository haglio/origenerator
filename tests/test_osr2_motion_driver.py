"""Osr2MotionDriver — broker etiquette and the self-generated position stream."""
from __future__ import annotations

import threading
import time

from player_core.learned_model import LearnedModel, Phrase, classify
from player_core.robot_hand import PARK_CENTER, RETRACT_CENTER

from origenerator import motion_engine
from origenerator.osr2_motion_driver import (
    _HANDOFF_MS,
    _LOOKAHEAD_MS,
    Osr2MotionDriver,
    _TickThread,
)


class FakeBroker:
    def __init__(self):
        self.positions = []
        self.parked = 0

    def send_position(self, pos, interval_ms):
        self.positions.append((pos, interval_ms))

    def park(self):
        self.parked += 1


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

    driver = Osr2MotionDriver(broker, now_source=clock, ticker_factory=factory)
    driver.tickers = tickers
    return driver, broker, clock


def test_starting_takes_the_device(qtbot):
    driver, broker, _clock = _driver(qtbot)
    handovers = []
    driver.active_changed.connect(handovers.append)
    assert driver.toggle() is True
    assert driver.active
    assert broker.parked == 0  # taking the device isn't parking it
    assert handovers == [True]  # announced, so the funscript drive stands down
    assert driver.tickers[0].started == 1  # and the clock is running


def test_each_command_aims_as_far_ahead_as_the_time_it_gives(qtbot):
    # Aimed at where the motion already is, the device can only ever chase: by
    # the time the command lands the motion has moved on. Every command names
    # the place the motion will have reached when its own interval runs out —
    # through the takeover glide as much as after it, so being given longer
    # means being sent further rather than trailing the motion.
    driver, broker, clock = _driver(qtbot)
    driver.start()
    for step in (0.025, 0.025, 0.5, 0.025):
        clock.t += step
        driver.poll()
        pos, interval = broker.positions[-1]
        assert pos == motion_engine.position_ahead(driver.state, interval / 1000)
    assert interval == _LOOKAHEAD_MS  # the last one, well past the glide
    assert pos > motion_engine.position(driver.state)  # ahead, on the way up


def test_the_takeover_keeps_streaming_and_eases_its_interval_out(qtbot):
    # The device is parked wherever the last thing to hold it left it, so the
    # first target can be the length of the axis away. Holding the stream back
    # for the glide is what turned the seam into a slam: the device sat still
    # while the motion ran on, then had to cover all of it in one tick.
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


def test_stopping_parks_the_device(qtbot):
    driver, broker, _clock = _driver(qtbot)
    driver.start()
    handovers = []
    driver.active_changed.connect(handovers.append)
    assert driver.toggle() is False
    assert driver.tickers[0].stopped == 1  # the clock is waited out...
    assert broker.parked == 1              # ...before the park, so it sticks
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
    # A machine that suspends (or a laptop lid) comes back seconds late. The
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


def test_the_dials_shape_the_status_line(qtbot):
    driver, _broker, _clock = _driver(qtbot)
    driver.start()
    driver.adjust_speed(50)          # dial to the top: 200 cycles/min
    driver.adjust_amplitude(-40)     # 100 -> 60
    driver.adjust_center(-100)       # slides down to the sweep's floor (30)
    driver.cycle_shape()             # sine -> triangle
    assert driver.status_text() == "OSR2 · 200/min · triangle · travel 60 around 30"


def test_the_status_line_says_the_motion_is_stopped_but_keeps_the_dials(qtbot):
    """The dials are readable and tunable before the motion starts.  Stopped is
    all it says: a funscript may have the device meanwhile, and "OSR2 off" read
    as the device -- or the app's control of it -- being off."""
    driver, _broker, _clock = _driver(qtbot)
    driver.adjust_speed(50)
    assert driver.status_text() == (
        "Motion stopped · 200/min · sine · travel 100 around 50")


def test_the_learned_motion_takes_the_motion_over_and_it_is_what_is_streamed(qtbot):
    # Hands off to the scripts: the tick streams where the phrases will have
    # the device when the command's own interval runs out, inside the dials'
    # range -- and cruise control, had it the motion, has let go.

    phrase = Phrase(tuple((500, 80 if i % 2 == 0 else 20) for i in range(16)))
    driver, broker, clock = _driver(qtbot)
    driver.state.learned.model = LearnedModel(
        phrases={classify(phrase): [phrase]}, seen={classify(phrase): 1})
    driver.start()
    driver.toggle_cruise()
    driver.toggle_learned()
    assert driver.state.learned.active and not driver.state.cruise.active
    for _ in range(60):
        clock.t += 0.025
        driver.poll()
        pos, interval = broker.positions[-1]
        assert pos == motion_engine.position_ahead(driver.state, interval / 1000)
    assert all(0.0 <= pos <= 100.0 for pos, _i in broker.positions)
    assert len({round(pos) for pos, _i in broker.positions}) > 5  # it moves
    assert "human inspired" in driver.status_text()
    driver.set_learned(False)
    assert not driver.state.learned.active and not driver.state.learned.times


def test_cruise_control_takes_the_motion_over_and_it_is_what_is_streamed(qtbot):
    # Hands off, the motion is no longer one wave: it is several summed, each
    # with its own speed and its own share of the travel, both on their way
    # somewhere else. What has to stay true is that the tick still sends where
    # that motion will be when the command's own interval runs out.
    driver, broker, clock = _driver(qtbot)
    driver.start()
    driver.toggle_cruise()
    assert driver.state.cruise.active
    assert not driver.state.cruise.stack  # drawn on the next tick, from the dials
    for _ in range(60):
        clock.t += 0.025
        driver.poll()
        pos, interval = broker.positions[-1]
        assert pos == motion_engine.position_ahead(driver.state, interval / 1000)
    assert all(0.0 <= pos <= 100.0 for pos, _i in broker.positions)
    assert len({round(pos) for pos, _i in broker.positions}) > 5  # it moves
    assert driver.state.cruise.stack.waves
    driver.toggle_cruise()
    assert not driver.state.cruise.active and not driver.state.cruise.stack.waves


def test_a_hold_stills_the_motion_at_the_end_it_names(qtbot):
    """Cruise first, because it rewrites all three dials every tick; then the
    travel closes before the center moves, so the motion stills where it is and
    travels to the end from there rather than oscillating its way across."""
    driver, _broker, _clock = _driver(qtbot)
    motion_engine.enable_cruise_control(driver.state)

    driver.hold(RETRACT_CENTER)

    assert driver.held_at == RETRACT_CENTER
    assert driver.state.cruise.active is False
    assert driver.state.state.amplitude == 0
    assert driver.state.state.center == RETRACT_CENTER


def test_driving_puts_back_what_the_first_hold_stilled(qtbot):
    """Park, then retract, then driving: the second hold must not overwrite the
    recording the first one took, or the way back is a flat line at an end."""
    driver, _broker, _clock = _driver(qtbot)
    motion_engine.set_amplitude(driver.state.state, 60)
    motion_engine.set_center(driver.state.state, 40)
    motion_engine.set_speed(driver.state.state, 70)

    driver.hold(PARK_CENTER)
    driver.hold(RETRACT_CENTER)
    driver.release()

    assert driver.held_at is None
    assert (driver.state.state.amplitude, driver.state.state.intended_center,
            driver.state.state.speed) == (60, 40, 70)


def test_cruise_comes_back_last_where_it_was_on(qtbot):
    """It draws its waves from what the dials say, so it is re-armed after they
    are back rather than before."""
    driver, _broker, _clock = _driver(qtbot)
    motion_engine.enable_cruise_control(driver.state)

    driver.hold(PARK_CENTER)
    driver.release()

    assert driver.state.cruise.active is True


def test_driving_with_nothing_held_changes_nothing(qtbot):
    """The console's driving button is also the way back off control-off, where
    there is no hold to put back."""
    driver, _broker, _clock = _driver(qtbot)
    motion_engine.set_amplitude(driver.state.state, 55)

    driver.release()

    assert driver.state.state.amplitude == 55


def test_a_hold_refuses_every_dial_that_would_break_it(qtbot):
    """A nudge under a hold would move the device while the console still said
    it was held -- and driving puts the recording back, so it would be thrown
    away at the end of the hold anyway.  The console dims these same marks."""
    driver, _broker, _clock = _driver(qtbot)
    motion_engine.set_amplitude(driver.state.state, 60)
    driver.hold(PARK_CENTER)

    driver.adjust_amplitude(10)
    driver.set_amplitude(80)
    driver.adjust_center(5)
    driver.set_center(70)
    driver.adjust_speed(10)
    driver.toggle_cruise()
    driver.set_cruise(True)

    assert driver.state.state.amplitude == 0
    assert driver.state.state.center == PARK_CENTER
    assert driver.state.cruise.active is False


def test_the_dials_answer_again_once_the_hold_is_let_go(qtbot):
    driver, _broker, _clock = _driver(qtbot)
    driver.hold(PARK_CENTER)
    driver.release()

    driver.set_amplitude(80)

    assert driver.state.state.amplitude == 80


def test_a_tick_that_lands_after_the_device_is_given_up_sends_nothing(qtbot):
    driver, broker, clock = _driver(qtbot)
    driver.start()
    clock.t += 0.025
    driver.poll()
    sent = len(broker.positions)

    driver.stop()
    clock.t += 0.025
    driver.poll()

    assert broker.parked == 1
    assert len(broker.positions) == sent
