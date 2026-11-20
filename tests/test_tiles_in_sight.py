from __future__ import annotations

from PySide6.QtWidgets import QWidget

from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.tiles_in_sight import TilesInSight


class _Tile(QWidget):
    def __init__(self, told: list):
        super().__init__()
        self.setFixedSize(180, 200)
        self._told = told
        self.in_sight = True

    def set_in_sight(self, in_sight: bool) -> None:
        self._told.append(self)
        self.in_sight = in_sight


def _grid_of(qtbot, count: int, told: list):
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(900, 20000)
    flow = FlowLayout(host, spacing=8)
    tiles = [_Tile(told) for _ in range(count)]
    for tile in tiles:
        flow.addWidget(tile)
    host.show()
    flow.activate()
    return host, flow, tiles


def _add(host, flow, tiles, told, count: int) -> list:
    added = []
    with flow.appending():
        for _ in range(count):
            tile = _Tile(told)
            flow.addWidget(tile)
            tile.show()
            added.append(tile)
    flow.activate()
    tiles.extend(added)
    return added


def test_tiles_drawn_at_the_foot_are_told_whether_they_are_in_sight_without_telling_the_rest(
        qtbot):
    told = []
    host, flow, tiles = _grid_of(qtbot, 400, told)
    sight = TilesInSight()
    sight.follow(host, tiles, 0, 1000)
    told.clear()

    added = _add(host, flow, tiles, told, 6)
    sight.follow(host, tiles, 0, 1000)

    assert set(added) <= set(told)
    assert len(told) <= len(added) + 4, (
        "telling every tile drawn again each few tiles takes longer the further down the "
        "gallery is")
    assert not any(tile.in_sight for tile in added)


def test_tiles_drawn_into_sight_are_told_they_are_in_sight(qtbot):
    told = []
    host, flow, tiles = _grid_of(qtbot, 40, told)
    sight = TilesInSight()
    foot = tiles[-1].y() + tiles[-1].height()
    sight.follow(host, tiles, foot - 500, foot + 600)

    added = _add(host, flow, tiles, told, 6)
    sight.follow(host, tiles, foot - 500, foot + 600)

    assert all(tile.in_sight for tile in added)
    assert [tile.in_sight for tile in tiles] == [
        tile.y() + tile.height() > foot - 500 and tile.y() < foot + 600 for tile in tiles]
