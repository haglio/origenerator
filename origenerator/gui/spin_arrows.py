"""The up/down triangles a styled spin box needs, drawn to disk once.

Qt's stylesheet engine is not a browser's: the CSS trick of collapsing a box to
zero size and letting its borders meet as a triangle draws a filled rectangle
here, which is exactly what appeared over the step buttons. And Qt takes an
arrow only as an image — no data URIs, no shapes — so the pictures have to
exist as files somewhere the stylesheet can name.

They are generated rather than committed because they are two triangles: a few
lines of code beats a pair of binaries in the tree, and generating them means
the color comes from the same token the rest of the stylesheet uses instead of
drifting from it the first time the palette moves.

Written under ``state/ui`` (gitignored, alongside the thumbnail cache) once per
color, and skipped when they are already there.
"""

from __future__ import annotations

import logging
from pathlib import Path

from origenerator.config import STATE_DIR

logger = logging.getLogger(__name__)

_WIDTH, _HEIGHT = 9, 5  # a small triangle, sized to sit in a 16px-wide button


def _draw(path: Path, color: tuple, pointing_down: bool) -> None:
    from PIL import Image

    image = Image.new("RGBA", (_WIDTH, _HEIGHT), (0, 0, 0, 0))
    pixels = image.load()
    for row in range(_HEIGHT):
        # Widest at the base, one pixel narrower each row toward the point.
        inset = row if pointing_down else _HEIGHT - 1 - row
        for column in range(inset, _WIDTH - inset):
            pixels[column, row] = color
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def arrow_paths(color) -> tuple[str, str] | None:
    """``(up, down)`` as stylesheet-ready paths, or ``None`` if they can't be made.

    ``None`` leaves the caller to omit its arrow rules altogether, which is the
    right fallback: Qt then draws its own arrow, and a native arrow of uncertain
    color still beats a white rectangle.
    """
    rgb = (color.red(), color.green(), color.blue(), 255)
    stem = f"spin_arrow_{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
    directory = STATE_DIR / "ui"
    up, down = directory / f"{stem}_up.png", directory / f"{stem}_down.png"
    try:
        if not up.exists():
            _draw(up, rgb, pointing_down=False)
        if not down.exists():
            _draw(down, rgb, pointing_down=True)
    except Exception as e:
        logger.warning("Could not draw the spin-box arrows: %s", e)
        return None
    # Forward slashes: a Windows backslash in a Qt stylesheet url() is an escape.
    return up.as_posix(), down.as_posix()
