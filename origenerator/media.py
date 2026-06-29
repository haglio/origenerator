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
