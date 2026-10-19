from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PyQt6.QtCore import pyqtSignal

from origenerator.gui.pictured_dropdown import PICTURES_ROLE, PicturedDropdown


@dataclass(frozen=True)
class RecentVideo:
    prompt_id: str
    thumbnail: str | None
    size = None


class RecentVideos(PicturedDropdown):
    picked = pyqtSignal(str)

    def __init__(self, recent: Callable[[], list[RecentVideo]], parent=None):
        super().__init__(parent, gray=True)
        self._recent = recent
        self.setPlaceholderText("Recent")
        self.activated.connect(self._on_activated)

    def refresh(self) -> None:
        self._list_rows(("", (video,)) for video in self._recent())

    def _on_activated(self, row: int) -> None:
        video = self.itemData(row, PICTURES_ROLE)[0]
        self.setCurrentIndex(-1)
        self.picked.emit(video.prompt_id)

    def showPopup(self):
        self.refresh()
        super().showPopup()
