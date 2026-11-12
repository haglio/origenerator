from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from origenerator import gallery_names_file
from origenerator.evolver_export import EvolverInbox
from origenerator.osr2_motion_driver import Osr2MotionDriver
from origenerator.radio import OrigeneratorRadio


@dataclass(frozen=True)
class Shared:
    osr2_motion: Osr2MotionDriver | None = None
    radio: OrigeneratorRadio | None = None
    prompt_heights: object = None
    inbox: EvolverInbox | None = None
    publish_names: Callable[[dict[str, str]], None] = gallery_names_file.publish


NO_SHARED = Shared()
