from __future__ import annotations

import os

from app_support.osr2_hold import PARK, RESUME
from funestra.funscript import Funscript

from origenerator import osr2_driver
from origenerator.funscript import funscript_path_for
from origenerator.osr2_driver import DriveScripts, Osr2Driver, drive_script
from origenerator.output_places import OutputPlaces
from tests.funscript_files import write_funscript
from tests.osr2_fakes import FakeBroker
from tests.running_ahead_support import record_the_app_running_ahead


class FakePlayer:
    def __init__(self, pos=0):
        self._pos = pos

    def position(self):
        return self._pos


ACTIONS = [{"at": 0, "pos": 0}, {"at": 500, "pos": 100}, {"at": 1000, "pos": 0}]
SCRIPT = drive_script(ACTIONS)


def test_poll_streams_toward_the_next_action(qapp):
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    driver.start(FakePlayer(pos=100), SCRIPT)

    driver.poll()
    assert broker.positions[-1] == (100, 400)


def test_a_playhead_that_has_stopped_moving_holds_the_device_at_the_same_target(qapp):
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    driver.start(FakePlayer(pos=100), SCRIPT)

    driver.poll()
    driver.poll()

    assert broker.positions[-2:] == [(100, 400), (100, 400)]


def test_poll_drives_from_the_playhead_without_a_playback_state(qapp):
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    driver.start(FakePlayer(pos=0), SCRIPT)

    driver.poll()
    assert broker.positions == [(100, 500)]


def test_poll_wraps_position_onto_a_looping_video(qapp):
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    driver.start(FakePlayer(pos=1100), SCRIPT)

    driver.poll()
    assert broker.positions[-1] == (100, 400)


def test_a_script_past_the_max_intensity_is_streamed_as_shallow_as_it_leaves(qapp):
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    driver.max_intensity = 30
    driver.start(FakePlayer(pos=100), SCRIPT)

    driver.poll()

    script = Funscript(actions=[(a["at"], a["pos"]) for a in ACTIONS])
    assert broker.positions[-1] == (
        round(script.paced_position_at(500, 1.0, max_intensity=30)), 400)


def test_stop_parks_the_device(qapp):
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    driver.start(FakePlayer(), SCRIPT)

    driver.stop()
    assert broker.parked == 1


def test_a_funscript_with_no_actions_gives_the_device_nothing_to_drive():
    assert drive_script([]) is None


def test_a_funscript_out_of_order_is_driven_in_the_order_of_its_times():
    assert drive_script(list(reversed(ACTIONS))) == SCRIPT


def test_it_says_whether_it_has_the_device(qapp):
    driver = Osr2Driver(broker=FakeBroker())
    assert driver.active is False

    driver.start(FakePlayer(pos=0), SCRIPT)
    assert driver.active is True

    driver.stop()
    assert driver.active is False


def test_the_line_it_draws_is_the_script_from_the_playhead_forward(qapp):
    driver = Osr2Driver(broker=FakeBroker())
    driver.start(FakePlayer(pos=0), SCRIPT)

    heights = driver.trace(5, 1.0)

    assert len(heights) == 5
    assert heights[0] == 0.0
    assert heights[2] == 1.0
    assert heights[4] == 0.0


def test_the_line_it_draws_gives_up_the_depth_the_max_intensity_takes(qapp):
    driver = Osr2Driver(broker=FakeBroker())
    driver.max_intensity = 30
    driver.start(FakePlayer(pos=0), SCRIPT)

    heights = driver.trace(5, 1.0)

    script = Funscript(actions=[(a["at"], a["pos"]) for a in ACTIONS])
    assert heights[2] == script.paced_position_at(500, 1.0, max_intensity=30) / 100


def test_the_line_folds_onto_the_script_the_way_the_stream_does(qapp):
    driver = Osr2Driver(broker=FakeBroker())
    driver.start(FakePlayer(pos=750), SCRIPT)

    heights = driver.trace(3, 1.0)

    assert heights == (0.5, 0.5, 0.5)


