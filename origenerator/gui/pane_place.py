from __future__ import annotations

from dataclasses import dataclass, replace

from PyQt6.QtCore import QCoreApplication, QEvent, QPoint, QRect, Qt
from PyQt6.QtWidgets import QWidget

from origenerator.gui.thumbnail_selection import Picks, ThumbnailSelection

REVEAL_MARGIN = 40


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


def bring_into_view(scroll, tile) -> None:
    _lay_out_now(scroll)
    bar = scroll.verticalScrollBar()
    seen = scroll.viewport().rect().height()
    tall = tile.size().height()
    room = min(REVEAL_MARGIN, max(0, seen - tall) // 2)
    top = tile.mapTo(scroll.widget(), QPoint(0, 0)).y()
    bar.setValue(min(max(bar.value(), top + tall + room - seen), top - room))


def _lay_out_now(scroll) -> None:
    content = scroll.widget()
    _show_the_tiles_qt_queued_to_show(content)
    if content.layout() is not None:
        content.layout().activate()
    QCoreApplication.sendEvent(scroll, QEvent(QEvent.Type.LayoutRequest))


def _show_the_tiles_qt_queued_to_show(content) -> None:
    for tile in content.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
        QCoreApplication.sendPostedEvents(tile, QEvent.Type.MetaCall)
