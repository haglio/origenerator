"""The database file, and the one way this package opens it.

`db.py` is a 626-line class holding the schema, the connection policy and every
query for six unrelated tables. The queries are coming out one table to a
module; what every one of them shares is exactly this — the file, and how a
connection to it is opened, used and closed.
"""
from __future__ import annotations

import sqlite3
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

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

