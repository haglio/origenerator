from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path

_LISTINGS: ContextVar[dict[Path, dict[str, os.DirEntry]] | None] = ContextVar(
    "listings", default=None)


@contextmanager
def one_look() -> Iterator[None]:
    token = _LISTINGS.set(_LISTINGS.get() if _LISTINGS.get() is not None else {})
    try:
        yield
    finally:
        _LISTINGS.reset(token)


def looking_once(asked):
    @wraps(asked)
    def answered(*args, **kwargs):
        with one_look():
            return asked(*args, **kwargs)
    return answered


def is_file(path) -> bool:
    path = Path(path)
    if _LISTINGS.get() is None:
        return path.is_file()
    entry = entries_in(path.parent).get(os.path.normcase(path.name))
    return entry is not None and entry.is_file()


def entries_in(folder) -> dict[str, os.DirEntry]:
    listings = _LISTINGS.get()
    folder = Path(folder)
    if listings is None:
        return _listing(folder)
    if folder not in listings:
        listings[folder] = _listing(folder)
    return listings[folder]


def _listing(folder: Path) -> dict[str, os.DirEntry]:
    try:
        with os.scandir(folder) as entries:
            return {os.path.normcase(entry.name): entry for entry in entries}
    except OSError:
        return {}
