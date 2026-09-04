"""How big this app draws, and why its hosted half draws smaller.

Standalone, Origenerator owns a whole monitor and draws at the shared family's
ordinary size: a ``BUTTON_SIZE`` square with a ``BUTTON_ICON`` mark in it.

Hosted by a Fun Time session it does not.  It occupies the Random Favs
Browser's upright rect, inches from that session's satellite HUDs, which draw
at the family's smaller ``BUTTON_SIZE_HUD``.  Two banks of the same buttons at
two sizes on one screen read as two different applications sharing a monitor
rather than as one session — so hosted, this app draws at the ratio between
them, and its buttons come out the size the HUD's are.

The whole app scales, not the buttons alone: a 28px bank shrunk to 18px inside
panes still sized for 28px leaves the marks stranded in room meant for bigger
ones.  Qt scales a whole application for us through ``QT_SCALE_FACTOR``, read
once at startup before the first ``QApplication`` exists, so every widget,
font, margin and stylesheet pixel in the process follows the same number —
including the ones written as bare integers years before this module existed.

The one thing that must NOT follow it is a rect Fun Time hands us.  Those
arrive in device pixels (the session measured them off the monitor with Win32),
while every Qt coordinate in a scaled process is logical.  :func:`to_logical`
converts at the boundary; without it a window asked to sit at the RFB's rect
would land at ``scale`` of the way across the screen, at ``scale`` of the size.
"""

from __future__ import annotations

import os

from origenerator.paths import ensure_shared_ui_on_path

# Before the shared_ui import below, as every module here that reaches for a
# sibling does.  This one runs EARLIER than any of them -- main() imports it
# before the app's own packages are touched -- and the launch interpreter is
# not the one the test suite uses: it is the plain system Python named by
# paths.origenerator_python_exe, which has no shared_ui installed at all.  Left
# out, the import raises before logging is configured, so the process dies
# without a line in state/origenerator.log and a hosting session sees only a
# window that never appeared.
ensure_shared_ui_on_path()

from shared_ui.spacing import BUTTON_SIZE, BUTTON_SIZE_HUD  # noqa: E402

# The ratio the hosted app draws at: its buttons become the HUD's buttons.
HOSTED_SCALE = BUTTON_SIZE_HUD / BUTTON_SIZE

_ENV_VAR = "QT_SCALE_FACTOR"


def apply_hosted_scale() -> float:
    """Draw this process at :data:`HOSTED_SCALE`, and return the factor set.

    Must be called before the first PyQt6 import: Qt reads ``QT_SCALE_FACTOR``
    when the platform plugin initializes, and a value written after that is
    never looked at again.

    An explicit ``QT_SCALE_FACTOR`` already in the environment wins — someone
    who set it meant it, and this app is not the only reason a process might be
    scaled.
    """
    existing = os.environ.get(_ENV_VAR)
    if existing:
        try:
            return float(existing)
        except ValueError:
            pass  # unreadable: treat it as unset rather than inherit nonsense
    os.environ[_ENV_VAR] = repr(HOSTED_SCALE)
    return HOSTED_SCALE


def active_scale() -> float:
    """The factor this process is drawing at — 1.0 when nothing scaled it."""
    try:
        return float(os.environ.get(_ENV_VAR, "") or 1.0)
    except ValueError:
        return 1.0


def to_logical_size(value: int) -> int:
    """A device-pixel LENGTH from Fun Time, in this process's Qt coordinates.

    Rounded rather than truncated: a rect's right edge is its x plus its width,
    and truncating both walks the edge inward by up to two pixels per window —
    enough to show the desktop through the seam between two satellite regions.
    """
    scale = active_scale()
    return value if scale == 1.0 else round(value / scale)


def to_logical_rect(x: int, y: int, width: int, height: int):
    """A device-pixel RECT from Fun Time, in this process's Qt coordinates.

    A position cannot be converted the way a length is, because Qt does not lay
    the scaled screens out end to end.  Measured on this machine's two monitors
    at scale 0.643: the second screen's device rect (2560, 3, 1440, 3440) comes
    back from Qt as logical (2560, 3, 2240, 5351) — its ORIGIN is left at the
    device position and only its SIZE is scaled.  So a whole-desktop
    ``x / scale`` puts a window 2560/0.643 = 3982 across, which is 1422 logical
    px INTO that screen rather than at its left edge: the portrait show landed
    in the right third of its region and hung off the monitor, with the player
    it was supposed to cover showing through beside it.

    The conversion is therefore relative to the screen the rect lands on: its
    origin, plus the offset scaled.  A rect on no screen at all (a monitor
    unplugged since the session measured it) falls back to the whole-desktop
    form, which is right for the primary screen and no worse than nothing.
    """
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
    """The Qt logical origin of the screen holding DEVICE point (*x*, *y*).

    Matched on each screen's DEVICE rect, never its logical one.  Under a scale
    below 1 the logical rects OVERLAP — this machine's primary is device
    (0, 0, 2560, 1440) and logical (0, 0, 3982, 2240), so its logical rect
    swallows the second monitor's origin at x=2560 and answers "contains" for
    every point on it.  Matching logically therefore returned the PRIMARY's
    origin for a portrait rect that belongs to the other screen, which is the
    whole-desktop division this function was written to replace: the portrait
    show landed at device x=3474 instead of 2560, 914px into the monitor, and
    the fix read as no fix at all.

    A screen's device rect is recovered from the logical one by the identity
    this module leans on throughout — the origin is left at the device position
    and only the size is scaled — so scaling the size back down is enough.
    """
    from PyQt6.QtCore import QRect
    from PyQt6.QtGui import QGuiApplication

    scale = active_scale()
    for screen in QGuiApplication.screens():
        logical = screen.geometry()
        device = QRect(logical.x(), logical.y(),
                       max(1, round(logical.width() * scale)),
                       max(1, round(logical.height() * scale)))
        if device.contains(x, y):
            return logical.x(), logical.y()
    primary = QGuiApplication.primaryScreen()
    return (primary.geometry().x(), primary.geometry().y()) if primary else (0, 0)


def unscaled_pixmap(pixmap):
    """*pixmap* set to draw one bitmap pixel per DEVICE pixel, scale or no scale.

    The satellite HUDs are bitmaps painted at the family's own sizes — an 18px
    button is already the size it is meant to be on screen — so the app-wide
    scale, which exists to shrink the core window's panes, must not shrink them
    a second time.  Qt draws a pixmap at ``size / devicePixelRatio`` logical px,
    which the scale then multiplies back: setting the ratio TO the scale makes
    those two cancel, and the bitmap lands 1:1 on device pixels with no
    resampling at all.  Its widget must be sized to
    ``pixmap.deviceIndependentSize()`` to match, and coordinates coming back
    from a mouse are logical, so they multiply by the scale to index the bitmap
    (:func:`to_bitmap_pos`).
    """
    pixmap.setDevicePixelRatio(active_scale())
    return pixmap


def to_bitmap_pos(x: float, y: float) -> tuple[int, int]:
    """A mouse position on an :func:`unscaled_pixmap` widget, in bitmap pixels."""
    scale = active_scale()
    return int(x * scale), int(y * scale)
