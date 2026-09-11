"""The colors this app's cards and rows share, and nothing else does.

`shared_ui.colors` carries the family's palette and `stylesheet.build_stylesheet`
is the one sheet the window wears. What was left over is a handful of greys that
several widgets each spelled out for themselves: the fill a selected thing takes,
the frame a card rests and hovers at, the ground an empty slot shows. The same
grey ended up written in two unrelated files, so changing it meant finding both
— which is the one property the shared palette exists to give.

Local rather than in `shared_ui`: these are this app's own cards. A color the
family shares belongs over there, and moving one up is a cross-repo change of
its own.

A literal that happens to match one of these but means something else — a glyph
drawn the color of a hover frame, a caption the color of a selected border —
stays a literal. Collapsing two meanings onto one token is what makes a palette
impossible to change later.
"""
from __future__ import annotations

# What a selected tile or version row is filled with, and the frame that says so.
SELECTED_FILL = "#3a3a3a"
SELECTED_BORDER = "#8a8a8a"

# A card's frame at rest, and under the pointer.
CARD_BORDER = "#3f3f3f"
CARD_HOVER_BORDER = "#6f6f6f"

# The ground an empty slot sits on, where there is no picture to show yet.
EMPTY_PLATE = "#2a2a2a"

# The frame around something still being made — a queued enhancement, a card
# whose generation is on the GPU.
IN_FLIGHT_BORDER = "#3080e0"
