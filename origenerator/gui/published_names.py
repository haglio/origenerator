from __future__ import annotations

from PySide6.QtCore import QObject

from origenerator.gallery_names_file import NamesFile
from origenerator.gui.off_thread import run_off_thread


class PublishedNames(QObject):
    def __init__(self, names_file: NamesFile, *, run=run_off_thread) -> None:
        super().__init__()
        self._file = names_file
        self._run = run
        self._newest: dict[str, str] | None = None
        self._writing = False

    def publish(self, names_by_file: dict[str, str]) -> None:
        self._newest = names_by_file
        if not self._writing:
            self._write_the_newest()

    def _write_the_newest(self, _written=None) -> None:
        names, self._newest = self._newest, None
        self._writing = names is not None
        if names is not None:
            self._run(lambda: self._file.publish(names), self._write_the_newest, owner=self)
