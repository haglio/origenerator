"""The database file, and the one way this package opens it."""
from __future__ import annotations

import sqlite3
import threading
import weakref
from contextlib import contextmanager
from pathlib import Path


class SqliteFile:
    """One sqlite database on disk.

    ``connect`` commits on the way out, and always closes. Closing is what the
    plain ``with sqlite3.connect(...)`` this replaced never did -- that one
    commits and then leaves the connection to the garbage collector, which on
    Windows keeps the file open long enough for the next rename or replace of it
    to be refused (see :mod:`origenerator.db_salvage`).
    """

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
        """Changes whenever anything commits to the file: SQLite's
        ``data_version``, read on a connection that never writes."""
        with self._watching:
            if self._watcher is None:
                self._watcher = sqlite3.connect(self.path, check_same_thread=False)
                weakref.finalize(self, self._watcher.close)
            return self._watcher.execute("PRAGMA data_version").fetchone()[0]



class Store:
    """A group of queries over one table of a :class:`SqliteFile`.

    Whole on its own: ``DeletionStore(SqliteFile(path))`` is a working object, so
    a unit that touches one table can be handed that table rather than the whole
    database. Making the file and its schema is not a store's job -- that is the
    whole database's, and :class:`origenerator.db.Database` does it once.
    """

    def __init__(self, file: SqliteFile):
        self._connect = file.connect
