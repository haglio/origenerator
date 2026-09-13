"""Media-type vocabulary shared by ingestion and the gallery.

A single source of truth for which file extensions count as images vs videos,
so the importer and the gallery model classify outputs identically.
"""
from __future__ import annotations

from enum import StrEnum
from pathlib import Path

IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp"})
VIDEO_EXTS = frozenset({".mp4", ".webm"})


class MediaType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"


def media_type_from_filename(filename: str) -> MediaType | None:
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTS:
        return MediaType.IMAGE
    if ext in VIDEO_EXTS:
        return MediaType.VIDEO
    return None


def sibling_of_type(path: Path, media: MediaType) -> Path | None:
    """A file beside ``path`` with the same stem but a ``media``-type extension.

    This is how a video and its VHS_VideoCombine metadata-PNG sidecar find each
    other — shared by import (which folds them into one entry) and deletion
    (which removes both so a re-import can't resurrect the orphan).
    """
    exts = IMAGE_EXTS if media == MediaType.IMAGE else VIDEO_EXTS
    for ext in sorted(exts):
        sibling = path.with_suffix(ext)
        if sibling != path and sibling.exists():
            return sibling
    return None
