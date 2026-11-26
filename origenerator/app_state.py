from __future__ import annotations

import copy
import json
import threading
from collections.abc import Callable
from pathlib import Path

from app_support.file_channel import write_whole


class AppState:
    def __init__(self, path: Path, *, write: Callable[[Path, str], None] = write_whole):
        self.path = Path(path)
        self._write_whole = write
        self._data = self._load()
        self._last_written: str | None = None
        self._last_saved: dict | None = None
        self._saves = self._written = 0
        self._writing = threading.Lock()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        self._data[key] = value

    def save(self, *, hand_off: Callable[[Callable[[], None]], None] | None = None) -> None:
        if self._data == self._last_saved:
            return
        text = json.dumps(self._data, indent=2)
        self._last_saved = copy.deepcopy(self._data)
        self._saves += 1
        made = self._saves

        def write() -> None:
            self._write(made, text)
        (hand_off or (lambda run: run()))(write)

    def _write(self, made: int, text: str) -> None:
        with self._writing:
            if made <= self._written or text == self._last_written:
                return
            try:
                self._write_whole(self.path, text)
            except OSError:
                self._last_saved = None
                raise
            self._last_written, self._written = text, made
