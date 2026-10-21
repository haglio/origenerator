from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QMovie, QPixmap

from origenerator.gui.looping_preview import looping_movie
from origenerator.gui.pictured_dropdown import PICTURES_ROLE, PicturedDropdown
from origenerator.gui.thumbnail_box import THUMBNAIL_BOX


@dataclass(frozen=True)
class RecentVideo:
    prompt_id: str
    thumbnail: str | None
    movie: str | None = None
    size = None


class RecentVideos(PicturedDropdown):
    picked = pyqtSignal(str)

    def __init__(self, recent: Callable[[], list[RecentVideo]], parent=None):
        super().__init__(parent, gray=True)
        self._recent = recent
        self._rows: dict[str, int] = {}
        self.setPlaceholderText("Recent")
        self.activated.connect(self._on_activated)

    def refresh(self) -> None:
        self._stop_playing()
        videos = self._recent()
        self._rows = {video.prompt_id: row for row, video in enumerate(videos)}
        self._list_rows(("", (video,)) for video in videos)

    def _on_activated(self, row: int) -> None:
        video = self.itemData(row, PICTURES_ROLE)[0]
        self.setCurrentIndex(-1)
        self.picked.emit(video.prompt_id)

    def showPopup(self):
        self.refresh()
        super().showPopup()

    def hidePopup(self):
        super().hidePopup()
        self._stop_playing()

    def _frame_of(self, video: RecentVideo) -> QPixmap | None:
        movie = self.findChild(QMovie, video.prompt_id) or self._play(video)
        frame = movie.currentPixmap() if movie is not None else None
        return frame if frame is not None and not frame.isNull() else None

    def _play(self, video: RecentVideo) -> QMovie | None:
        row = self._rows.get(video.prompt_id)
        if row is None or not video.movie or not Path(video.movie).exists():
            return None
        movie = looping_movie(video.movie, THUMBNAIL_BOX, self)
        movie.setObjectName(video.prompt_id)
        movie.frameChanged.connect(lambda _frame: self.view().update(self.model().index(row, 0)))
        return movie

    def _stop_playing(self) -> None:
        for movie in self.findChildren(QMovie):
            movie.stop()
            movie.setObjectName("")
            movie.deleteLater()
