"""Osr2StrokeDriver — broker etiquette and the self-generated position stream."""

from origenerator.gui.osr2_stroke_driver import Osr2StrokeDriver


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


def _driver(qtbot):
    broker, clock = FakeBroker(), FakeClock()
    return Osr2StrokeDriver(broker, now_source=clock), broker, clock


def test_starting_takes_the_device_and_pauses_genau(qtbot):
    driver, broker, _clock = _driver(qtbot)
    handovers = []
    driver.active_changed.connect(handovers.append)
    assert driver.toggle() is True
    assert driver.active
    assert broker.paused == 1
    assert broker.parked == 0  # taking the device isn't parking it
    assert handovers == [True]  # announced, so the funscript drive stands down


def test_polls_stream_positions_advancing_with_the_clock(qtbot):
    driver, broker, clock = _driver(qtbot)
    driver.start()
    clock.t += 0.033
    driver.poll()
    clock.t += 0.033
    driver.poll()
    assert len(broker.positions) == 2
    (p1, i1), (p2, i2) = broker.positions
    assert 0.0 <= p1 <= 100.0 and 0.0 <= p2 <= 100.0
    assert p2 > p1  # a fresh sine stroke is rising off the bottom
    assert i1 == i2 == 33


def test_stopping_parks_the_device_and_restores_genau(qtbot):
    driver, broker, _clock = _driver(qtbot)
    driver.start()
    handovers = []
    driver.active_changed.connect(handovers.append)
    assert driver.toggle() is False
    assert broker.parked == 1
    assert broker.restored == 1
    assert handovers == [False]  # announced, so the funscript drive may re-aim
    driver.stop()  # already stopped: releasing again must not park twice
    assert broker.parked == 1
    assert handovers == [False]  # and a redundant stop announces nothing


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
