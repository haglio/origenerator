from __future__ import annotations

from dataclasses import dataclass

from origenerator.osr2_motion_driver import Osr2MotionDriver
from origenerator.radio import OrigeneratorRadio


@dataclass(frozen=True)
class Shared:
    osr2_motion: Osr2MotionDriver | None = None
    radio: OrigeneratorRadio | None = None
    prompt_heights: object = None
    phone_records: object = None


NO_SHARED = Shared()
