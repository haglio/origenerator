from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path

_ANSWERS: ContextVar[dict | None] = ContextVar("answers", default=None)


@contextmanager
def one_look() -> Iterator[None]:
    token = _ANSWERS.set(_ANSWERS.get() if _ANSWERS.get() is not None else {})
    try:
        yield
    finally:
        _ANSWERS.reset(token)


def looking_once(asked):
    @wraps(asked)
    def answered(*args, **kwargs):
        with one_look():
            return asked(*args, **kwargs)
    return answered


def once_a_look(asked):
    @wraps(asked)
    def answered(*args):
        answers = _ANSWERS.get()
        if answers is None:
            return asked(*args)
        if (asked, args) not in answers:
            answers[asked, args] = asked(*args)
        return answers[asked, args]
    return answered


def is_file(path) -> bool:
    path = Path(path)
    if _ANSWERS.get() is None:
        return path.is_file()
    entry = entries_in(path.parent).get(os.path.normcase(path.name))
    return entry is not None and entry.is_file()


def stat_of(path) -> os.stat_result:
    path = Path(path)
    if _ANSWERS.get() is None:
        return path.stat()
    entry = entries_in(path.parent).get(os.path.normcase(path.name))
    if entry is None:
        raise FileNotFoundError(path)
    return entry.stat()


def entries_in(folder) -> dict[str, os.DirEntry]:
    return _listing(Path(folder))


@once_a_look
def _listing(folder: Path) -> dict[str, os.DirEntry]:
    try:
        with os.scandir(folder) as entries:
            return {os.path.normcase(entry.name): entry for entry in entries}
    except OSError:
        return {}
