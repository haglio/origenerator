from __future__ import annotations

import glob
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote

from PIL import Image, ImageChops
from PIL.PngImagePlugin import PngInfo

_FOLDER = "kept from fixes"
_BEFORE, _AFTER, _CHANGED = "before", "after", "changed"
_BLANK = (0, 0, 0)
_WAITING = ".switching"
_HALF_WRITTEN = ".writing"
_NONE_OFF = "-"
_QUICK_TO_WRITE = 1


@dataclass(frozen=True)
class Redrawn:
    image: Image.Image
    written_inside: dict


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


def opened(image: Path) -> Redrawn | None:
    if not image.is_file():
        return None
    with Image.open(image) as on_disk:
        return Redrawn(on_disk.copy(), dict(getattr(on_disk, "text", {})))


def with_the_fix(whole: Image.Image, kept: Path, at: int, box: list[int], *,
                 on: bool) -> Image.Image | None:
    piece, mask = _kept_file(kept, at, _AFTER if on else _BEFORE), _kept_file(kept, at, _CHANGED)
    if not (piece.is_file() and mask.is_file()):
        return None
    redrawn = whole.copy()
    with Image.open(piece) as drawn, Image.open(mask) as where:
        redrawn.paste(drawn.convert(redrawn.mode), (box[0], box[1]), where)
    return redrawn


def write_over(drawn: Redrawn, kept: Path, image: Path, off: list[str]) -> None:
    waiting = kept / _waiting_name(image, off)
    half_written = waiting.with_name(waiting.name + _HALF_WRITTEN)
    drawn.image.save(half_written, format="PNG", pnginfo=_as_png_text(drawn.written_inside),
                     compress_level=_QUICK_TO_WRITE)
    os.replace(half_written, waiting)
    _put_in_place(waiting, image)
    for earlier in _waiting(kept, image):
        if earlier != waiting:
            earlier.unlink(missing_ok=True)


def finish_what_was_written(kept: Path, image: Path) -> list[str] | None:
    waiting = _waiting(kept, image)
    if not waiting:
        return None
    newest = max(waiting, key=lambda path: path.name)
    _put_in_place(newest, image)
    return _off_named_in(newest, image)


def forget_what_was_written(kept: Path, image: Path) -> None:
    for left in map(Path, glob.glob(str(kept / f"{glob.escape(image.name)}.*{_WAITING}*"))):
        left.unlink(missing_ok=True)


def _put_in_place(waiting: Path, image: Path) -> None:
    # A slideshow showing the image holds it open, and Windows replaces no file held open; it does let one be written over.
    with open(image, "r+b") as shown:
        shown.write(waiting.read_bytes())
        shown.truncate()


def _waiting_name(image: Path, off: list[str]) -> str:
    named = ",".join(quote(part, safe="") for part in off) or _NONE_OFF
    return f"{image.name}.{time.time_ns():020d}.{named}{_WAITING}"


def _waiting(kept: Path, image: Path) -> list[Path]:
    return list(map(Path, glob.glob(str(kept / f"{glob.escape(image.name)}.*{_WAITING}"))))


def _off_named_in(waiting: Path, image: Path) -> list[str]:
    _written_at, named = waiting.name[len(image.name) + 1:-len(_WAITING)].split(".", 1)
    return [] if named == _NONE_OFF else [unquote(part) for part in named.split(",")]


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
