"""A video plays on a native window, which no ordinary sibling widget paints over however it is stacked; an overlay made native itself stacks against the video by Z-order."""
from __future__ import annotations

from PyQt6.QtCore import Qt

from origenerator.win32 import raise_window_without_activating


def float_over_media(widget, *, click_through: bool = True) -> None:
    if click_through:
        widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)


def raise_over_media(widget) -> None:
    widget.raise_()
    raise_window_without_activating(int(widget.winId()))
