from __future__ import annotations

import logging
import queue
import time

import pytest
from app_support import ports
from app_support.file_channel import consume_command_file
from app_support.osr2_device import SILENT_ONCE_OFF_S, Osr2Mode, Osr2Trouble
from app_support.osr2_hold import PARK
from app_support.osr2_slot import Osr2Slot
from app_support.state_files import BROKER_CMD, BROKER_MODE, OSR2_NOT_FOUND, OSR2_SERIAL_RX
from app_support.threading_utils import start_daemon_thread

from origenerator.osr2 import Osr2Broker, device_mode, device_trouble, format_position


@pytest.fixture
def the_brokers_slot():
    """The broker's own slot on a port of the test's, and what it hands on."""
    lines: queue.Queue[tuple[str, str]] = queue.Queue()
    slot = Osr2Slot(port=0, logger=logging.getLogger("test.origenerator.osr2"),
                    start_thread=start_daemon_thread)
    slot.write_through(lambda sender, line: lines.put((sender, line)))
    slot.start()
    yield slot, lines
    slot.close()


def _first_line_handed_on(broker: Osr2Broker, lines) -> tuple[str, str]:
    deadline = time.monotonic() + 5.0
    while lines.empty() and time.monotonic() < deadline:
        broker.send_position(50, 100)
        time.sleep(0.005)
    return lines.get_nowait()


def test_format_position_maps_percent_to_four_digit_axis_and_interval():
    # L0 is the OSR2 motion axis; position is 0000-9999 (floor to top), then I<ms>.
    assert format_position(0, 100) == "L00000I100"
    assert format_position(50, 100) == "L05000I100"
    assert format_position(100, 250) == "L09999I250"


def test_format_position_clamps_out_of_range():
    assert format_position(-20, 40) == "L00000I40"
    assert format_position(140, 40) == "L09999I40"


def test_a_hold_is_asked_of_the_broker_where_it_drains_its_verbs(tmp_path):
    Osr2Broker(state_dir=tmp_path).ask(PARK)

    assert consume_command_file(tmp_path / BROKER_CMD) == [PARK]


def test_a_driving_app_reaches_the_osr2_through_the_brokers_slot_as_origenerator(
        the_brokers_slot):
    slot, lines = the_brokers_slot
    broker = Osr2Broker(port=slot.address[1])
    broker.want(True)
    try:
        assert _first_line_handed_on(broker, lines) == ("origenerator", "L05000I100")
    finally:
        broker.close()


def test_an_app_that_does_not_want_the_osr2_sends_it_nothing(the_brokers_slot):
    slot, lines = the_brokers_slot
    broker = Osr2Broker(port=slot.address[1])
    try:
        for _ in range(50):
            broker.send_position(50, 100)
            time.sleep(0.005)
    finally:
        broker.close()

    assert lines.empty() and slot.holder is None


# --- is the device there: what the console reads to say "Off" ---------------

def _rx(tmp_path, stamped=None):
    """The broker's directory, its stamp of when the OSR2 last spoke at whatever
    time is given."""
    if stamped is not None:
        (tmp_path / OSR2_SERIAL_RX).write_text(str(stamped), encoding="utf-8")
    return tmp_path


def test_the_device_having_spoken_recently_means_it_is_there(tmp_path):
    assert device_mode(now=1000.0, state_dir=_rx(tmp_path, 995.0)) is Osr2Mode.CONTROLLED


def test_a_device_that_has_gone_quiet_reads_as_off(tmp_path):
    assert device_mode(now=1000.0, state_dir=_rx(tmp_path, 960.0)) is Osr2Mode.OFF


def test_nothing_stamped_at_all_reads_as_off(tmp_path):
    # A broker that never ran, a state dir that isn't there, a hand-mangled file:
    # all of them are "as far as anything here can tell, no device".
    assert device_mode(now=1000.0, state_dir=_rx(tmp_path)) is Osr2Mode.OFF
    assert device_mode(now=1000.0, state_dir=_rx(tmp_path, "just now")) is Osr2Mode.OFF


def test_a_device_silent_for_the_whole_shared_window_reads_as_off(tmp_path):
    assert device_mode(now=1000.0, state_dir=_rx(tmp_path, 1000.0 - SILENT_ONCE_OFF_S)) is Osr2Mode.OFF


def test_a_broker_that_cannot_find_the_osr2_says_why_it_is_unheard(tmp_path):
    (tmp_path / OSR2_NOT_FOUND).write_text("999.5", encoding="utf-8")

    assert device_trouble(now=1000.0, state_dir=tmp_path) is Osr2Trouble.NOT_FOUND


def test_an_app_named_no_port_reaches_the_brokers_own_slot(the_brokers_slot, monkeypatch):
    slot, lines = the_brokers_slot
    monkeypatch.setattr(ports, "OSR2_SLOT", slot.address[1])
    broker = Osr2Broker()
    broker.want(True)
    try:
        assert _first_line_handed_on(broker, lines)[0] == "origenerator"
    finally:
        broker.close()


def test_a_device_running_its_own_auto_mode_reads_as_auto(tmp_path):
    (tmp_path / BROKER_MODE).write_text("1", encoding="utf-8")

    assert device_mode(now=1000.0, state_dir=_rx(tmp_path, 995.0)) is Osr2Mode.AUTO
