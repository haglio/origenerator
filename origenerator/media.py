"""Media-type vocabulary shared by ingestion and the gallery.

A single source of truth for which file extensions count as images vs videos,
so the importer and the gallery model classify outputs identically.
"""

from pathlib import Path

IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp"})
VIDEO_EXTS = frozenset({".mp4", ".webm"})


def media_type_from_filename(filename: str) -> str | None:
    """Return ``"image"``/``"video"`` from a filename's extension, else ``None``."""
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    return None


def sibling_of_type(path: Path, media: str) -> Path | None:
    """A file beside ``path`` with the same stem but a ``media``-type extension.

    This is how a video and its VHS_VideoCombine metadata-PNG sidecar find each
    other — shared by import (which folds them into one entry) and deletion
    (which removes both so a re-import can't resurrect the orphan).
    """
    exts = IMAGE_EXTS if media == "image" else VIDEO_EXTS
    for ext in sorted(exts):
        sibling = path.with_suffix(ext)
        if sibling != path and sibling.exists():
            return sibling
    return None
