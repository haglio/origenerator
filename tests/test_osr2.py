from __future__ import annotations

from origenerator.osr2 import PARK_TCODE, Osr2Broker, device_on, format_position


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


def test_park_tcode_is_the_familys_park_command():
    from player_core.tcode import PARK_COMMAND

    assert PARK_TCODE is PARK_COMMAND
    assert PARK_TCODE == "L00000I500"


def test_send_position_streams_a_newline_terminated_tcode_datagram():
    sock = FakeSock()
    _broker(sock).send_position(50, 100)
    assert sock.sent == [(b"L05000I100\n", ("127.0.0.1", 50557))]


def test_park_sends_the_rest_command():
    sock = FakeSock()
    _broker(sock).park()
    assert sock.sent == [(b"L00000I500\n", ("127.0.0.1", 50557))]


# --- is the device there: what the console reads to say "Off" ---------------

def _rx(tmp_path, stamped=None):
    """The broker's stamp of when the OSR2 last spoke, at whatever time is given."""
    path = tmp_path / "rx.txt"
    if stamped is not None:
        path.write_text(str(stamped), encoding="utf-8")
    return path


def test_the_device_having_spoken_recently_means_it_is_there(tmp_path):
    assert device_on(now=1000.0, rx_file=_rx(tmp_path, 995.0)) is True


def test_a_device_that_has_gone_quiet_reads_as_off(tmp_path):
    assert device_on(now=1000.0, rx_file=_rx(tmp_path, 960.0)) is False


def test_nothing_stamped_at_all_reads_as_off(tmp_path):
    # A broker that never ran, a state dir that isn't there, a hand-mangled file:
    # all of them are "as far as anything here can tell, no device".
    assert device_on(now=1000.0, rx_file=_rx(tmp_path)) is False
    assert device_on(now=1000.0, rx_file=_rx(tmp_path, "just now")) is False


def test_the_staleness_window_can_be_named_like_the_file_it_reads(tmp_path):
    """It was read off the config module from inside the function while the file
    beside it was a parameter, so a caller could point the check at a stamp but
    not at a window. Both are arguments now, and both still default to the
    broker's own numbers."""
    stamped = _rx(tmp_path, 960.0)

    assert device_on(now=1000.0, rx_file=stamped, stale_s=60.0) is True
    assert device_on(now=1000.0, rx_file=stamped, stale_s=10.0) is False


def test_the_window_defaults_to_the_brokers_own(tmp_path, monkeypatch):
    """Named or not, the number is the broker's, so the app and the broker never
    disagree about whether the OSR2 is there."""
    from origenerator import osr2

    monkeypatch.setattr(osr2, "RX_STALE_S", 5.0)

    assert device_on(now=1000.0, rx_file=_rx(tmp_path, 997.0)) is True
    assert device_on(now=1000.0, rx_file=_rx(tmp_path, 990.0)) is False


def test_a_broker_named_nothing_streams_where_the_broker_listens():
    named, unnamed = FakeSock(), FakeSock()

    Osr2Broker("127.0.0.1", 50557, sock_factory=lambda: named).park()
    Osr2Broker(sock_factory=lambda: unnamed).park()

    assert unnamed.sent == named.sent
