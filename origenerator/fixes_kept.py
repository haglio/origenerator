from __future__ import annotations

import glob
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops
from PIL.PngImagePlugin import PngInfo

_FOLDER = "kept from fixes"
_BEFORE, _AFTER, _CHANGED = "before", "after", "changed"
_BLANK = (0, 0, 0)
_WAITING = ".switching"
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


def redrawn(image: Path, kept: Path, at: int, box: list[int], *, on: bool) -> Redrawn | None:
    piece, mask = _kept_file(kept, at, _AFTER if on else _BEFORE), _kept_file(kept, at, _CHANGED)
    if not (image.is_file() and piece.is_file() and mask.is_file()):
        return None
    with Image.open(image) as opened:
        written_inside = dict(getattr(opened, "text", {}))
        whole = opened.copy()
    with Image.open(piece) as drawn, Image.open(mask) as where:
        whole.paste(drawn.convert(whole.mode), (box[0], box[1]), where)
    return Redrawn(whole, written_inside)


def set_down(drawn: Redrawn, kept: Path, image: Path, part: str, *, on: bool) -> Path:
    waiting = kept / f"{image.name}.{part}.{'on' if on else 'off'}{_WAITING}"
    half_written = waiting.with_name(waiting.name + ".writing")
    drawn.image.save(half_written, format="PNG", pnginfo=_as_png_text(drawn.written_inside),
                     compress_level=_QUICK_TO_WRITE)
    os.replace(half_written, waiting)
    return waiting


def put_in_place(waiting: Path, image: Path) -> None:
    # A slideshow showing the image holds it open, and Windows replaces no file held open; it does let one be written over.
    with open(image, "r+b") as shown:
        shown.write(waiting.read_bytes())
        shown.truncate()
    waiting.unlink()


def set_down_and_never_put_in_place(kept: Path, image: Path) -> list[tuple[Path, str, bool]]:
    found = []
    for waiting in map(Path, glob.glob(str(kept / f"{glob.escape(image.name)}.*{_WAITING}"))):
        part, state = waiting.name[len(image.name) + 1:-len(_WAITING)].rsplit(".", 1)
        found.append((waiting, part, state == "on"))
    return found


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
