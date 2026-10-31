from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from PyQt6.QtCore import QObject

from origenerator.gui.hud_nav_map import NavMapNeighbors
from origenerator.gui.off_thread import run_off_thread


@dataclass(frozen=True)
class RegionOpening:
    rows: list[dict]
    items: list
    versions: dict
    enhanced_ids: set[str]
    scripts: dict[str, Path | None]
    lead: int = 0
    lead_neighbors: NavMapNeighbors | None = None


class RegionOpenings(QObject):
    def __init__(self, rows_of: Callable[[str], list[dict]],
                 make: Callable[[list[dict]], RegionOpening],
                 finish: Callable[[RegionOpening, str], RegionOpening], parent=None) -> None:
        super().__init__(parent)
        self._rows_of = rows_of
        self._make = make
        self._finish = finish
        self._ready: dict[str, RegionOpening] = {}
        self._making: set[str] = set()
        self._asked_again: set[str] = set()

    def of(self, side: str) -> RegionOpening | None:
        return self._ready.get(side)

    def library_moved(self) -> None:
        self._ready.clear()
        self._asked_again.update(self._making)

    def make_ready(self, side: str) -> None:
        if side in self._making:
            self._asked_again.add(side)
            return
        self._making.add(side)
        rows = self._rows_of(side)
        run_off_thread(partial(self._make, rows), partial(self._made, side), owner=self)

    def _made(self, side: str, opening: RegionOpening | None) -> None:
        self._making.discard(side)
        if side in self._asked_again:
            self._asked_again.discard(side)
            self.make_ready(side)
        elif opening is not None and opening.items:
            self._ready[side] = self._finish(opening, side)
