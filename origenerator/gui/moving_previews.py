from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from origenerator import gallery
from origenerator.gui.off_thread import run_off_thread
from origenerator.media import MediaType
from origenerator.output_places import OutputPlaces


class MovingPreviews(QObject):
    made = pyqtSignal(str, str)

    def __init__(self, places: OutputPlaces, thumb_dir: Path, *, run=run_off_thread,
                 make=None, parent: QObject | None = None):
        super().__init__(parent)
        self._places, self._thumb_dir = places, thumb_dir
        self._run, self._make = run, make or _made_by_the_gallery
        self._asked: set[str] = set()
        self._waiting: list[dict] = []
        self._making = False

    def of(self, row: dict) -> str | None:
        if self._thumb_dir is None:
            return None
        made = gallery.animated_preview_if_made(row, self._places, self._thumb_dir)
        if made is None and gallery.media_type_of_row(row) == MediaType.VIDEO:
            self._ask(row)
        return made

    def _ask(self, row: dict) -> None:
        if row["prompt_id"] in self._asked:
            return
        self._asked.add(row["prompt_id"])
        self._waiting.append(row)
        self._make_the_next()

    def _make_the_next(self) -> None:
        if self._making or not self._waiting:
            return
        self._making = True
        row = self._waiting.pop()
        places, thumb_dir, make = self._places, self._thumb_dir, self._make
        self._run(lambda: make(row, places, thumb_dir),
                  lambda path: self._made_one(row["prompt_id"], path), owner=self)

    def _made_one(self, prompt_id: str, path: str | None) -> None:
        self._making = False
        if path:
            self.made.emit(prompt_id, path)
        self._make_the_next()


def _made_by_the_gallery(row: dict, places: OutputPlaces, thumb_dir: Path) -> str | None:
    return gallery.make_animated_preview(row, places, thumb_dir)
