"""Talk to the OSR2 device through the broker sibling.

The broker owns the device (real serial ``COM4``) and forwards raw T-code sent to
its UDP listener straight to it, suppressing MultiFunPlayer for a moment so the two
don't fight (``osr2_broker/session.py``). So origenerator drives the device simply
by streaming T-code here in sync with a playing video. While it drives, it pauses
genau auto-mode by writing the broker's shared enabled flag, then restores it.

Everything is best-effort: UDP to nobody and a write to an absent state dir are
harmless no-ops, so the app behaves the same whether or not the broker is running.
"""

from __future__ import annotations

import logging
import socket
import time
from pathlib import Path

from app_support.file_channel import read_flag, stamp_age, write_flag

from origenerator import config
from origenerator.paths import ensure_player_core_on_path

# Before any player_core import: that checkout is a sibling on the path, not a
# dependency the launch interpreter has installed (see tests/test_sibling_imports).
ensure_player_core_on_path()

from player_core.tcode import (  # noqa: E402
    PARK_COMMAND,
    UdpTCodeSink,
    format_tcode_command,
    to_tcode_position,
)

logger = logging.getLogger(__name__)

# The device's rest command -- stroke axis to the bottom over half a second, the
# family's one spelling of it, which the broker parks with too -- so a stopped
# video leaves the OSR2 where the broker expects it.
PARK_TCODE = PARK_COMMAND


def device_on(*, now: float | None = None, rx_file=None,
              stale_s: float | None = None) -> bool:
    """Whether the OSR2 is there — the broker's own rule, off the broker's own stamp.

    The device speaking is the only evidence that it is switched on: the USB
    cable is never unplugged, so the port is enumerated whether or not the thing
    at the end of it has power, and T-code carries no acknowledgment, so a write
    that goes nowhere looks exactly like one that arrives. The broker keeps a
    second stamp for what it last *sent*, and that one is nothing to go by here
    for precisely this app's reason: its stroke streams T-code through the broker
    the moment the switch goes on, which would keep the sent stamp fresh against
    a device that is switched off and have the console call it driving. (Fun
    Time can afford to count that stamp — the genau it runs drives only a device
    that has already announced itself over the wire.)

    Best-effort like everything else here: a missing state dir, an unreadable
    stamp, or a broker that never ran all read as off, which is the truth as far
    as anything here can tell.
    """
    current = time.time() if now is None else now
    path = Path(rx_file if rx_file is not None else config.OSR2_SERIAL_RX_FILE)
    window = config.OSR2_RX_STALE_S if stale_s is None else stale_s
    age = stamp_age(path, current)
    return age is not None and age < window


def format_position(pos_0_100: float, interval_ms: float) -> str:
    """A T-code move for the L0 stroke axis: ``L0<0000-9999>I<ms>``.

    ``pos_0_100`` is a funscript position (0 bottom, 100 top); ``interval_ms`` is
    how long the device takes to get there, so streaming each action with the
    time until the next reads as smooth motion.  The scaling and the clamp are
    player_core's, the same ones every other driver in the family sends with.
    """
    return format_tcode_command("L0", to_tcode_position(pos_0_100), int(interval_ms))


class Osr2Broker:
    """A thin UDP client to the broker's T-code listener, plus genau coordination.

    Holds one datagram socket for streaming stroke positions, and knows how to pause
    and restore genau auto-mode via the broker's shared enabled-flag file so a driving
    video fully owns the device. ``sock_factory`` is injectable for tests.
    """

    def __init__(self, host: str, port: int, *, genau_enabled_file,
                 sock_factory=None):
        self._host = host
        self._port = port
        self._genau_file = Path(genau_enabled_file)
        self._sock_factory = sock_factory or (
            lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        )
        self._sink: UdpTCodeSink | None = None
        self._prior_genau: bool | None = None
        self._send_error_logged = False

    def send_position(self, pos_0_100: float, interval_ms: float) -> None:
        """Move the stroke axis to ``pos_0_100`` over ``interval_ms``."""
        self._send(format_position(pos_0_100, interval_ms))

    def park(self) -> None:
        """Send the device to its resting position."""
        self._send(PARK_TCODE)

    def pause_genau(self) -> None:
        """Disable genau auto-mode, remembering its prior state to restore later."""
        self._prior_genau = read_flag(self._genau_file, default=True)
        self._write_genau(False)

    def restore_genau(self) -> None:
        """Put genau's enabled flag back to what it was before :meth:`pause_genau`."""
        if self._prior_genau is None:
            return
        self._write_genau(self._prior_genau)
        self._prior_genau = None

    def close(self) -> None:
        if self._sink is not None:
            try:
                self._sink.close()
            except OSError:
                pass
            self._sink = None

    def _send(self, line: str) -> None:
        # The family's datagram sink, over a socket made on first use so a
        # broker built for a session that never drives opens nothing.
        try:
            if self._sink is None:
                self._sink = UdpTCodeSink(self._host, self._port, sock=self._sock_factory())
            self._sink.send(line)
        except OSError as e:  # nobody listening / socket gone — harmless, but surface it once
            if not self._send_error_logged:
                self._send_error_logged = True
                logger.warning("OSR2 UDP send to %s:%s failed: %s", self._host, self._port, e)

    def _write_genau(self, value: bool) -> None:
        # The state directory is the broker's to make, not this app's: a
        # flag written into a directory nobody else has is a flag nobody reads.
        if not self._genau_file.parent.exists():
            logger.debug("OSR2 state dir missing; not writing genau flag")
            return
        if not write_flag(self._genau_file, value):
            logger.warning("Failed to write genau flag %s", self._genau_file)
