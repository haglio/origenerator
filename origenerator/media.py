from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple

from origenerator.one_look import is_file

IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp"})
VIDEO_EXTS = frozenset({".mp4", ".webm"})


class MediaType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"


class ItemType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    FLICK = "flick"

    @property
    def filed_as(self) -> MediaType:
        return MediaType.IMAGE if self is ItemType.IMAGE else MediaType.VIDEO


class ShownFile(NamedTuple):
    path: str
    media_type: MediaType
    thumbnail: str | None = None


_ICONS = {ItemType.IMAGE: "photo", ItemType.VIDEO: "play", ItemType.FLICK: "flick"}


def icon_name(item_type: str) -> str:
    return _ICONS[ItemType(item_type)]


def media_type_from_filename(filename: str) -> MediaType | None:
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTS:
        return MediaType.IMAGE
    if ext in VIDEO_EXTS:
        return MediaType.VIDEO
    return None


def sibling_of_type(path: Path, media: MediaType) -> Path | None:
    exts = IMAGE_EXTS if media == MediaType.IMAGE else VIDEO_EXTS
    for ext in sorted(exts):
        sibling = path.with_suffix(ext)
        if sibling != path and is_file(sibling):
            return sibling
    return None


@dataclass(frozen=True)
class VideoHeader:
    width: int
    height: int
    fps: float
    frames: float

    @property
    def seconds(self) -> float:
        return self.frames / self.fps


def video_header(video_path) -> VideoHeader | None:
    import cv2  # noqa: PLC0415 (heavy; the pure helpers must not pull it in)

    if not video_path:
        return None
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            return None
        header = VideoHeader(
            width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            fps=cap.get(cv2.CAP_PROP_FPS),
            frames=cap.get(cv2.CAP_PROP_FRAME_COUNT),
        )
    finally:
        cap.release()
    if header.width <= 0 or header.height <= 0 or not header.fps or header.fps <= 0             or not header.frames or header.frames <= 0:
        return None
    return header


def video_frame_size(video_path) -> tuple[int, int] | None:
    header = video_header(video_path)
    return (header.width, header.height) if header else None
