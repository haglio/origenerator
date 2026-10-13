"""Talk to the OSR2 device through the broker sibling.

The broker owns the device (real serial ``COM4``) and forwards raw T-code sent to
its UDP listener straight to it, suppressing MultiFunPlayer for a moment so the two
don't fight (``osr2_broker/session.py``). So origenerator drives the device simply
by streaming T-code here in sync with a playing video.  The device's own auto
mode wins over that: while it runs, the broker drops what arrives here.

Everything is best-effort: UDP to nobody is a harmless no-op, so the app behaves
the same whether or not the broker is running.
"""

from __future__ import annotations

import logging
import socket
from pathlib import Path

from app_support import osr2_device, ports
from funestra.tcode import (
    PARK_COMMAND,
    UdpTCodeSink,
    format_tcode_command,
    to_tcode_position,
)
from PyQt6.QtCore import QTimer

from origenerator.config import project_dir

logger = logging.getLogger(__name__)

# The device's rest command -- motion axis to the floor over half a second, the
# family's one spelling of it, which the broker parks with too -- so a stopped
# video leaves the OSR2 where the broker expects it.
PARK_TCODE = PARK_COMMAND
# The broker's own wait before an OmniPause park (osr2_broker.hold's
# HoldScheduler.DELAY_SECONDS): a room that plays again inside it is never parked.
PARK_SETTLE_MS = 1000

BROKER_HOST = "127.0.0.1"
TCODE_UDP_PORT = ports.TCODE_UDP
# Not this app's state directory and not the broker's own checkout: the one
# directory all three apps meet at, which the broker -- whose files they are --
# names in its published broker_contract.json. Spelled here as well because this
# app is told it by nothing, and tests/test_broker_contract.py is what holds the
# two spellings together.
SHARED_STATE_DIR = project_dir("fun_time") / "state"


def device_mode(*, now: float | None = None, state_dir=None) -> osr2_device.Osr2Mode:
    return osr2_device.mode(
        Path(state_dir) if state_dir is not None else SHARED_STATE_DIR, now=now)


def format_position(pos_0_100: float, interval_ms: float) -> str:
    """A T-code move for the L0 motion axis: ``L0<0000-9999>I<ms>``.

    ``pos_0_100`` is a funscript position (0 floor, 100 top); ``interval_ms`` is
    how long the device takes to get there, so streaming each action with the
    time until the next reads as smooth motion.  The scaling and the clamp are
    funestra's, the same ones every other driver in the family sends with.
    """
    return format_tcode_command("L0", to_tcode_position(pos_0_100), int(interval_ms))


class Osr2Broker:
    """A thin UDP client to the broker's T-code listener.

    Holds one datagram socket for streaming motion positions.  ``sock_factory`` is
    injectable for tests.
    """

    def __init__(self, host: str = BROKER_HOST, port: int = TCODE_UDP_PORT, *,
                 sock_factory=None):
        self._host = host
        self._port = port
        self._sock_factory = sock_factory or (
            lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        )
        self._sink: UdpTCodeSink | None = None
        self._send_error_logged = False

    def send_position(self, pos_0_100: float, interval_ms: float) -> None:
        """Move the motion axis to ``pos_0_100`` over ``interval_ms``."""
        self._send(format_position(pos_0_100, interval_ms))

    def park(self) -> None:
        """Send the device to its resting position."""
        self._send(PARK_TCODE)

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


def park_once_settled(broker, parent) -> QTimer:
    timer = QTimer(parent)
    timer.setSingleShot(True)
    timer.setInterval(PARK_SETTLE_MS)
    timer.timeout.connect(lambda: _park_for_the_pause(broker))
    return timer


def _park_for_the_pause(broker) -> None:
    broker.park()
    logger.info("OSR2 parked: the room is paused")
