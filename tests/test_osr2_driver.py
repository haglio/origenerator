from origenerator.gui.osr2_driver import Osr2Driver


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


class FakePlayer:
    """Only exposes position() — the driver follows the playhead and doesn't gate
    on QMediaPlayer's playback state (the info-pane preview auto-plays and has no
    pause control; the Drive OSR2 button is the on/off)."""

    def __init__(self, pos=0):
        self._pos = pos

    def position(self):
        return self._pos


ACTIONS = [{"at": 0, "pos": 0}, {"at": 500, "pos": 100}, {"at": 1000, "pos": 0}]


def test_start_pauses_genau_and_poll_streams_toward_the_next_action(qapp):
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    driver.start(FakePlayer(pos=100), ACTIONS)

    assert broker.paused == 1
    driver.poll()
    # 100 ms in, the next action is the top (100) at 500 ms → head there over 400 ms.
    assert broker.positions[-1] == (100, 400)


def test_poll_drives_from_the_playhead_without_a_playback_state(qapp):
    # A player that exposes only position() still drives — no playbackState() needed.
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    driver.start(FakePlayer(pos=0), ACTIONS)

    driver.poll()
    assert broker.positions == [(100, 500)]  # from the bottom, head to the top at 500 ms


def test_poll_wraps_position_onto_a_looping_clip(qapp):
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    # The preview loops, so a position past the script length maps back onto it.
    driver.start(FakePlayer(pos=1100), ACTIONS)  # 1100 % 1000 = 100

    driver.poll()
    assert broker.positions[-1] == (100, 400)


def test_stop_parks_the_device_and_restores_genau(qapp):
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    driver.start(FakePlayer(), ACTIONS)

    driver.stop()
    assert broker.parked == 1 and broker.restored == 1


def test_start_with_no_actions_does_not_engage(qapp):
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    driver.start(FakePlayer(), [])

    assert broker.paused == 0
    driver.poll()
    assert broker.positions == []
