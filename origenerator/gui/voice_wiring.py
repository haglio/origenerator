from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from origenerator.gui.starting_rows import StartingRows


@dataclass(frozen=True)
class VoiceSources:
    db: object
    slideshows: object
    client: object
    starting: StartingRows
    jobs: object = None
    requests: object = None
    setters: object = None


@dataclass(frozen=True)
class VoiceSwitches:
    populate: QWidget | None
    radio: QWidget | None
    drive: QWidget | None
    mic: QWidget | None
