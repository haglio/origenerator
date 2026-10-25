"""Talk to the OSR2 device through the broker sibling.

The broker owns the device, on whichever serial port its USB socket is given, and
hands it the T-code of the one sender holding its slot (``app_support.osr2_slot``),
so origenerator drives the device by holding that slot while a driver drives and
streaming T-code into it in sync with a playing video. The device's own auto mode
wins over that: while it runs, the broker drops what arrives.

Everything is best-effort: a slot nobody listens on is dialed again a moment
later, so the app behaves the same whether or not the broker is running.
"""

from __future__ import annotations

from pathlib import Path

from app_support import osr2_device
from app_support.osr2_hold import ask_the_broker
from app_support.osr2_slot import Osr2Sender
from funestra.tcode import format_tcode_command, to_tcode_position

from origenerator.config import project_dir

SENDER = "origenerator"
# Not this app's state directory and not the broker's own checkout: the one
# directory all three apps meet at, which the broker -- whose files they are --
# names in its published broker_contract.json. Spelled here as well because this
# app is told it by nothing, and tests/test_broker_contract.py is what holds the
# two spellings together.
SHARED_STATE_DIR = project_dir("fun_time") / "state"


def _state_dir(state_dir) -> Path:
    return Path(state_dir) if state_dir is not None else SHARED_STATE_DIR


def device_mode(*, now: float | None = None, state_dir=None) -> osr2_device.Osr2Mode:
    return osr2_device.mode(_state_dir(state_dir), now=now)


def device_trouble(*, now: float | None = None,
                   state_dir=None) -> osr2_device.Osr2Trouble | None:
    return osr2_device.trouble(_state_dir(state_dir), now=now)


def format_position(pos_0_100: float, interval_ms: float) -> str:
    """A T-code move for the L0 motion axis: ``L0<0000-9999>I<ms>``.

    ``pos_0_100`` is a funscript position (0 floor, 100 top); ``interval_ms`` is
    how long the device takes to get there, so streaming each action with the
    time until the next reads as smooth motion.  The scaling and the clamp are
    funestra's, the same ones every other driver in the family sends with.
    """
    return format_tcode_command("L0", to_tcode_position(pos_0_100), int(interval_ms))


class Osr2Broker:
    """The app's way to the OSR2: the broker's slot, held while a driver drives,
    and the broker's command file for its holds."""

    def __init__(self, *, port: int | None = None, state_dir: Path = SHARED_STATE_DIR):
        self._sender = Osr2Sender(SENDER, port=port)
        self._state_dir = Path(state_dir)

    def want(self, wanted: bool) -> None:
        self._sender.want(wanted)

    def send_position(self, pos_0_100: float, interval_ms: float) -> None:
        """Move the motion axis to ``pos_0_100`` over ``interval_ms``."""
        self._sender.send(format_position(pos_0_100, interval_ms))

    def ask(self, verb: str) -> None:
        ask_the_broker(self._state_dir, verb)

    def close(self) -> None:
        self._sender.close()
