"""The colors this app's cards and rows share, and nothing else does.

`shared_ui.colors` carries the family's palette and `stylesheet.build_stylesheet`
is the one sheet the window wears. What was left over is a handful of colors that
several widgets each spelled out for themselves: the blue a picked thing wears,
the frame a card rests and hovers at, the ground an empty slot shows. The same
gray ended up written in two unrelated files, so changing it meant finding both
— which is the one property the shared palette exists to give.

Every value is one of `shared_ui.palette`'s, named here in this app's words:
the family's look is its small set of colors, so a card's frame or an empty
slot's ground takes the nearest of them rather than a shade of its own, and
`tests/test_family_look.py` fails on any shade typed back in.
"""
from __future__ import annotations

from shared_ui.palette import (
    BG_BUTTON,
    BG_SECONDARY,
    BLUE,
    BORDER_PANEL,
    GREEN,
    TEXT_PRIMARY,
    as_hex,
)

# A picked tile, card or version row: the ground it is filled with, and its frame.
SELECTED_FILL = as_hex(BLUE)
SELECTED_BORDER = as_hex(TEXT_PRIMARY)

# A card's frame at rest, and under the pointer.
CARD_BORDER = as_hex(BG_BUTTON)
CARD_HOVER_BORDER = as_hex(BORDER_PANEL)

# The ground an empty slot sits on, where there is no picture to show yet.
EMPTY_PLATE = as_hex(BG_SECONDARY)

# The frame around something still being made — a queued enhancement, a card
# whose generation is on the GPU.
IN_FLIGHT_BORDER = as_hex(BLUE)

# The lit edge an enhancement level wears while the row that would duplicate it
# is hovered.
MATCH_BORDER = as_hex(GREEN)
