from __future__ import annotations

import io
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from app_support.written_file import ReadEachWhenChanged
from PIL import Image
from shared_ui.palette import BORDER_SUBTLE

_EMPTY_ALPHA = 110

def empty_thumbnail(draw, x, y, side) -> int:
    draw.rectangle([x, y, x + side - 1, y + side - 1], fill=(*BORDER_SUBTLE, _EMPTY_ALPHA))
    return side


def _written(path) -> int | None:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


def thumbnail_dates(paths) -> tuple[int | None, ...]:
    return tuple(_written(path) for path in paths if path)


class _Thumbnail(NamedTuple):
    path: str
    side: int
    gray: bool


def _held_thumbnails(most: int, *, now_ns: Callable[[], int] = time.time_ns
                     ) -> ReadEachWhenChanged[_Thumbnail, Image.Image | None]:
    return ReadEachWhenChanged(
        lambda thumbnail: _opened_and_fitted(thumbnail.path, thumbnail.side, thumbnail.gray),
        most=most, path_of=lambda thumbnail: Path(thumbnail.path), now_ns=now_ns)


_FITTED = _held_thumbnails(1024)


def fitted_thumbnail(path, side: int, gray: bool = False) -> Image.Image | None:
    if not path:
        return None
    return _FITTED.latest(_Thumbnail(str(path), side, gray))


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
