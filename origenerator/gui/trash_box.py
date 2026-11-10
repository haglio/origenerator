from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QRectF, QSize
from PyQt6.QtGui import QPainter, QPen
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget
from shared_ui.colors import BORDER_PANEL, TEXT_MUTED
from shared_ui.spacing import BUTTON_RADIUS, GAP_DIALOG, GAP_SMALL, MARGIN_STANDARD

from origenerator.gui import tile_shape
from origenerator.gui.flow_layout import FlowLayout

_EDGE = 1
_DASH = 10
_INSET = _EDGE + MARGIN_STANDARD
TILE_GAP = GAP_DIALOG


class _TileGroup(QWidget):

    def __init__(self, tiles: list[QWidget], parent=None, *, side_inset: int = 0):
        super().__init__(parent)
        self._side_inset = side_inset
        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(side_inset, _INSET, side_inset, _INSET)
        self._column.setSpacing(GAP_SMALL)
        host = QWidget()
        flow = FlowLayout(host, spacing=TILE_GAP)
        for tile in tiles:
            flow.addWidget(tile)
        self._column.addWidget(host)
        self._tiles = tiles

    def _widest_line(self) -> int:
        return (sum(tile.sizeHint().expandedTo(tile.minimumSize()).width() for tile in self._tiles)
                + TILE_GAP * (len(self._tiles) - 1))

    def sizeHint(self) -> QSize:
        width = self._widest_line() + 2 * self._side_inset
        return QSize(width, self.heightForWidth(width))


class TrashBox(_TileGroup):

    def __init__(self, tiles: list[QWidget], parent=None):
        super().__init__(tiles, parent, side_inset=_INSET)
        self.label = QLabel("in the Trash")
        tile_shape.style_caption(self.label)
        self.label.setStyleSheet(f"color: {TEXT_MUTED.name()};")
        self._column.addWidget(self.label)

    def _widest_line(self) -> int:
        return max(super()._widest_line(), self.label.sizeHint().width())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        pen = QPen(BORDER_PANEL, _EDGE)
        pen.setDashPattern([_DASH, _DASH])
        painter.setPen(pen)
        half = _EDGE / 2
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(half, half, -half, -half),
                                BUTTON_RADIUS, BUTTON_RADIUS)


def place_tiles(tiles: list[tuple[QWidget, bool]],
                add: Callable[[QWidget], None]) -> TrashBox | None:
    trashed = [tile for tile, in_trash in tiles if in_trash]
    kept = [tile for tile, in_trash in tiles if not in_trash]
    if not trashed:
        for tile in kept:
            add(tile)
        return None
    if kept:
        add(_TileGroup(kept))
    box = TrashBox(trashed)
    add(box)
    return box
