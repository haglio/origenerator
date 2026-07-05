from PyQt6.QtMultimedia import QMediaPlayer

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
    def __init__(self, pos=0, playing=True):
        self._pos = pos
        self._playing = playing

    def position(self):
        return self._pos

    def playbackState(self):
        return (
            QMediaPlayer.PlaybackState.PlayingState if self._playing
            else QMediaPlayer.PlaybackState.PausedState
        )


ACTIONS = [{"at": 0, "pos": 0}, {"at": 500, "pos": 100}, {"at": 1000, "pos": 0}]


def test_start_pauses_genau_and_poll_streams_toward_the_next_action(qapp):
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    driver.start(FakePlayer(pos=100), ACTIONS)

    assert broker.paused == 1
    driver.poll()
    # 100 ms in, the next action is the top (100) at 500 ms → head there over 400 ms.
    assert broker.positions[-1] == (100, 400)


def test_poll_sends_nothing_while_the_player_is_paused(qapp):
    broker = FakeBroker()
    driver = Osr2Driver(broker=broker)
    driver.start(FakePlayer(pos=100, playing=False), ACTIONS)

    driver.poll()
    assert broker.positions == []


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
