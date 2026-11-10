from __future__ import annotations

from collections.abc import Callable


class RowReadings:
    def __init__(self, before: RowReadings | None = None):
        self._before = before.readings_now() if before is not None else {}
        self._now: dict[str, tuple[object, dict[int, tuple[dict, object]]]] = {}

    def readings_now(self) -> dict[str, tuple[object, dict[int, tuple[dict, object]]]]:
        return self._now

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
