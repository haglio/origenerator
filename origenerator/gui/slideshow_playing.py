from __future__ import annotations

from dataclasses import dataclass

from origenerator.gui.frame_files import FrameFiles


@dataclass(frozen=True)
class Playing:
    items: object
    start: object = None
    shuffle: object = None
    hud: object = None
    actions: object = None
    versions: object = None
    opening: object = None


@dataclass(frozen=True)
class Seat:
    shape: str
    channel: object
    frames: FrameFiles


@dataclass(frozen=True)
class Hosting:
    pace: object = None
    say: object = None
    shown: object = None
    clock: object = None


NO_HOSTING = Hosting()
