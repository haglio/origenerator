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
from pathlib import Path

logger = logging.getLogger(__name__)

# The device's rest command — stroke axis to the bottom over half a second. Same
# string the broker parks with, so a stopped video leaves the OSR2 where the broker
# expects it.
PARK_TCODE = "L00000I500"


def format_position(pos_0_100: float, interval_ms: float) -> str:
    """A T-code move for the L0 stroke axis: ``L0<0000-9999>I<ms>``.

    ``pos_0_100`` is a funscript position (0 bottom, 100 top), clamped and scaled to
    the axis's four-digit range; ``interval_ms`` is how long the device takes to get
    there, so streaming each action with the time until the next reads as smooth motion.
    """
    pos = max(0.0, min(100.0, pos_0_100))
    magnitude = int(round(pos / 100 * 9999))
    return f"L0{magnitude:04d}I{int(interval_ms)}"


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
        self._sock = None
        self._prior_genau: str | None = None
        self._send_error_logged = False

    def send_position(self, pos_0_100: float, interval_ms: float) -> None:
        """Move the stroke axis to ``pos_0_100`` over ``interval_ms``."""
        self._send(format_position(pos_0_100, interval_ms))

    def park(self) -> None:
        """Send the device to its resting position."""
        self._send(PARK_TCODE)

    def pause_genau(self) -> None:
        """Disable genau auto-mode, remembering its prior state to restore later."""
        self._prior_genau = self._read_genau()
        self._write_genau("0")

    def restore_genau(self) -> None:
        """Put genau's enabled flag back to what it was before :meth:`pause_genau`."""
        if self._prior_genau is None:
            return
        self._write_genau(self._prior_genau)
        self._prior_genau = None

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _send(self, line: str) -> None:
        try:
            if self._sock is None:
                self._sock = self._sock_factory()
            self._sock.sendto((line + "\n").encode("ascii"), (self._host, self._port))
        except OSError as e:  # nobody listening / socket gone — harmless, but surface it once
            if not self._send_error_logged:
                self._send_error_logged = True
                logger.warning("OSR2 UDP send to %s:%s failed: %s", self._host, self._port, e)

    def _read_genau(self) -> str:
        try:
            return self._genau_file.read_text(encoding="utf-8").strip() or "1"
        except OSError:
            return "1"  # broker treats an absent/empty flag as enabled

    def _write_genau(self, value: str) -> None:
        if not self._genau_file.parent.exists():
            logger.debug("OSR2 state dir missing; not writing genau flag")
            return
        try:
            self._genau_file.write_text(value, encoding="utf-8")
        except OSError as e:
            logger.warning("Failed to write genau flag %s: %s", self._genau_file, e)
