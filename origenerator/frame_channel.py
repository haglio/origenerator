"""This window's picture, written where the session showing it can read it.

One memory-mapped file, its header carrying a sequence number that is odd while
a frame is being written, so a reader that looks mid-write is told to come back
rather than handed half a picture.  The reader is the session's own
(``app_support.frame_channel``); the two cannot share a module until the
family's app_support pin moves, which shared_ui and player_core hold in step.
"""
from __future__ import annotations

import mmap
import struct
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_HEADER = struct.Struct("<QIII")  # sequence (odd while writing), token, width, height
_SEQUENCE = struct.Struct("<Q")
_BYTES_PER_PIXEL = 4


class FrameWriter:
    def __init__(self, path: Path, *, max_pixels: int) -> None:
        self._max_pixels = max_pixels
        size = _HEADER.size + max_pixels * _BYTES_PER_PIXEL
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab") as created:
            if created.tell() < size:
                created.truncate(size)
        self._file = path.open("r+b")
        self._map = mmap.mmap(self._file.fileno(), size)
        self._sequence = 0
        _HEADER.pack_into(self._map, 0, 0, 0, 0, 0)

    @contextmanager
    def writing(self) -> Iterator[None]:
        self._sequence += 1
        _SEQUENCE.pack_into(self._map, 0, self._sequence)
        try:
            yield
        finally:
            self._sequence += 1
            _SEQUENCE.pack_into(self._map, 0, self._sequence)

    def write(self, token: int, width: int, height: int, pixels: bytes) -> None:
        if width * height > self._max_pixels or len(pixels) != width * height * _BYTES_PER_PIXEL:
            raise ValueError(f"a {width}x{height} frame does not fit this channel")
        with self.writing():
            self._map[_HEADER.size:_HEADER.size + len(pixels)] = pixels
            _HEADER.pack_into(self._map, 0, self._sequence, token, width, height)

    def close(self) -> None:
        self._map.close()
        self._file.close()
