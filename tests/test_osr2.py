from origenerator.osr2 import Osr2Broker, PARK_TCODE, format_position


class FakeSock:
    def __init__(self):
        self.sent = []
        self.closed = False

    def sendto(self, data, addr):
        self.sent.append((data, addr))

    def close(self):
        self.closed = True


def _broker(tmp_path, sock):
    return Osr2Broker(
        "127.0.0.1", 50557,
        genau_enabled_file=tmp_path / "genau_enabled.txt",
        sock_factory=lambda: sock,
    )


def test_format_position_maps_percent_to_four_digit_axis_and_interval():
    # L0 is the OSR2 stroke axis; position is 0000-9999 (bottom-top), then I<ms>.
    assert format_position(0, 100) == "L00000I100"
    assert format_position(50, 100) == "L05000I100"
    assert format_position(100, 250) == "L09999I250"


def test_format_position_clamps_out_of_range():
    assert format_position(-20, 40) == "L00000I40"
    assert format_position(140, 40) == "L09999I40"


def test_park_tcode_matches_the_broker_rest_command():
    assert PARK_TCODE == "L00000I500"


def test_send_position_streams_a_newline_terminated_tcode_datagram(tmp_path):
    sock = FakeSock()
    _broker(tmp_path, sock).send_position(50, 100)
    assert sock.sent == [(b"L05000I100\n", ("127.0.0.1", 50557))]


def test_park_sends_the_rest_command(tmp_path):
    sock = FakeSock()
    _broker(tmp_path, sock).park()
    assert sock.sent == [(b"L00000I500\n", ("127.0.0.1", 50557))]


def test_pause_genau_writes_zero_then_restore_puts_the_prior_value_back(tmp_path):
    flag = tmp_path / "genau_enabled.txt"
    flag.write_text("1", encoding="utf-8")
    broker = _broker(tmp_path, FakeSock())

    broker.pause_genau()
    assert flag.read_text(encoding="utf-8") == "0"
    broker.restore_genau()
    assert flag.read_text(encoding="utf-8") == "1"


def test_pause_genau_treats_a_missing_flag_as_enabled(tmp_path):
    flag = tmp_path / "genau_enabled.txt"  # absent → broker default is enabled
    broker = _broker(tmp_path, FakeSock())

    broker.pause_genau()
    assert flag.read_text(encoding="utf-8") == "0"
    broker.restore_genau()
    assert flag.read_text(encoding="utf-8") == "1"


def test_restore_genau_without_a_pause_does_nothing(tmp_path):
    flag = tmp_path / "genau_enabled.txt"
    _broker(tmp_path, FakeSock()).restore_genau()
    assert not flag.exists()
