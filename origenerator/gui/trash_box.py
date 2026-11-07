from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget
from shared_ui.colors import BORDER_PANEL, TEXT_MUTED
from shared_ui.spacing import BUTTON_RADIUS, GAP_MEDIUM, GAP_SMALL, MARGIN_STANDARD

from origenerator.gui import tile_shape
from origenerator.gui.flow_layout import FlowLayout

_NAME = "trashBox"
_CSS = (f"QFrame#{_NAME} {{ border: 1px dotted {BORDER_PANEL.name()};"
        f" border-radius: {BUTTON_RADIUS}px; }}"
        f"QFrame#{_NAME} > QLabel {{ color: {TEXT_MUTED.name()}; }}")


class TrashBox(QFrame):

    def __init__(self, tiles: list[QWidget], parent=None):
        super().__init__(parent)
        self.setObjectName(_NAME)
        self.setStyleSheet(_CSS)
        column = QVBoxLayout(self)
        column.setContentsMargins(MARGIN_STANDARD, MARGIN_STANDARD,
                                  MARGIN_STANDARD, MARGIN_STANDARD)
        column.setSpacing(GAP_SMALL)
        self.label = QLabel("Trash")
        tile_shape.style_caption(self.label)
        column.addWidget(self.label)
        host = QWidget()
        flow = FlowLayout(host, spacing=GAP_MEDIUM)
        for tile in tiles:
            flow.addWidget(tile)
        column.addWidget(host)


def place_tiles(tiles: list[tuple[QWidget, bool]],
                add: Callable[[QWidget], None]) -> TrashBox | None:
    for tile, in_trash in tiles:
        if not in_trash:
            add(tile)
    trashed = [tile for tile, in_trash in tiles if in_trash]
    if not trashed:
        return None
    box = TrashBox(trashed)
    add(box)
    return box