def test_a_driver_with_nothing_to_follow_draws_nothing(qapp):
    assert Osr2Driver(broker=FakeBroker()).trace(8, 1.0) == ()


def test_a_frozen_room_stops_a_script_at_once_and_asks_the_broker_to_park_it(qapp):
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    driver.start(FakePlayer(pos=100), SCRIPT)

    driver.set_frozen(True)
    driver.poll()

    assert broker.positions == []
    assert broker.asked == [RESUME, PARK]
    assert driver.active


def test_a_script_driving_the_osr2_holds_the_brokers_slot_until_it_lets_go(qapp):
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    driver.start(FakePlayer(pos=100), SCRIPT)
    holding = broker.wanted[-1]

    driver.stop()

    assert (holding, broker.wanted[-1]) == (True, False)


def test_a_frozen_room_lets_go_of_the_slot_and_playing_again_wants_it_afresh(qapp):
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    driver.start(FakePlayer(pos=100), SCRIPT)

    driver.set_frozen(True)
    driver.set_frozen(False)

    assert broker.wanted == [True, False, True]


def test_a_script_started_in_a_frozen_room_waits_to_want_the_slot(qapp):
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    driver.set_frozen(True)

    driver.start(FakePlayer(pos=100), SCRIPT)

    assert broker.wanted == [False]


def test_a_script_played_again_hands_the_device_back_and_follows_the_playhead(qapp):
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    driver.start(FakePlayer(pos=100), SCRIPT)

    driver.set_frozen(True)
    driver.set_frozen(False)
    driver.poll()

    assert broker.asked == [RESUME, PARK, RESUME]
    assert broker.positions == [(100, 400)]


def test_a_script_let_go_of_in_a_frozen_room_is_parked_once(qtbot):
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    driver.start(FakePlayer(pos=100), SCRIPT)
    driver.set_frozen(True)

    driver.stop()

    assert broker.parked == 1


def test_a_script_started_in_a_frozen_room_waits_for_it_to_play(qapp):
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    driver.set_frozen(True)

    driver.start(FakePlayer(pos=0), SCRIPT)
    driver.poll()
    assert broker.positions == []

    driver.set_frozen(False)
    driver.poll()
    assert broker.positions == [(100, 500)]


def test_the_app_runs_ahead_of_background_work_while_a_video_drives(qapp, monkeypatch):
    raised = record_the_app_running_ahead(monkeypatch)
    driver = Osr2Driver(broker=FakeBroker())

    driver.start(FakePlayer(pos=0), SCRIPT)
    assert raised == ["ahead"]

    driver.stop()
    assert raised == ["ahead", "back"]


class _Tickers:
    def __init__(self):
        self.made = []

    def __call__(self, tick, interval_s):
        ticker = _Ticker(tick, interval_s)
        self.made.append(ticker)
        return ticker


class _Ticker:
    def __init__(self, tick, interval_s):
        self.tick, self.interval_s = tick, interval_s
        self.running = False

    def start(self):
        self.running = True

    def stop(self):
        self.running = False


def test_a_script_is_streamed_from_a_clock_of_its_own_every_50_ms(qapp):
    broker, tickers = FakeBroker(), _Tickers()
    driver = Osr2Driver(broker=broker, ticker_factory=tickers)
    driver.start(FakePlayer(pos=100), SCRIPT)

    [ticker] = tickers.made
    ticker.tick()

    assert (ticker.running, ticker.interval_s, broker.positions) == (True, 0.05, [(100, 400)]), (
        "the device's timing rides on a thread of its own, so a busy window cannot stall it")


def test_letting_go_of_a_script_stops_its_clock(qapp):
    tickers = _Tickers()
    driver = Osr2Driver(broker=FakeBroker(), ticker_factory=tickers)
    driver.start(FakePlayer(pos=100), SCRIPT)

    driver.stop()

    assert [ticker.running for ticker in tickers.made] == [False]


