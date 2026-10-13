"""The drag payload that names a generation by prompt_id.

Shared by every drag source — the gallery's browser thumbnails and the generate
tab's preview — and by every drop target that reads it: Combine's slots and the
settings tabs' Start Image. Kept in its own module so a plain media widget doesn't
have to depend on the thumbnail widget just for the type.
"""
from __future__ import annotations

from PyQt6.QtCore import QByteArray, QMimeData

GENERATION_MIME = "application/x-origenerator-generation"


def generation_mime(prompt_id: str) -> QMimeData:
    """The drag payload naming a generation by prompt_id, for a drop target to read."""
    mime = QMimeData()
    mime.setData(GENERATION_MIME, QByteArray(prompt_id.encode("utf-8")))
    return mime


def dropped_generation(mime: QMimeData) -> str | None:
    if not mime.hasFormat(GENERATION_MIME):
        return None
    return bytes(mime.data(GENERATION_MIME)).decode("utf-8")
