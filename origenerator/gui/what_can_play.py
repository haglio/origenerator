from __future__ import annotations

from collections.abc import Callable, Sequence


def _the_same_rows(rows: Sequence[dict], others: Sequence[dict]) -> bool:
    return len(rows) == len(others) and all(
        row is other for row, other in zip(rows, others, strict=True))


class WhatCanPlay:
    def __init__(self, file_of: Callable[[dict], object]):
        self._file_of = file_of
        self._played_last: dict | None = None
        self._nothing_in: tuple[dict, ...] | None = None

    def anything_in(self, rows: Sequence[dict]) -> bool:
        if self._still_plays(self._played_last, rows):
            return True
        if self._nothing_in is not None and _the_same_rows(rows, self._nothing_in):
            return False
        found = next((row for row in rows if self._file_of(row) is not None), None)
        self._played_last = found
        self._nothing_in = tuple(rows) if found is None else None
        return found is not None

    def _still_plays(self, row: dict | None, rows: Sequence[dict]) -> bool:
        return (row is not None and any(listed is row for listed in rows)
                and self._file_of(row) is not None)
