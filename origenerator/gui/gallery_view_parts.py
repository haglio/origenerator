from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtWidgets import QWidget

from origenerator.evolver_export import EvolverInbox
from origenerator.gallery_names_file import NamesFile
from origenerator.gui.published_names import PublishedNames
from origenerator.gui.two_screens import TwoScreens
from origenerator.osr2_motion_driver import Osr2MotionDriver
from origenerator.radio import OrigeneratorRadio


@dataclass(frozen=True)
class Shared:
    osr2_motion: Osr2MotionDriver | None = None
    radio: OrigeneratorRadio | None = None
    prompt_heights: object = None
    inbox: EvolverInbox | None = None
    publish_names: Callable[[dict[str, str]], None] = field(
        default_factory=lambda: PublishedNames(NamesFile()).publish)
    device_waits_for_the_window: bool = False
    two_screens: TwoScreens | None = None
    app_title: QWidget | None = None


NO_SHARED = Shared()
