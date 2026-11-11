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
