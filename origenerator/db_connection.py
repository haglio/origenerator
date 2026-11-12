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
        self._own: sqlite3.Connection | None = None
        self._owning = threading.RLock()
        self._seen_others_at: int | None = None
        self._told_of_writes: list = []

    @contextmanager
    def connect(self, *, tells_of_writes: bool = True):
        with self._owning:
            conn = self._own_connection()
            before = conn.total_changes
            with conn:
                yield conn
            written = conn.total_changes != before
        if written and tells_of_writes:
            for told in list(self._told_of_writes):
                told()

    def when_written(self, told) -> None:
        self._told_of_writes.append(told)

    def _own_connection(self) -> sqlite3.Connection:
        if self._own is None:
            self._own = sqlite3.connect(self.path, check_same_thread=False)
            self._own.row_factory = sqlite3.Row
            weakref.finalize(self, self._own.close)
        return self._own

    def version(self) -> int:
        with self._watching:
            if self._watcher is None:
                self._watcher = sqlite3.connect(self.path, check_same_thread=False)
                weakref.finalize(self, self._watcher.close)
            return self._watcher.execute("PRAGMA data_version").fetchone()[0]

    def log_own_changes(self, table: str, key: str) -> ChangeLog:
        return ChangeLog(self, table, key)

    def others_wrote_since_last_asked(self, conn: sqlite3.Connection) -> bool:
        # SQLite: a connection's data_version moves only for commits made on other connections
        version = conn.execute("PRAGMA data_version").fetchone()[0]
        others_wrote = version != self._seen_others_at
        self._seen_others_at = version
        return others_wrote


class ChangeLog:
    def __init__(self, file: SqliteFile, table: str, key: str):
        self._file = file
        self._log = f"own_changes_to_{table}"
        with file.connect() as conn:
            conn.executescript(f"""
                CREATE TEMP TABLE {self._log} ({key} TEXT);
                CREATE TEMP TRIGGER {self._log}_added AFTER INSERT ON main.{table}
                    BEGIN INSERT INTO {self._log} VALUES (NEW.{key}); END;
                CREATE TEMP TRIGGER {self._log}_changed AFTER UPDATE ON main.{table}
                    BEGIN INSERT INTO {self._log} VALUES (OLD.{key}), (NEW.{key}); END;
                CREATE TEMP TRIGGER {self._log}_removed AFTER DELETE ON main.{table}
                    BEGIN INSERT INTO {self._log} VALUES (OLD.{key}); END;
            """)

    def changed_since_last_asked(self) -> set[str] | None:
        with self._file.connect(tells_of_writes=False) as conn:
            others_wrote = self._file.others_wrote_since_last_asked(conn)
            changed = {row[0] for row in conn.execute(f"SELECT * FROM {self._log}")}
            conn.execute(f"DELETE FROM {self._log}")
        return None if others_wrote else changed


class Store:
    def __init__(self, file: SqliteFile):
        self._connect = file.connect
