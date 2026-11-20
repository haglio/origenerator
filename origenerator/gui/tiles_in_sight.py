from __future__ import annotations

from bisect import bisect_left, bisect_right

from PySide6.QtCore import QPoint

from origenerator.gui.flow_layout import FlowLayout


class TilesInSight:
    def __init__(self) -> None:
        self._placed_as: tuple | None = None
        self._tops: list[int] = []
        self._by_top: list = []
        self._tallest = 0
        self._told: set = set()

    def follow(self, drawn, tiles, top: int, foot: int) -> None:
        placed_as = _placed_as(drawn, tiles)
        if placed_as is None or placed_as != self._placed_as:
            self._place(drawn, tiles)
            self._placed_as = placed_as
            self._tell(self._within(top, foot), everyone=True)
            return
        self._tell(self._within(top, foot), everyone=False)

    def _place(self, drawn, tiles) -> None:
        placed = sorted(((tile.mapTo(drawn, QPoint(0, 0)).y(), n, tile)
                         for n, tile in enumerate(tiles)), key=lambda place: place[:2])
        self._tops = [at for at, _n, _tile in placed]
        self._by_top = [(at, tile) for at, _n, tile in placed]
        self._tallest = max((tile.height() for _at, tile in self._by_top), default=0)

    def _within(self, top: int, foot: int) -> set:
        first = bisect_right(self._tops, top - self._tallest)
        last = bisect_left(self._tops, foot)
        return {tile for at, tile in self._by_top[first:last] if at + tile.height() > top}

    def _tell(self, in_sight: set, *, everyone: bool) -> None:
        if everyone:
            for _at, tile in self._by_top:
                tile.set_in_sight(tile in in_sight)
        else:
            for tile in self._told - in_sight:
                tile.set_in_sight(False)
            for tile in in_sight - self._told:
                tile.set_in_sight(True)
        self._told = in_sight


def _placed_as(drawn, tiles) -> tuple | None:
    flow = drawn.layout()
    if not isinstance(flow, FlowLayout):
        return None
    return drawn, flow.times_placed, len(tiles)
