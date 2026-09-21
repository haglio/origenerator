from __future__ import annotations

from dataclasses import dataclass, replace

from PyQt6.QtCore import QPoint, QRect

from origenerator.gui.thumbnail_selection import Picks, ThumbnailSelection


@dataclass(frozen=True)
class PanePlace:
    picks: Picks
    offset: int
    picture: str | None = None
    picture_at: int = 0

    def from_the_top(self) -> PanePlace:
        return replace(self, offset=0, picture=None, picture_at=0)


def place_of(scroll, selection: ThumbnailSelection, tiles: dict) -> PanePlace:
    offset = scroll.verticalScrollBar().value()
    picture = _picked_in_view(scroll, selection, tiles) if offset else None
    return PanePlace(selection.picks(), offset, picture,
                     0 if picture is None else _below_the_top(scroll, tiles[picture]))


def stand_at(scroll, tiles: dict, place: PanePlace, drawn) -> None:
    if scroll.widget() is not drawn:
        return
    tile = tiles.get(place.picture) if place.picture else None
    scroll.verticalScrollBar().setValue(
        place.offset if tile is None
        else tile.mapTo(drawn, QPoint(0, 0)).y() - place.picture_at)


def _picked_in_view(scroll, selection: ThumbnailSelection, tiles: dict) -> str | None:
    seen = scroll.viewport().rect()
    for prompt_id in selection.in_shown_order():
        tile = tiles.get(prompt_id)
        if tile is not None and seen.intersects(
                QRect(tile.mapTo(scroll.viewport(), QPoint(0, 0)), tile.size())):
            return prompt_id
    return None


def _below_the_top(scroll, tile) -> int:
    return tile.mapTo(scroll.viewport(), QPoint(0, 0)).y()
