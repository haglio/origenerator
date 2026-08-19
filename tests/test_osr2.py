from origenerator.osr2 import Osr2Broker, PARK_TCODE, device_on, format_position


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


# --- is the device on the wire: what the console reads to say "Off" ----------

def _stamps(tmp_path, rx=None, tx=None):
    """The broker's two serial stamps, written with whatever times are given."""
    rx_file, tx_file = tmp_path / "rx.txt", tmp_path / "tx.txt"
    for path, stamped in ((rx_file, rx), (tx_file, tx)):
        if stamped is not None:
            path.write_text(str(stamped), encoding="utf-8")
    return {"rx_file": rx_file, "tx_file": tx_file}


def test_a_fresh_stamp_either_way_means_the_device_is_there(tmp_path):
    # Fun Time counts both: the device only speaks when spoken to, so the reply
    # stamp alone goes quiet through any stretch nothing is being sent.
    assert device_on(now=1000.0, **_stamps(tmp_path, rx=995.0, tx=100.0)) is True
    assert device_on(now=1000.0, **_stamps(tmp_path, rx=100.0, tx=995.0)) is True


def test_both_stamps_stale_means_nothing_is_on_the_wire(tmp_path):
    assert device_on(now=1000.0, **_stamps(tmp_path, rx=980.0, tx=983.0)) is False


def test_no_stamps_at_all_reads_as_off(tmp_path):
    # A broker that never ran, a state dir that isn't there, a hand-mangled file:
    # all of them are "as far as anything here can tell, no device".
    assert device_on(now=1000.0, **_stamps(tmp_path)) is False
    assert device_on(now=1000.0, **_stamps(tmp_path, rx="just now", tx="")) is False
