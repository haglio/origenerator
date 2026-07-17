"""The drag payload that names a generation by prompt_id.

Shared by every drag source — the gallery's browser thumbnails and the generate
tab's preview — and by the combine drop slots that read it, so any of them can be
dragged onto a slot with the same contract. Kept in its own module so a plain
media widget doesn't have to depend on the thumbnail widget just for the type.
"""

from PyQt6.QtCore import QByteArray, QMimeData

# A dragged generation carries its prompt_id under this type; a combine drop slot
# reads it to know which image or video was dropped.
GENERATION_MIME = "application/x-origenerator-generation"


def generation_mime(prompt_id: str) -> QMimeData:
    """The drag payload naming a generation by prompt_id, for a drop slot to read."""
    mime = QMimeData()
    mime.setData(GENERATION_MIME, QByteArray(prompt_id.encode("utf-8")))
    return mime
