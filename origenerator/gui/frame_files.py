from __future__ import annotations

import logging
import time
from collections.abc import Callable
from itertools import count
from pathlib import Path

logger = logging.getLogger(__name__)

_JPEG_MAGIC = b"\xff\xd8"
_NEWEST_KEPT = 2
SECONDS_A_FUNESTRA_MAY_STILL_OPEN_IT = 10.0


class FrameFiles:
    def __init__(self, folder: Path, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._folder = folder
        self._clock = clock
        self._numbers = count()
        self._files: dict[str, list[Path]] = {}
        self._newest_frame: dict[str, bytes] = {}
        self._leaving: list[tuple[float, Path]] = []
        self._remove_now(_files_in(folder))

    def write(self, key: str, frame: bytes) -> Path | None:
        self._remove_what_has_waited()
        files = self._files.setdefault(key, [])
        if files and self._newest_frame[key] == frame:
            return files[-1]
        suffix = ".jpg" if frame.startswith(_JPEG_MAGIC) else ".png"
        path = self._folder / f"{key}-{next(self._numbers)}{suffix}"
        being_written = path.with_name(f"{path.name}.partial")
        try:
            self._folder.mkdir(parents=True, exist_ok=True)
            being_written.write_bytes(frame)
            being_written.replace(path)
        except OSError:
            logger.warning("Could not write a frame of %s to %s", key, path, exc_info=True)
            return None
        files.append(path)
        self._newest_frame[key] = frame
        while len(files) > 1 + _NEWEST_KEPT:
            self._remove_soon([files.pop(1)])
        return path

    def first_of(self, key: str) -> Path | None:
        files = self._files.get(key)
        return files[0] if files else None

    def forget(self, key: str) -> None:
        self._newest_frame.pop(key, None)
        self._remove_soon(self._files.pop(key, []))

    def forget_all(self) -> None:
        self._newest_frame.clear()
        everything = [path for files in self._files.values() for path in files]
        self._files.clear()
        self._remove_now(everything)

    def _remove_soon(self, paths) -> None:
        now = self._clock()
        self._leaving.extend((now, path) for path in paths)
        self._remove_what_has_waited()

    def _remove_now(self, paths) -> None:
        self._leaving.extend((float("-inf"), path) for path in paths)
        self._remove_what_has_waited()

    def _remove_what_has_waited(self) -> None:
        due = self._clock() - SECONDS_A_FUNESTRA_MAY_STILL_OPEN_IT
        self._leaving = [(since, path) for since, path in self._leaving
                         if since > due or not _removed(path)]


def _files_in(folder: Path) -> list[Path]:
    try:
        return [path for path in folder.iterdir() if path.is_file()]
    except OSError:
        return []


def _removed(path: Path) -> bool:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return False
    return True
