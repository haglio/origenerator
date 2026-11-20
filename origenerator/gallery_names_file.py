from __future__ import annotations

import json
from pathlib import Path

from app_support.file_channel import read_whole, write_whole

from origenerator.config import LIBRARY_STATE_DIR

GALLERY_NAMES_FILE = "gallery_names.json"
GALLERY_NAMES_PATH = LIBRARY_STATE_DIR / GALLERY_NAMES_FILE


class NamesFile:
    def __init__(self, path: Path = GALLERY_NAMES_PATH, *, read=read_whole,
                 write=write_whole) -> None:
        self._path = path
        self._read = read
        self._write = write
        self._written: str | None = None
        self._looked = False

    def publish(self, names_by_file: dict[str, str]) -> None:
        text = json.dumps(names_by_file, sort_keys=True)
        if not self._looked:
            self._written = self._published()
            self._looked = True
        if text != self._written:
            self._write(self._path, text)
            self._written = text

    def _published(self) -> str | None:
        try:
            return self._read(self._path)
        except FileNotFoundError:
            return None
