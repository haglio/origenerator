from __future__ import annotations

from collections.abc import Callable

from funestra.funestra_verbs import JUMP_TO_FUNSCRIPT, SEEK_BACK, SEEK_FWD, set_speed
from funestra.hud_controls import longer_than_a_step
from funestra.playback_rate import NORMAL_RATE
from funestra.status import FunestraStatus


class FunestraTransport:
    def __init__(self, *, send: Callable[[str], None], publish: Callable[[], None],
                 at_defaults: Callable[[], bool]) -> None:
        self._send = send
        self._publish = publish
        self._at_defaults = at_defaults
        self._duration_ms = 0
        self._image = False
        self._speed = NORMAL_RATE
        self._has_funscript = False
        self._has_osr2 = False

    def heard(self, status: FunestraStatus, fields: dict) -> None:
        self._duration_ms = status.duration_ms
        self._image = status.image
        self._speed = status.speed
        self._has_funscript = fields.get("has_funscript") == "1"

    def nudge(self, delta: int) -> None:
        self._send(SEEK_FWD if delta > 0 else SEEK_BACK)

    def funscript_jump(self) -> None:
        self._send(JUMP_TO_FUNSCRIPT)

    def back_to_normal_speed(self) -> None:
        self._send(set_speed(NORMAL_RATE))

    def set_has_osr2(self, has_it: bool) -> None:
        if has_it != self._has_osr2:
            self._has_osr2 = has_it
            self._publish()

    @property
    def has_osr2(self) -> bool:
        return self._has_osr2

    def row_facts(self) -> dict:
        return {"longer_than_a_step": longer_than_a_step(self._duration_ms),
                "image": self._image,
                "has_funscript": self._has_funscript,
                "nothing_to_reset": self._at_defaults() and self._speed == NORMAL_RATE}
