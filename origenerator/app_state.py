from __future__ import annotations

import copy
import json
from pathlib import Path


class AppState:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._data = self._load()
        self._last_written: str | None = None
        self._last_saved: dict | None = None

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

    def save(self) -> None:
        if self._data == self._last_saved:
            return
        text = json.dumps(self._data, indent=2)
        if text != self._last_written:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(self.path)
            self._last_written = text
        self._last_saved = copy.deepcopy(self._data)
