"""Floating a widget over media, and the plate that keeps it readable.

A video plays on a native window, and an ordinary sibling widget cannot paint
over one however it is stacked — so an overlay that showed perfectly well over
a picture vanished the moment a clip came up. Made native itself, it stacks
against the video by Z-order like any other window. Six widgets learned that
separately, most of them by shipping the bug first and then carrying a comment
about it; this is the one place it is written down, so the next overlay a show
grows does not become the seventh.

The plate is here for the same reason: light text needs a dark ground under it
over bright media, and that translucent black was spelled out at each site that
wanted one.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt

# What an overlay sits on so light text and small pictures stay readable over
# whatever the media happens to be showing there. Padding is each caller's
# own — it is about that overlay's contents, not about being readable.
PLATE_CSS = "background: rgba(0, 0, 0, 140); border-radius: 4px;"


def float_over_media(widget, *, click_through: bool = True) -> None:
    """Let ``widget`` paint over a video surface.

    ``click_through`` passes the mouse on to whatever is under the overlay,
    which is what a caption or a still wants and what a control does not. It is
    asked for per call rather than applied to everything, because a native
    window per widget is real cost: the corner controls take it only where a
    video can turn up, never on a wall of thumbnails.
    """
    if click_through:
        widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
