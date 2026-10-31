"""The drag payload that names a generation by prompt_id.

Shared by every drag source — the gallery's browser thumbnails and the generate
tab's preview — and by what reads it, the Combine drop zones and the folders of
your own in the TOC, so any of them can be dragged onto any of those with the same
contract. Kept in its own module so a plain media widget doesn't have to depend on
the item tile just for the type.
"""
from __future__ import annotations

from PyQt6.QtCore import QByteArray, QMimeData

# A dragged generation carries its prompt_id under this type.
GENERATION_MIME = "application/x-origenerator-generation"


def generation_mime(prompt_id: str) -> QMimeData:
    """The drag payload naming a generation by prompt_id, for a drop zone to read."""
    mime = QMimeData()
    mime.setData(GENERATION_MIME, QByteArray(prompt_id.encode("utf-8")))
    return mime


def dragged_generation(mime) -> str | None:
    """The prompt_id a drag names, or ``None`` for a drag of anything else."""
    if not mime.hasFormat(GENERATION_MIME):
        return None
    return bytes(mime.data(GENERATION_MIME)).decode("utf-8")
