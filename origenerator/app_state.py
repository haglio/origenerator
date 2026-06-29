"""Persist small bits of UI state (open tabs, gallery folder) across launches.

A thin JSON-backed key/value store kept deliberately Qt-free so the persistence
logic is unit-testable on its own. Lives next to the generations database in the
gitignored ``state/`` directory.
"""

from __future__ import annotations

import json
from pathlib import Path


class AppState:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._data = self._load()

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
        """Write the state to disk, replacing the file atomically."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        tmp.replace(self.path)
