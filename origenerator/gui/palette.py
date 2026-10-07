"""The colors this app's cards and rows share, and nothing else does.

`shared_ui.colors` carries the family's palette and `stylesheet.build_stylesheet`
is the one sheet the window wears. What was left over is a handful of colors that
several widgets each spelled out for themselves: the blue a picked thing wears,
the frame a card rests and hovers at, the ground an empty slot shows. The same
gray ended up written in two unrelated files, so changing it meant finding both
— which is the one property the shared palette exists to give.

Local rather than in `shared_ui`: these are this app's own cards. A color the
family shares belongs over there, and moving one up is a cross-repo change of
its own.

A literal that happens to match one of these but means something else — a glyph
drawn the color of a hover frame, a caption the color of a selected border —
stays a literal. Collapsing two meanings onto one token is what makes a palette
impossible to change later.

The names read from `shared_ui.palette` below are this app's words for colors the
family owns, rather than typed out again: the family has one blue and one green,
and a second copy of either is a thing that drifts. `tests/test_family_colors.py`
fails on any that is typed back in.
"""
from __future__ import annotations

from shared_ui.palette import BLUE, GREEN, as_hex

# What a picked tile, card or version row wears: its ground and its picture's frame.
SELECTED = as_hex(BLUE)

# A card's frame at rest, and under the pointer.
CARD_BORDER = "#3f3f3f"
CARD_HOVER_BORDER = "#6f6f6f"

# The ground an empty slot sits on, where there is no picture to show yet.
EMPTY_PLATE = "#2a2a2a"

# The frame around something still being made — a queued enhancement, a card
# whose generation is on the GPU.
IN_FLIGHT_BORDER = as_hex(BLUE)

# The lit edge an enhancement level wears while the row that would duplicate it
# is hovered.
MATCH_BORDER = as_hex(GREEN)
