from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtWidgets import QWidget

from origenerator.gui.starting_rows import StartingRows


@dataclass(frozen=True)
class VoiceSources:
    db: object
    slideshows: object
    client: object
    starting: StartingRows


@dataclass(frozen=True)
class VoiceSwitches:
    auto: QWidget | None
    radio: QWidget | None
    drive: QWidget | None
    mic: QWidget | None
