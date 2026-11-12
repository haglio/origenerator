from __future__ import annotations

from PySide6.QtCore import QByteArray, QMimeData

GENERATION_MIME = "application/x-origenerator-generation"


def generation_mime(prompt_id: str) -> QMimeData:
    mime = QMimeData()
    mime.setData(GENERATION_MIME, QByteArray(prompt_id.encode("utf-8")))
    return mime


def dragged_generation(mime) -> str | None:
    if not mime.hasFormat(GENERATION_MIME):
        return None
    return bytes(mime.data(GENERATION_MIME)).decode("utf-8")
