from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from PIL import Image

from origenerator import fix_switches, fixes_kept
from origenerator.gallery import resolve_preview
from origenerator.gallery.output import output_file_path, row_output_files
from origenerator.output_places import OutputPlaces
from origenerator.thumbnail import thumbnail_of

logger = logging.getLogger(__name__)


class Shown(NamedTuple):
    file: dict
    image: Image.Image | None
    path: Path


@dataclass
class _Enhancement:
    prompt_id: str
    path: Path
    kept: Path
    file: dict
    drawn: fixes_kept.Redrawn | None = None
    is_being_written: bool = False
    redraws_shown: int = 0
    redraws_written: int = 0

    @property
    def is_behind_the_screen(self) -> bool:
        return self.redraws_written < self.redraws_shown


class FixesBeingChosen:
    def __init__(self, db, places: OutputPlaces, thumb_dir: Path | None, *,
                 off_thread: Callable, written: Callable[[Path], None] = lambda path: None):
        self._db = db
        self._places = places
        self._thumb_dir = thumb_dir
        self._off_thread = off_thread
        self._tell_written = written
        self._one_writer = threading.Lock()
        self._chosen: dict[tuple[str, str], _Enhancement] = {}
        self._last_recorded: tuple[Path, tuple, fixes_kept.Redrawn] | None = None

    def change(self, row: dict, filename: str, part: str, what: str, to: bool) -> Shown | None:
        key = (row["prompt_id"], filename)
        enhancement = self._chosen.get(key) or self._as_recorded(row, filename)
        if enhancement is None:
            return None
        changed = fix_switches.changed(enhancement.file, part, what, to)
        if changed is None:
            return None
        redrawn = None
        if what == fix_switches.ON:
            redrawn = self._redrawn(enhancement, part, on=to)
            if redrawn is None:
                return None
            enhancement.drawn = redrawn
            enhancement.redraws_shown += 1
        enhancement.file = changed
        self._chosen[key] = enhancement
        if redrawn is not None and not enhancement.is_being_written:
            self._write(key, enhancement)
        return Shown(changed, redrawn.image if redrawn is not None else None, enhancement.path)

    def any_being_written(self) -> bool:
        return any(enhancement.is_being_written or enhancement.is_behind_the_screen
                   for enhancement in self._chosen.values())

    def record(self) -> list[str]:
        recorded = []
        for key, enhancement in list(self._chosen.items()):
            if enhancement.is_being_written or enhancement.is_behind_the_screen:
                continue
            del self._chosen[key]
            if self._record(enhancement, key[1]):
                recorded.append(enhancement.prompt_id)
        return recorded

    def settle(self) -> list[str]:
        for enhancement in self._chosen.values():
            if not (enhancement.is_being_written or enhancement.is_behind_the_screen):
                continue
            self._write_what_is_shown(enhancement, enhancement.drawn, _off(enhancement.file),
                                      enhancement.redraws_shown)
            enhancement.is_being_written = False
            self._tell_written(enhancement.path)
        return self.record()

    def _as_recorded(self, row: dict, filename: str) -> _Enhancement | None:
        file = next((entry for entry in row_output_files(row)
                     if entry.get("filename") == filename), None)
        if (file is None or self._thumb_dir is None
                or not isinstance(file.get(fix_switches.KEPT_KEY), str)):
            return None
        kept = fixes_kept.folder_beside(Path(self._thumb_dir)) / file[fix_switches.KEPT_KEY]
        return _Enhancement(row["prompt_id"], output_file_path(file, self._places), kept, file)

    def _redrawn(self, enhancement: _Enhancement, part: str, *, on: bool):
        drawn_as = fix_switches.drawn_as(enhancement.file, part)
        try:
            before = (enhancement.drawn or self._as_last_recorded(enhancement.path)
                      or fixes_kept.opened(enhancement.path))
            if drawn_as is None or before is None:
                return None
            image = fixes_kept.with_the_fix(before.image, enhancement.kept, *drawn_as, on=on)
        except OSError:
            logger.exception("Could not switch a fix of %s", enhancement.prompt_id)
            return None
        return None if image is None else fixes_kept.Redrawn(image, before.written_inside)

    def _as_last_recorded(self, path: Path) -> fixes_kept.Redrawn | None:
        if self._last_recorded is None:
            return None
        recorded, as_written, drawn = self._last_recorded
        return drawn if recorded == path and _as_on_disk(path) == as_written else None

    def _write(self, key, enhancement: _Enhancement) -> None:
        enhancement.is_being_written = True
        drawn, off, shown = enhancement.drawn, _off(enhancement.file), enhancement.redraws_shown
        self._off_thread(lambda: self._write_what_is_shown(enhancement, drawn, off, shown),
                         lambda _done: self._wrote(key))

    def _write_what_is_shown(self, enhancement: _Enhancement, drawn, off: list[str],
                             shown: int) -> None:
        with self._one_writer:
            if enhancement.redraws_written >= shown:
                return
            try:
                fixes_kept.write_over(drawn, enhancement.kept, enhancement.path, off)
            except OSError:
                logger.exception("Could not write a switched fix over %s", enhancement.path.name)
            enhancement.redraws_written = shown

    def _wrote(self, key) -> None:
        enhancement = self._chosen.get(key)
        if enhancement is None or not enhancement.is_being_written:
            return
        enhancement.is_being_written = False
        self._tell_written(enhancement.path)
        if enhancement.is_behind_the_screen:
            self._write(key, enhancement)

    def _record(self, enhancement: _Enhancement, filename: str) -> bool:
        row = self._db.get_generation(enhancement.prompt_id)
        files = row_output_files(row) if row else []
        at = next((at for at, entry in enumerate(files) if entry.get("filename") == filename), None)
        if at is None:
            return False
        files[at] = enhancement.file
        self._db.update_generation(enhancement.prompt_id, output_files=json.dumps(files))
        fixes_kept.forget_what_was_written(enhancement.kept, enhancement.path)
        if enhancement.drawn is not None:
            self._last_recorded = (enhancement.path, _as_on_disk(enhancement.path),
                                   enhancement.drawn)
            self._redraw_the_thumbnail(row, enhancement)
        return True

    def _redraw_the_thumbnail(self, row: dict, enhancement: _Enhancement) -> None:
        preview = resolve_preview(row, self._places)
        if preview is None or Path(preview[0]) != enhancement.path:
            return
        try:
            thumbnail = thumbnail_of(enhancement.drawn.image, Path(self._thumb_dir),
                                     name=enhancement.prompt_id)
        except Exception:
            logger.exception("Could not redraw the thumbnail for %s", enhancement.prompt_id)
            return
        self._db.update_generation(enhancement.prompt_id, thumbnail_path=str(thumbnail))


def _as_on_disk(path: Path) -> tuple:
    try:
        on_disk = path.stat()
    except OSError:
        return ()
    return on_disk.st_size, on_disk.st_mtime_ns


def _off(file: dict) -> list[str]:
    return [switch.part for switch in fix_switches.switches_of(file) if not switch.on]
