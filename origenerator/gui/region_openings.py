from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path

from PySide6.QtCore import QObject

from origenerator.gui.hud_nav_map import NavMapNeighbors
from origenerator.gui.off_thread import run_off_thread


@dataclass(frozen=True)
class RegionOpening:
    rows: list[dict]
    items: list
    versions: dict
    scripts: dict[str, Path | None]
    lead: int = 0
    lead_neighbors: NavMapNeighbors | None = None
    location: str | None = None


class RegionOpenings(QObject):
    def __init__(self, rows_at: Callable[[str], list[dict]],
                 make: Callable[[list[dict]], RegionOpening],
                 finish: Callable[[RegionOpening, str], RegionOpening], *,
                 made: Callable[[str], None] = lambda _side: None, parent=None) -> None:
        super().__init__(parent)
        self._rows_at = rows_at
        self._make = make
        self._finish = finish
        self._then = made
        self._ready: dict[str, RegionOpening] = {}
        self._wanted_at: dict[str, str] = {}
        self._making: set[str] = set()
        self._asked_again: set[str] = set()

    def of(self, side: str, location: str) -> RegionOpening | None:
        ready = self._ready.get(side)
        return ready if ready is not None and ready.location == location else None

    def making(self, side: str) -> bool:
        return side in self._making

    def library_moved(self) -> None:
        self._ready.clear()
        self._asked_again.update(self._making)

    def make_ready(self, side: str, location: str) -> None:
        if side in self._making:
            if self._wanted_at.get(side) != location:
                self._asked_again.add(side)
            self._wanted_at[side] = location
            return
        self._wanted_at[side] = location
        self._making.add(side)
        run_off_thread(partial(self._made_at, location), partial(self._made, side, location),
                       owner=self)

    def _made_at(self, location: str) -> RegionOpening:
        return replace(self._make(self._rows_at(location)), location=location)

    def _made(self, side: str, location: str, opening: RegionOpening | None) -> None:
        self._making.discard(side)
        if side in self._asked_again or self._wanted_at.get(side) != location:
            self._asked_again.discard(side)
            self.make_ready(side, self._wanted_at[side])
            return
        if opening is not None and opening.items:
            self._ready[side] = self._finish(opening, side)
        self._then(side)
