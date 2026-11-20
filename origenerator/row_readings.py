from __future__ import annotations

from collections.abc import Callable

_ABSENT = object()
_HOLDS_ANY = object()


class RowReadings:
    def __init__(self, before: RowReadings | None = None):
        self._before = before.readings_now() if before is not None else {}
        self._now: dict[str, tuple[object, dict[int, tuple[dict, object]]]] = {}

    def readings_now(self) -> dict[str, tuple[object, dict[int, tuple[dict, object]]]]:
        return {**self._before, **self._now}

    def of(self, reading: str, work_out: Callable[[dict], object], *,
           depends_on: object = None) -> Callable[[dict], object]:
        read_with, before = self._before.get(reading, (None, {}))
        if read_with is not depends_on:
            before = {}
        now_with, now = self._now.get(reading, (depends_on, {}))
        if now_with is not depends_on:
            now = {}
        self._now[reading] = (depends_on, now)

        def read(row: dict):
            kept = now.get(id(row)) or before.get(id(row))
            if kept is None or kept[0] is not row:
                kept = (row, work_out(row))
            now[id(row)] = kept
            return kept[1]
        return read

    def looking_up(self, reading: str, work_out: Callable[[dict, object], object],
                   index) -> Callable[[dict], object]:
        read_with, before = self._before.get(reading, (None, {}))
        trusted = read_with is index
        now_with, now = self._now.get(reading, (index, {}))
        if now_with is not index:
            now = {}
        self._now[reading] = (index, now)

        def read(row: dict):
            kept = now.get(id(row))
            if kept is None or kept[0] is not row:
                kept = before.get(id(row))
                if (kept is None or kept[0] is not row
                        or not (trusted or _found_the_same(kept[2], index))):
                    lookups = _Lookups(index)
                    kept = (row, work_out(row, lookups), lookups.seen())
                now[id(row)] = kept
            return kept[1]
        return read


class _Lookups:
    def __init__(self, index):
        self._index = index if index is not None else {}
        self._seen: dict | None = {}

    def seen(self) -> dict | None:
        return self._seen

    def get(self, key, default=None):
        found = self._index.get(key, _ABSENT)
        self._note(key, found)
        return default if found is _ABSENT else found

    def __bool__(self) -> bool:
        holds_any = bool(self._index)
        self._note(_HOLDS_ANY, holds_any)
        return holds_any

    def __getitem__(self, key):
        found = self.get(key, _ABSENT)
        if found is _ABSENT:
            raise KeyError(key)
        return found

    def __contains__(self, key) -> bool:
        return self.get(key, _ABSENT) is not _ABSENT

    def __len__(self) -> int:
        self._seen = None
        return len(self._index)

    def __iter__(self):
        self._seen = None
        return iter(self._index)

    def __getattr__(self, name):
        self._seen = None
        return getattr(self._index, name)

    def _note(self, key, found) -> None:
        if self._seen is not None:
            self._seen[key] = found


def _found_the_same(seen: dict | None, index) -> bool:
    if seen is None:
        return False
    index = index if index is not None else {}
    return all((bool(index) if key is _HOLDS_ANY else index.get(key, _ABSENT)) == found
               for key, found in seen.items())
