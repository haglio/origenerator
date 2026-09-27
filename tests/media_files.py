"""Real videos, fabricated, for the tests that need a decoder or a player to open one."""
from __future__ import annotations

import struct
from pathlib import Path

_FPS = 16


def write_mp4(path: Path, *, seconds: float = 0.25, width: int = 16, height: int = 16) -> Path:
    import cv2  # noqa: PLC0415 (heavy; only a test that needs a real video writes one)
    import numpy  # noqa: PLC0415

    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), _FPS, (width, height))
    for _ in range(max(1, round(seconds * _FPS))):
        writer.write(numpy.zeros((height, width, 3), dtype=numpy.uint8))
    writer.release()
    return path


def _box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def _top_level_boxes(data: bytes):
    offset = 0
    while offset < len(data):
        size, kind = struct.unpack_from(">I4s", data, offset)
        yield offset, size, kind
        offset += size


def write_mp4_with_a_comment_tag(path: Path, comment: str) -> Path:
    """A video carrying *comment* as a container tag, which a player's FFmpeg reads
    as it reads a generated video's embedded prompt.  cv2 writes ``moov`` last, so
    the tag is appended there without moving any offset the frames depend on."""
    data = bytearray(write_mp4(path).read_bytes())
    moov_at, moov_size, last_kind = list(_top_level_boxes(bytes(data)))[-1]
    assert last_kind == b"moov", f"cv2 wrote {last_kind!r} last, not moov"
    text = comment.encode("utf-8")
    user_data = _box(b"udta", _box(b"\xa9cmt", struct.pack(">HH", len(text), 0) + text))
    struct.pack_into(">I", data, moov_at, moov_size + len(user_data))
    path.write_bytes(bytes(data) + user_data)
    return path
