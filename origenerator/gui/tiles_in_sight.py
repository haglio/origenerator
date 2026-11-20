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
        if placed_as is not None and placed_as == self._placed_as:
            self._tell(self._within(top, foot), everyone=False)
            return
        added = self._added_at_the_end(placed_as, drawn, tiles)
        if added is None:
            self._place(drawn, tiles)
        else:
            self._place_added(drawn, added)
        self._placed_as = placed_as
        self._tell(self._within(top, foot), everyone=added is None, fresh=added or ())

    def _added_at_the_end(self, placed_as, drawn, tiles) -> list | None:
        if placed_as is None or self._placed_as is None:
            return None
        (was_drawn, was_placed, had), (_drawn, _placed, has) = self._placed_as, placed_as
        flow = drawn.layout()
        moved_from = flow.placed_from_since(was_placed)
        if was_drawn is not drawn or has < had or not moved_from:
            return None
        shown = set(tiles)
        return [(flow.itemAt(at).widget(), at) for at in range(moved_from, flow.count())
                if flow.itemAt(at).widget() in shown]

    def _place_added(self, drawn, added: list) -> None:
        placed = sorted((tile.mapTo(drawn, QPoint(0, 0)).y(), at, tile) for tile, at in added)
        moved_from = bisect_left(self._tops, placed[0][0]) if placed else len(self._tops)
        self._tops[moved_from:] = [at for at, _n, _tile in placed]
        self._by_top[moved_from:] = [(at, tile) for at, _n, tile in placed]
        self._tallest = max([self._tallest, *(tile.height() for _at, _n, tile in placed)])

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

    def _tell(self, in_sight: set, *, everyone: bool, fresh=()) -> None:
        if everyone:
            for _at, tile in self._by_top:
                tile.set_in_sight(tile in in_sight)
        else:
            placed_again = {tile for tile, _at in fresh}
            for tile in placed_again:
                tile.set_in_sight(tile in in_sight)
            for tile in self._told - in_sight - placed_again:
                tile.set_in_sight(False)
            for tile in in_sight - self._told - placed_again:
                tile.set_in_sight(True)
        self._told = in_sight


def _placed_as(drawn, tiles) -> tuple | None:
    flow = drawn.layout()
    if not isinstance(flow, FlowLayout):
        return None
    return drawn, flow.times_placed, len(tiles)
