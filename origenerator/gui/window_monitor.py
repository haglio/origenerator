from __future__ import annotations

import base64
import struct
from collections.abc import Callable, Sequence

from app_support.loading_screen import AppWindow
from PyQt6.QtGui import QGuiApplication, QScreen

_QT_SAVE_GEOMETRY_HEAD = struct.Struct(">IHH4i4ii")
_QT_SAVE_GEOMETRY_MAGIC = 0x1D9D0CB
GEOMETRY_KEY = "window_geometry"


def the_screen_it_was_saved_on(geometry: str | None, *,
                               screens: Callable[[], Sequence[QScreen]] = QGuiApplication.screens) -> QScreen | None:
    try:
        magic, _major, _minor, *_frame_and_normal_rects, screen_number = _QT_SAVE_GEOMETRY_HEAD.unpack_from(
            base64.b64decode(geometry, validate=True))
    except (TypeError, ValueError, struct.error):
        return None
    if magic != _QT_SAVE_GEOMETRY_MAGIC:
        return None
    every = screens()
    return every[screen_number] if 0 <= screen_number < len(every) else every[0]


def the_window_saved_in(geometry: str | None) -> AppWindow:
    screen = the_screen_it_was_saved_on(geometry)
    return AppWindow() if screen is None else the_window_on(screen)


def the_window_on(screen: QScreen) -> AppWindow:
    area, ratio = screen.geometry(), screen.devicePixelRatio()
    return AppWindow(kept_on=(area.x(), area.y(), round(area.width() * ratio), round(area.height() * ratio)))
