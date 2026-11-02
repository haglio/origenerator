from __future__ import annotations

import sqlite3
import threading
import weakref
from contextlib import contextmanager
from pathlib import Path


class SqliteFile:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._watcher: sqlite3.Connection | None = None
        self._watching = threading.Lock()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def version(self) -> int:
        with self._watching:
            if self._watcher is None:
                self._watcher = sqlite3.connect(self.path, check_same_thread=False)
                weakref.finalize(self, self._watcher.close)
            return self._watcher.execute("PRAGMA data_version").fetchone()[0]



class Store:
    def __init__(self, file: SqliteFile):
        self._connect = file.connect
