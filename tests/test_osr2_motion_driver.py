from __future__ import annotations

import threading
import time
from itertools import pairwise

import pytest
from app_support.osr2_hold import PARK, RESUME, RETRACT
from funestra.learned_model import LearnedModel, Phrase, classify
from funestra.main_hud import OSR2_PARKED, OSR2_RETRACTED
from funestra.robot_hand import RobotHandState, set_max_intensity

from origenerator import motion_engine
from origenerator.osr2_motion_driver import (
    _HANDOFF_MS,
    _LOOKAHEAD_MS,
    Osr2MotionDriver,
    _TickThread,
)
from tests.osr2_fakes import FakeBroker
from tests.running_ahead_support import record_the_app_running_ahead


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class FakeTicker:
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
    assert broker.asked == [RESUME]
    assert handovers == [True]
    assert driver.tickers[0].started == 1


def test_the_motion_holds_the_brokers_slot_while_it_drives_and_lets_go_when_stopped(qtbot):
    driver, broker, _clock = _driver(qtbot)
    driver.start()
    driving = broker.wanted[-1]

    driver.stop()

    assert (driving, broker.wanted[-1]) == (True, False)


def test_a_frozen_room_or_a_hold_lets_go_of_the_slot_and_driving_again_wants_it_afresh(qtbot):
    driver, broker, _clock = _driver(qtbot)
    driver.start()
    driver.set_frozen(True)
    frozen = broker.wanted[-1]
    driver.set_frozen(False)
    playing = broker.wanted[-1]
    driver.hold(OSR2_PARKED)
    held = broker.wanted[-1]

    driver.release()

    assert (frozen, playing, held, broker.wanted[-1]) == (False, True, False, True)


def test_each_command_aims_as_far_ahead_as_the_time_it_gives(qtbot):
    driver, broker, clock = _driver(qtbot)
    driver.start()
    for step in (0.025, 0.025, 0.5, 0.025):
        clock.t += step
        driver.poll()
        pos, interval = broker.positions[-1]
        assert pos == motion_engine.position_ahead(driver.state, interval / 1000)
    assert interval == _LOOKAHEAD_MS
    assert pos > motion_engine.position(driver.state)


def test_the_takeover_keeps_streaming_and_eases_its_interval_out(qtbot):
    driver, broker, clock = _driver(qtbot)
    driver.start()
    assert broker.positions[0][1] == _HANDOFF_MS
    for _ in range(4):
        clock.t += 0.025
        driver.poll()
    intervals = [i for _pos, i in broker.positions]
    assert intervals == sorted(intervals, reverse=True)
    assert all(i >= _LOOKAHEAD_MS for i in intervals)
    clock.t += 0.5
    driver.poll()
    assert broker.positions[-1][1] == _LOOKAHEAD_MS


def test_a_late_tick_still_sends_over_the_lookahead(qtbot):
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
    assert driver.tickers[0].stopped == 1
    assert broker.parked == 1
    assert handovers == [False]
    driver.stop()
    assert broker.parked == 1
    assert handovers == [False]


def test_the_clock_runs_off_the_gui_thread(qtbot):
    seen = []
    ticker = _TickThread(lambda: seen.append(threading.current_thread()), 0.001)
    ticker.start()
    deadline = time.monotonic() + 2.0
    while not seen and time.monotonic() < deadline:
        time.sleep(0.01)
    ticker.stop()
    assert seen, "the clock never ticked"
    assert all(t is not threading.main_thread() for t in seen), (
        "a slideshow decodes a full-size image on the GUI thread every few seconds, and each such "
        "stall would starve a clock living there")


def test_a_long_stall_picks_the_beat_up_from_now_instead_of_firing_a_backlog():
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
    ticker._run()
    gaps = [b - a for a, b in pairwise(ticks)]
    assert gaps
    assert all(abs(g - 0.025) < 1e-9 for g in gaps)


def test_the_bars_shape_the_status_line(qtbot):
    driver, _broker, _clock = _driver(qtbot)
    driver.start()
    driver.adjust_speed(50)
    driver.adjust_amplitude(-40)
    driver.adjust_center(-100)
    driver.cycle_shape()
    assert driver.status_text() == "OSR2 · 200/min · triangle · travel 60 around 30", (
        "the speed bar at its top is 200 a minute, and a center slid all the way down stops at the "
        "floor of the sweep, 30 with this travel")


def test_the_status_line_says_the_motion_is_stopped_but_keeps_the_bars(qtbot):
    driver, _broker, _clock = _driver(qtbot)
    driver.adjust_speed(50)
    assert driver.status_text() == (
        "Motion stopped · 200/min · sine · travel 100 around 50")


