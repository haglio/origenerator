from __future__ import annotations

from origenerator.gui.osr2_driver import Osr2Driver


class FakeBroker:
    def __init__(self):
        self.positions = []
        self.parked = 0

    def send_position(self, pos, interval_ms):
        self.positions.append((pos, interval_ms))

    def park(self):
        self.parked += 1


class FakePlayer:
    """Only exposes position() — the driver follows the playhead and doesn't gate
    on QMediaPlayer's playback state (the info-pane preview auto-plays and has no
    pause control; the Drive OSR2 button is the on/off)."""

    def __init__(self, pos=0):
        self._pos = pos

    def position(self):
        return self._pos


ACTIONS = [{"at": 0, "pos": 0}, {"at": 500, "pos": 100}, {"at": 1000, "pos": 0}]


def test_poll_streams_toward_the_next_action(qapp):
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    driver.start(FakePlayer(pos=100), ACTIONS)

    driver.poll()
    # 100 ms in, the next action is the top (100) at 500 ms → head there over 400 ms.
    assert broker.positions[-1] == (100, 400)


def test_poll_drives_from_the_playhead_without_a_playback_state(qapp):
    # A player that exposes only position() still drives — no playbackState() needed.
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    driver.start(FakePlayer(pos=0), ACTIONS)

    driver.poll()
    assert broker.positions == [(100, 500)]  # from the floor, head to the top at 500 ms


def test_poll_wraps_position_onto_a_looping_clip(qapp):
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    # The preview loops, so a position past the script length maps back onto it.
    driver.start(FakePlayer(pos=1100), ACTIONS)  # 1100 % 1000 = 100

    driver.poll()
    assert broker.positions[-1] == (100, 400)


def test_stop_parks_the_device(qapp):
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    driver.start(FakePlayer(), ACTIONS)

    driver.stop()
    assert broker.parked == 1


def test_start_with_no_actions_does_not_engage(qapp):
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    driver.start(FakePlayer(), [])

    driver.poll()
    assert broker.positions == []


def test_it_says_whether_it_has_the_device(qapp):
    driver = Osr2Driver(broker=FakeBroker())
    assert driver.active is False

    driver.start(FakePlayer(pos=0), ACTIONS)
    assert driver.active is True

    driver.stop()
    assert driver.active is False


def test_the_line_it_draws_is_the_script_from_the_playhead_forward(qapp):
    """What the console draws in the motion's place while a script has the
    device: where the script puts it now, and where it is about to."""
    driver = Osr2Driver(broker=FakeBroker())
    driver.start(FakePlayer(pos=0), ACTIONS)

    heights = driver.trace(5, 1.0)  # a second, in quarter-second steps

    assert len(heights) == 5
    assert heights[0] == 0.0     # the script opens on the floor
    assert heights[2] == 1.0     # its peak, half a second in
    assert heights[4] == 0.0     # and back down by the end


def test_the_line_folds_onto_the_script_the_way_the_stream_does(qapp):
    """The preview loops, so the stream wraps the playhead onto the script --
    and a line drawn past the end would flatten where the device turns round."""
    driver = Osr2Driver(broker=FakeBroker())
    driver.start(FakePlayer(pos=750), ACTIONS)

    heights = driver.trace(3, 1.0)  # 750ms, 1250ms -> 250ms, 1750ms -> 750ms

    assert heights == (0.5, 0.5, 0.5)


def test_a_driver_with_nothing_to_follow_draws_nothing(qapp):
    assert Osr2Driver(broker=FakeBroker()).trace(8, 1.0) == ()
