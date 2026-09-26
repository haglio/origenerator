from __future__ import annotations

import logging
from itertools import count
from pathlib import Path

logger = logging.getLogger(__name__)

_JPEG_MAGIC = b"\xff\xd8"
_NEWEST_KEPT = 2


class FrameFiles:
    def __init__(self, folder: Path) -> None:
        self._folder = folder
        self._numbers = count()
        self._files: dict[str, list[Path]] = {}
        self._newest_frame: dict[str, bytes] = {}
        self._still_open: list[Path] = []
        self._remove(_files_in(folder))

    def write(self, key: str, frame: bytes) -> Path | None:
        self._remove()
        files = self._files.setdefault(key, [])
        if files and self._newest_frame[key] == frame:
            return files[-1]
        suffix = ".jpg" if frame.startswith(_JPEG_MAGIC) else ".png"
        path = self._folder / f"{key}-{next(self._numbers)}{suffix}"
        try:
            self._folder.mkdir(parents=True, exist_ok=True)
            path.write_bytes(frame)
        except OSError:
            logger.warning("Could not write a frame of %s to %s", key, path, exc_info=True)
            return None
        files.append(path)
        self._newest_frame[key] = frame
        while len(files) > 1 + _NEWEST_KEPT:
            self._remove([files.pop(1)])
        return path

    def first_of(self, key: str) -> Path | None:
        files = self._files.get(key)
        return files[0] if files else None

    def forget(self, key: str) -> None:
        self._newest_frame.pop(key, None)
        self._remove(self._files.pop(key, []))

    def forget_all(self) -> None:
        for key in list(self._files):
            self.forget(key)

    def _remove(self, paths=()) -> None:
        self._still_open = [path for path in (*self._still_open, *paths)
                            if not _removed(path)]


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