def test_the_learned_motion_takes_the_motion_over_and_it_is_what_is_streamed(qtbot):
    phrase = Phrase(tuple((500, 80 if i % 2 == 0 else 20) for i in range(16)))
    driver, broker, clock = _driver(qtbot)
    driver.state.learned.model = LearnedModel(
        phrases={classify(phrase): [phrase]}, seen={classify(phrase): 1})
    driver.start()
    driver.toggle_learned()
    assert driver.state.learned.active
    for _ in range(60):
        clock.t += 0.025
        driver.poll()
        pos, interval = broker.positions[-1]
        assert pos == motion_engine.position_ahead(driver.state, interval / 1000)
    assert all(0.0 <= pos <= 100.0 for pos, _i in broker.positions)
    assert len({round(pos) for pos, _i in broker.positions}) > 5
    assert "human inspired" in driver.status_text()
    driver.set_learned(False)
    assert not driver.state.learned.active
    assert not driver.state.learned.times


def test_a_hold_leaves_amp_speed_and_center_where_they_were(qtbot):
    driver, _broker, _clock = _driver(qtbot)
    driver.set_amplitude(60)
    driver.set_center(40)
    driver.set_speed(70)

    driver.hold(OSR2_RETRACTED)

    bars = driver.state.state
    assert (bars.amplitude, bars.intended_center, bars.speed) == (60, 40, 70)


def test_while_held_the_broker_holds_the_device_and_the_motion_sends_nothing(qtbot):
    driver, broker, clock = _driver(qtbot)
    driver.start()
    sent = len(broker.positions)

    driver.hold(OSR2_RETRACTED)
    clock.t += 1.0
    driver.poll()

    assert driver.held == OSR2_RETRACTED
    assert broker.asked[-1] == RETRACT
    assert len(broker.positions) == sent


def test_driving_brings_the_device_back_to_the_motion_with_the_takeovers_glide(qtbot):
    driver, broker, clock = _driver(qtbot)
    driver.start()
    driver.hold(OSR2_PARKED)
    clock.t += 1.0
    driver.poll()

    driver.release()
    driver.poll()

    assert broker.asked[-1] == RESUME
    pos, interval = broker.positions[-1]
    assert interval == _HANDOFF_MS
    assert pos == motion_engine.position_ahead(driver.state, interval / 1000)


def test_park_then_retract_then_driving_leaves_amp_speed_and_center_as_they_were(qtbot):
    driver, _broker, _clock = _driver(qtbot)
    motion_engine.set_amplitude(driver.state.state, 60)
    motion_engine.set_center(driver.state.state, 40)
    motion_engine.set_speed(driver.state.state, 70)

    driver.hold(OSR2_PARKED)
    driver.hold(OSR2_RETRACTED)
    driver.release()

    assert driver.held is None
    assert (driver.state.state.amplitude, driver.state.state.intended_center,
            driver.state.state.speed) == (60, 40, 70)


def test_human_inspired_motion_stays_on_through_a_hold(qtbot):
    driver, _broker, _clock = _driver(qtbot)
    driver.set_learned(True)

    driver.hold(OSR2_PARKED)
    driver.release()

    assert driver.state.learned.active is True


def test_driving_with_nothing_held_changes_nothing(qtbot):
    driver, _broker, _clock = _driver(qtbot)
    motion_engine.set_amplitude(driver.state.state, 55)

    driver.release()

    assert driver.state.state.amplitude == 55


def test_amp_speed_center_and_human_inspired_answer_while_held_as_they_do_in_fun_time(qtbot):
    driver, _broker, _clock = _driver(qtbot)
    driver.set_amplitude(60)
    speed = driver.state.state.speed
    driver.hold(OSR2_PARKED)

    driver.adjust_amplitude(10)
    driver.set_center(50)
    driver.adjust_speed(10)
    driver.set_learned(True)

    bars = driver.state.state
    assert (bars.amplitude, bars.intended_center, bars.speed) == (70, 50, speed + 10)
    assert driver.state.learned.active is True


def test_the_max_intensity_is_the_devices_to_keep_even_through_a_hold(qtbot):
    driver, _broker, _clock = _driver(qtbot)
    driver.start()
    driver.hold(OSR2_PARKED)

    driver.set_max_intensity(30)

    assert driver.state.state.max_intensity == 30


def test_a_max_intensity_lowered_while_held_lowers_the_bars_at_once(qtbot):
    driver, _broker, _clock = _driver(qtbot)
    driver.set_amplitude(90)
    driver.set_speed(90)
    bars = driver.state.state
    pushed = RobotHandState(amplitude=90, speed=90, intended_center=bars.intended_center)
    set_max_intensity(pushed, 30)
    driver.hold(OSR2_PARKED)

    driver.set_max_intensity(30)

    assert (bars.speed, bars.amplitude, bars.center) == (
        pushed.speed, pushed.amplitude, pushed.center)


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


def test_a_frozen_room_stops_the_motion_at_once_and_sends_nothing_more(qtbot):
    driver, broker, clock = _driver(qtbot)
    driver.start()
    sent = len(broker.positions)

    driver.set_frozen(True)
    clock.t += 0.025
    driver.poll()

    assert driver.tickers[0].stopped == 1
    assert len(broker.positions) == sent
    assert driver.active


