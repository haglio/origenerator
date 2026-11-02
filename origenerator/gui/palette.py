from __future__ import annotations

from shared_ui.palette import (
    BG_BUTTON,
    BG_SECONDARY,
    BLUE,
    BORDER_PANEL,
    TEXT_PRIMARY,
    as_hex,
)

SELECTED_FILL = as_hex(BLUE)
SELECTED_BORDER = as_hex(TEXT_PRIMARY)

TILE_BORDER = as_hex(BG_BUTTON)
TILE_HOVER_BORDER = as_hex(BORDER_PANEL)

EMPTY_PLATE = as_hex(BG_SECONDARY)

IN_FLIGHT_BORDER = as_hex(BLUE)

MATCH_BORDER = as_hex(TEXT_PRIMARY)
