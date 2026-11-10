# ruff: noqa: PLC0415
# Qt is imported inside the functions: apply_room_scale runs before the first PyQt6 import in the process.
from __future__ import annotations

import ctypes
import logging
import os

# The launch interpreter is the plain system Python (paths.origenerator_python_exe), which has no pip-installed shared_ui; this module is imported before the app's own packages.
from shared_ui.spacing import BUTTON_SIZE, BUTTON_SIZE_HUD

logger = logging.getLogger(__name__)

HOSTED_SCALE = BUTTON_SIZE_HUD / BUTTON_SIZE

_ENV_VAR = "QT_SCALE_FACTOR"


def hosted_scale() -> float:
    try:
        return float(os.environ.get(_ENV_VAR) or HOSTED_SCALE)
    except ValueError:
        return HOSTED_SCALE


def room_scale(*, in_a_headset: bool) -> float:
    return 1.0 if in_a_headset else hosted_scale()


def apply_room_scale(*, in_a_headset: bool) -> float:
    """Qt reads QT_SCALE_FACTOR when the platform plugin initializes, so this must run before the first PyQt6 import."""
    scale = room_scale(in_a_headset=in_a_headset)
    if scale != 1.0:
        os.environ[_ENV_VAR] = repr(scale)
    return scale


def draw_at(factor: float) -> None:
    # Both are private API exported by Qt6Gui.dll (checked on Qt 6.11): Qt otherwise reads QT_SCALE_FACTOR only at startup, and setGlobalFactor leaves the application's device pixel ratio, which every QIcon.pixmap draws at, cached at the old factor.
    # Qt on Windows moves every screen's logical geometry at once, but a window draws at the new ratio only once it is hidden and shown again.
    try:
        qt_gui = ctypes.WinDLL("Qt6Gui.dll")
        set_global_factor = getattr(qt_gui, "?setGlobalFactor@QHighDpiScaling@@SAXN@Z")
        forget_the_old_ratio = getattr(
            qt_gui, "?resetCachedDevicePixelRatio@QGuiApplicationPrivate@@SAXXZ")
    except (OSError, AttributeError):
        logger.warning("This Qt cannot be rescaled while running; staying at %.3f",
                       active_scale())
        return
    set_global_factor.argtypes = [ctypes.c_double]
    set_global_factor.restype = None
    forget_the_old_ratio.argtypes = []
    forget_the_old_ratio.restype = None
    set_global_factor(factor)
    forget_the_old_ratio()
    if factor == 1.0:
        os.environ.pop(_ENV_VAR, None)
    else:
        os.environ[_ENV_VAR] = repr(factor)


def active_scale() -> float:
    try:
        return float(os.environ.get(_ENV_VAR, "") or 1.0)
    except ValueError:
        return 1.0


def to_logical_size(value: int) -> int:
    scale = active_scale()
    return value if scale == 1.0 else round(value / scale)


def to_logical_rect(x: int, y: int, width: int, height: int):
    """Qt leaves a scaled screen's origin at its device position and scales only its size, so a rect converts relative to the screen it lands on."""
    scale = active_scale()
    if scale == 1.0:
        return x, y, width, height
    origin_x, origin_y = _screen_origin(x, y)
    return (
        origin_x + round((x - origin_x) / scale),
        origin_y + round((y - origin_y) / scale),
        to_logical_size(width),
        to_logical_size(height),
    )


def _screen_origin(x: int, y: int) -> tuple[int, int]:
    from PyQt6.QtGui import QGuiApplication

    screens = [(screen.geometry().x(), screen.geometry().y(),
                screen.geometry().width(), screen.geometry().height())
               for screen in QGuiApplication.screens()]
    primary = QGuiApplication.primaryScreen()
    fallback = (primary.geometry().x(), primary.geometry().y()) if primary else (0, 0)
    return origin_of_the_screen_holding(x, y, screens, active_scale(), fallback)


def origin_of_the_screen_holding(x: int, y: int, logical_screens, scale: float,
                                 fallback: tuple[int, int]) -> tuple[int, int]:
    for left, top, width, height in logical_screens:
        device_width, device_height = max(1, round(width * scale)), max(1, round(height * scale))
        if left <= x < left + device_width and top <= y < top + device_height:
            return left, top
    return fallback
