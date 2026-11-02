from __future__ import annotations

from pathlib import Path

from app_support import osr2_device
from app_support.osr2_hold import ask_the_broker
from app_support.osr2_slot import Osr2Sender
from funestra import broker
from funestra.tcode import format_tcode_command, to_tcode_position

from origenerator.config import project_dir

SENDER = "origenerator"
SHARED_STATE_DIR = project_dir("fun_time") / "state"


def _state_dir(state_dir) -> Path:
    return Path(state_dir) if state_dir is not None else SHARED_STATE_DIR


def device_mode(*, now: float | None = None, state_dir=None) -> osr2_device.Osr2Mode:
    return osr2_device.mode(_state_dir(state_dir), now=now)


def device_trouble(*, now: float | None = None,
                   state_dir=None) -> osr2_device.Osr2Trouble | None:
    return osr2_device.trouble(_state_dir(state_dir), now=now)


def broker_running(*, now: float | None = None, state_dir=None) -> bool:
    return broker.is_running(_state_dir(state_dir), now=now)


def press_the_broker(*, state_dir=None, checkout: Path | None = None) -> None:
    checkout = project_dir("broker") if checkout is None else checkout
    broker.press(_state_dir(state_dir), broker.tray_launcher_in(checkout))


def format_position(pos_0_100: float, interval_ms: float) -> str:
    return format_tcode_command("L0", to_tcode_position(pos_0_100), int(interval_ms))


class Osr2Broker:
    def __init__(self, *, port: int | None = None, state_dir: Path = SHARED_STATE_DIR):
        self._sender = Osr2Sender(SENDER, port=port)
        self._state_dir = Path(state_dir)

    def want(self, wanted: bool) -> None:
        self._sender.want(wanted)

    def send_position(self, pos_0_100: float, interval_ms: float) -> None:
        self._sender.send(format_position(pos_0_100, interval_ms))

    def ask(self, verb: str) -> None:
        ask_the_broker(self._state_dir, verb)

    def close(self) -> None:
        self._sender.close()