def test_a_frozen_room_stops_the_clock_and_playing_again_starts_one(qapp):
    tickers = _Tickers()
    driver = Osr2Driver(broker=FakeBroker(), ticker_factory=tickers)
    driver.start(FakePlayer(pos=100), SCRIPT)

    driver.set_frozen(True)
    stopped = [ticker.running for ticker in tickers.made]
    driver.set_frozen(False)

    assert (stopped, [ticker.running for ticker in tickers.made]) == ([False], [False, True])


def test_a_script_started_in_a_frozen_room_starts_no_clock_until_it_plays(qapp):
    tickers = _Tickers()
    driver = Osr2Driver(broker=FakeBroker(), ticker_factory=tickers)
    driver.set_frozen(True)

    driver.start(FakePlayer(pos=100), SCRIPT)

    assert tickers.made == []


def _scripted(monkeypatch, tmp_path, name="video one.mp4", actions=ACTIONS):
    places = OutputPlaces.in_one_folder(tmp_path)
    monkeypatch.setattr(osr2_driver, "OUTPUT_PLACES", places)
    video = tmp_path / "video" / name
    script = funscript_path_for(video, places=places)
    script.parent.mkdir(parents=True, exist_ok=True)
    write_funscript(script, actions)
    return str(video), script


LONG_AFTER_ANY_STAMP_NS = 2**62


def _counting_reads(kept: int = 4):
    read = []

    def reading(path):
        read.append(path.name)
        return osr2_driver.read_actions(path)

    return DriveScripts(read=reading, kept=kept, now_ns=lambda: LONG_AFTER_ANY_STAMP_NS), read


def test_a_funscript_unchanged_since_it_was_read_is_not_read_again(monkeypatch, tmp_path):
    video, _script = _scripted(monkeypatch, tmp_path)
    scripts, read = _counting_reads()

    first, again = scripts.script_of(video), scripts.script_of(video)

    assert (first, again, read) == (SCRIPT, SCRIPT, ["video one.mp4.funscript"])


def test_a_funscript_written_again_is_read_again(monkeypatch, tmp_path):
    video, script = _scripted(monkeypatch, tmp_path)
    scripts, _read = _counting_reads()
    scripts.script_of(video)

    rewritten = [{"at": 0, "pos": 100}, {"at": 400, "pos": 0}]
    write_funscript(script, rewritten)
    stat = script.stat()
    os.utime(script, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    assert scripts.script_of(video) == drive_script(rewritten)


def test_a_funscript_read_ahead_is_not_read_again_when_its_video_comes_on(monkeypatch, tmp_path):
    video, _script = _scripted(monkeypatch, tmp_path)
    scripts, read = _counting_reads()

    scripts.keep(scripts.read_ahead(video))

    assert (scripts.script_of(video), read) == (SCRIPT, ["video one.mp4.funscript"])


def test_a_video_with_no_funscript_is_read_as_none_and_kept_as_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(osr2_driver, "OUTPUT_PLACES", OutputPlaces.in_one_folder(tmp_path))
    scripts, read = _counting_reads()

    scripts.keep(scripts.read_ahead(str(tmp_path / "video" / "unscripted.mp4")))

    assert (scripts.script_of(str(tmp_path / "video" / "unscripted.mp4")), read) == (None, [])


def test_only_the_last_few_funscripts_read_are_kept(monkeypatch, tmp_path):
    videos = [_scripted(monkeypatch, tmp_path, f"video {n}.mp4")[0] for n in range(3)]
    scripts, read = _counting_reads(kept=2)

    for video in [*videos, videos[0]]:
        scripts.script_of(video)

    assert read == ["video 0.mp4.funscript", "video 1.mp4.funscript", "video 2.mp4.funscript",
                    "video 0.mp4.funscript"]


def test_a_funscript_already_kept_is_not_read_ahead_again(monkeypatch, tmp_path):
    video, _script = _scripted(monkeypatch, tmp_path)
    scripts, read = _counting_reads()
    scripts.script_of(video)

    assert (scripts.read_ahead(video), read) == (None, ["video one.mp4.funscript"])
