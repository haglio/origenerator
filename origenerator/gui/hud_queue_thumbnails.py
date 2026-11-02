from __future__ import annotations

import io
import os

from PIL import Image
from shared_ui.palette import BORDER_SUBTLE

_EMPTY_ALPHA = 110

_FITTED: dict[tuple[str, int, bool, int | None], Image.Image | None] = {}


def empty_thumbnail(draw, x, y, side) -> int:
    draw.rectangle([x, y, x + side - 1, y + side - 1], fill=(*BORDER_SUBTLE, _EMPTY_ALPHA))
    return side


def _written(path) -> int | None:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


def fitted_thumbnail(path, side: int, gray: bool = False) -> Image.Image | None:
    if not path:
        return None
    key = (str(path), side, gray, _written(path))
    if key not in _FITTED:
        _FITTED[key] = _opened_and_fitted(path, side, gray)
    return _FITTED[key]


def _centered(opened: Image.Image, side: int) -> Image.Image:
    opened.thumbnail((side, side))
    fitted = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    fitted.paste(opened, ((side - opened.width) // 2, (side - opened.height) // 2))
    return fitted


def _opened_and_fitted(path, side: int, gray: bool) -> Image.Image | None:
    try:
        opened = Image.open(path).convert("RGBA")
    except (OSError, ValueError):
        return None
    return _centered(opened.convert("L").convert("RGBA") if gray else opened, side)


def fitted_frame(frame: bytes | None, side: int) -> Image.Image | None:
    if not frame:
        return None
    try:
        opened = Image.open(io.BytesIO(frame)).convert("RGBA")
    except (OSError, ValueError):
        return None
    return _centered(opened, side)
