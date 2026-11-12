from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from origenerator.gui.generation_job import JobState
from origenerator.gui.inflight import InFlightItem, RunReading


class StartingRows(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: dict[str, InFlightItem] = {}
        self._shown = 0

    def show(self, **what) -> str:
        self._shown += 1
        key = f"starting-{self._shown}"
        self._rows[key] = InFlightItem(key=key, reading=RunReading(status=JobState.QUEUED),
                                       reveal=lambda: None, starting=True, **what)
        self.changed.emit()
        return key

    def drop(self, key: str | None) -> None:
        if key is not None and self._rows.pop(key, None) is not None:
            self.changed.emit()

    def rows(self) -> list[InFlightItem]:
        return list(self._rows.values())

    def placed_among(self, items: list, line) -> list:
        placed = list(items)
        for row in self._rows.values():
            before = line.joins_before(row.media_type)
            placed.insert(next((at for at, item in enumerate(placed) if item.key == before),
                               len(placed)), row)
        return placed
