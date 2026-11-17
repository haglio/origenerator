from __future__ import annotations

import os
import shutil
from pathlib import Path

from PIL import Image, ImageChops
from PIL.PngImagePlugin import PngInfo

_FOLDER = "kept from fixes"
_BEFORE, _AFTER, _CHANGED = "before", "after", "changed"
_BLANK = (0, 0, 0)


def folder_beside(thumb_dir: Path) -> Path:
    return Path(thumb_dir).parent / _FOLDER


def keep(stages: list[Path], parts: list[str], into: Path) -> list[dict]:
    images = [_opened(path) for path in stages]
    if len(images) != len(parts) + 1 or len({image.size for image in images}) != 1:
        return []
    fixes: list[dict] = []
    changed_by: list[Image.Image] = []
    for at, part in enumerate(parts):
        before, after = images[at], images[at + 1]
        changed = _where_they_differ(before, after)
        box = changed.getbbox()
        if box is not None:
            into.mkdir(parents=True, exist_ok=True)
            mask = changed.crop(box)
            mask.save(_kept_file(into, at, _CHANGED))
            _only_where(mask, before.crop(box)).save(_kept_file(into, at, _BEFORE))
            _only_where(mask, after.crop(box)).save(_kept_file(into, at, _AFTER))
        fixes.append({"part": part, "box": list(box) if box else None,
                      "over": [earlier["part"]
                               for earlier, theirs in zip(fixes, changed_by, strict=True)
                               if ImageChops.darker(theirs, changed).getbbox() is not None]})
        changed_by.append(changed)
    return fixes


def switch(image: Path, kept: Path, at: int, box: list[int], *, on: bool) -> bool:
    piece, mask = _kept_file(kept, at, _AFTER if on else _BEFORE), _kept_file(kept, at, _CHANGED)
    if not (image.is_file() and piece.is_file() and mask.is_file()):
        return False
    with Image.open(image) as opened:
        written_inside = dict(getattr(opened, "text", {}))
        redrawn = opened.copy()
    with Image.open(piece) as drawn, Image.open(mask) as where:
        redrawn.paste(drawn.convert(redrawn.mode), (box[0], box[1]), where)
    written = kept / f"{image.name}.switching"
    redrawn.save(written, format="PNG", pnginfo=_as_png_text(written_inside))
    os.replace(written, image)
    return True


def forget_all_but(root: Path, kept_names, *, settled_before: float) -> int:
    if not root.is_dir():
        return 0
    wanted = set(kept_names)
    forgotten = [folder for folder in root.iterdir()
                 if folder.is_dir() and folder.name not in wanted
                 and folder.stat().st_mtime < settled_before]
    for folder in forgotten:
        shutil.rmtree(folder, ignore_errors=True)
    return len(forgotten)


def _opened(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGB")


def _kept_file(folder: Path, at: int, which: str) -> Path:
    return folder / f"{at}_{which}.png"


def _as_png_text(written_inside: dict) -> PngInfo:
    info = PngInfo()
    for key, value in written_inside.items():
        info.add_text(key, value)
    return info


def _where_they_differ(before: Image.Image, after: Image.Image) -> Image.Image:
    red, green, blue = ImageChops.difference(before, after).split()
    any_channel = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    return any_channel.point(lambda level: 255 if level else 0)


def _only_where(mask: Image.Image, piece: Image.Image) -> Image.Image:
    return Image.composite(piece, Image.new("RGB", piece.size, _BLANK), mask)