def test_a_frozen_room_asks_the_broker_to_park_the_device(qtbot):
    driver, broker, _clock = _driver(qtbot)
    driver.start()

    driver.set_frozen(True)

    assert broker.asked == [RESUME, PARK]


def test_a_room_played_again_hands_the_device_back_to_the_motion(qtbot):
    driver, broker, _clock = _driver(qtbot)
    driver.start()

    driver.set_frozen(True)
    driver.set_frozen(False)

    assert broker.asked == [RESUME, PARK, RESUME]


def test_the_motion_plays_on_from_where_the_room_froze_it(qtbot):
    driver, broker, clock = _driver(qtbot)
    driver.start()
    clock.t += 0.5
    driver.poll()
    where = motion_engine.position(driver.state)

    driver.set_frozen(True)
    clock.t += 60.0
    driver.set_frozen(False)

    assert motion_engine.position(driver.state) == where
    assert broker.positions[-1][1] == _HANDOFF_MS
    assert driver.tickers[-1].started == 1


def test_a_motion_started_in_a_frozen_room_waits_for_it_to_play(qtbot):
    driver, broker, _clock = _driver(qtbot)
    driver.set_frozen(True)

    driver.start()
    assert driver.active
    assert broker.positions == []
    assert driver.tickers == []

    driver.set_frozen(False)
    assert broker.positions
    assert driver.tickers[0].started == 1


def test_a_held_motion_stays_at_its_end_through_a_freeze(qtbot):
    driver, broker, clock = _driver(qtbot)
    driver.start()
    driver.hold(OSR2_RETRACTED)
    sent = len(broker.positions)

    driver.set_frozen(True)
    clock.t += 1.0
    driver.poll()

    assert broker.asked == [RESUME, RETRACT]
    assert len(broker.positions) == sent


def test_a_hold_asked_for_in_a_frozen_room_takes_the_device_to_its_end(qtbot):
    driver, broker, _clock = _driver(qtbot)
    driver.start()
    driver.set_frozen(True)

    driver.hold(OSR2_RETRACTED)

    assert broker.asked[-1] == RETRACT


def test_letting_a_hold_go_in_a_frozen_room_parks_the_device(qtbot):
    driver, broker, _clock = _driver(qtbot)
    driver.start()
    driver.hold(OSR2_RETRACTED)
    driver.set_frozen(True)

    driver.release()

    assert broker.asked[-1] == PARK


def test_a_motion_stopped_in_a_frozen_room_parks_now_and_stays_stopped(qtbot):
    driver, broker, _clock = _driver(qtbot)
    driver.start()
    driver.set_frozen(True)
    sent = len(broker.positions)

    driver.stop()
    driver.set_frozen(False)

    assert broker.parked == 1
    assert len(broker.positions) == sent


@pytest.mark.parametrize("saved", [
    None,
    "fast",
    {"speed": "fast", "amplitude": 60, "center": 40, "shape": "wobble", "human_inspired": "yes"},
])
def test_settings_that_no_longer_read_leave_the_motion_where_it_opens(saved):
    motion = motion_engine.Motion()

    motion_engine.take_settings(motion, saved)

    assert motion_engine.settings_of(motion) == motion_engine.settings_of(motion_engine.Motion())


def test_the_app_runs_ahead_of_background_work_while_the_motion_drives(qtbot, monkeypatch):
    raised = record_the_app_running_ahead(monkeypatch)
    driver, _broker, _clock = _driver(qtbot)

    driver.start()
    assert raised == ["ahead"]

    driver.stop()
    assert raised == ["ahead", "back"]


def test_a_paused_room_lets_the_app_go_back_behind_background_work(qtbot, monkeypatch):
    raised = record_the_app_running_ahead(monkeypatch)
    driver, _broker, _clock = _driver(qtbot)
    driver.start()

    driver.set_frozen(True)
    assert raised == ["ahead", "back"]

    driver.set_frozen(False)
    assert raised == ["ahead", "back", "ahead"]


def test_where_the_wave_stands_in_its_bars_is_a_fraction_of_the_way_up_from_the_floor_to_the_ceiling():
    motion = motion_engine.Motion()
    motion_engine.set_bars(motion.state, speed=50, amplitude=60, center=50)

    fractions = []
    for phase in (0.0, 0.25, 0.5):
        motion.phase = phase
        fractions.append(motion_engine._envelope_fraction(motion))

    assert fractions == pytest.approx([0.0, 0.5, 1.0])


def test_a_wave_with_no_amplitude_stands_at_the_floor_of_its_bars():
    motion = motion_engine.Motion()
    motion_engine.set_bars(motion.state, speed=50, amplitude=0, center=50)

    assert motion_engine._envelope_fraction(motion) == 0.0
