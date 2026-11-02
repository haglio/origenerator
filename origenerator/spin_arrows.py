"""The up/down triangles a styled spinner needs, drawn to disk once.

Qt's stylesheet engine draws the CSS border-triangle trick as a filled rectangle, and takes an
arrow only as an image file, so the arrows are written under ``state/ui`` for the stylesheet to name.
"""

from __future__ import annotations

import logging
from pathlib import Path

from origenerator.config import STATE_DIR

logger = logging.getLogger(__name__)

_WIDTH, _HEIGHT = 9, 5


def _draw(path: Path, color: tuple, pointing_down: bool) -> None:
    from PIL import Image  # noqa: PLC0415 (optional: no Pillow, no drawn arrow)

    image = Image.new("RGBA", (_WIDTH, _HEIGHT), (0, 0, 0, 0))
    pixels = image.load()
    for row in range(_HEIGHT):
        inset = row if pointing_down else _HEIGHT - 1 - row
        for column in range(inset, _WIDTH - inset):
            pixels[column, row] = color
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def arrow_paths(color, directory: Path = STATE_DIR / "ui") -> tuple[str, str] | None:
    rgb = (color.red(), color.green(), color.blue(), 255)
    stem = f"spin_arrow_{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
    up, down = directory / f"{stem}_up.png", directory / f"{stem}_down.png"
    try:
        if not up.exists():
            _draw(up, rgb, pointing_down=False)
        if not down.exists():
            _draw(down, rgb, pointing_down=True)
    except Exception as e:
        logger.warning("Could not draw the spinner arrows: %s", e)
        return None
    # Qt reads a backslash in a stylesheet url() as an escape.
    return up.as_posix(), down.as_posix()
