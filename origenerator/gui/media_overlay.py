"""Floating a widget over media.

A video plays on a native window, and an ordinary sibling widget cannot paint
over one however it is stacked — so an overlay that showed perfectly well over
a picture vanished the moment a clip came up. Made native itself, it stacks
against the video by Z-order like any other window. Six widgets learned that
separately, most of them by shipping the bug first and then carrying a comment
about it; this is the one place it is written down, so the next overlay a show
grows does not become the seventh.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt

from origenerator.win32 import raise_window_without_activating


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


def raise_over_media(widget) -> None:
    widget.raise_()
    raise_window_without_activating(int(widget.winId()))
