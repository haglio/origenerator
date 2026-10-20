from __future__ import annotations

from app_support.file_channel import consume_command_file
from app_support.osr2_device import SILENT_ONCE_OFF_S, Osr2Mode, Osr2Trouble
from app_support.osr2_hold import PARK
from app_support.state_files import BROKER_CMD, BROKER_MODE, OSR2_NOT_FOUND, OSR2_SERIAL_RX

from origenerator.osr2 import Osr2Broker, device_mode, device_trouble, format_position


class FakeSock:
    def __init__(self):
        self.sent = []
        self.closed = False

    def sendto(self, data, addr):
        self.sent.append((data, addr))

    def close(self):
        self.closed = True


def _broker(sock):
    return Osr2Broker("127.0.0.1", 50557, sock_factory=lambda: sock)


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


def test_send_position_streams_a_newline_terminated_tcode_datagram():
    sock = FakeSock()
    _broker(sock).send_position(50, 100)
    assert sock.sent == [(b"L05000I100\n", ("127.0.0.1", 50557))]


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


def test_a_broker_named_nothing_streams_where_the_broker_listens():
    named, unnamed = FakeSock(), FakeSock()

    Osr2Broker("127.0.0.1", 50557, sock_factory=lambda: named).send_position(50, 100)
    Osr2Broker(sock_factory=lambda: unnamed).send_position(50, 100)

    assert unnamed.sent == named.sent


def test_a_device_running_its_own_auto_mode_reads_as_auto(tmp_path):
    (tmp_path / BROKER_MODE).write_text("1", encoding="utf-8")

    assert device_mode(now=1000.0, state_dir=_rx(tmp_path, 995.0)) is Osr2Mode.AUTO
