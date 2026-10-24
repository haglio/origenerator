"""One file dialog for every field that takes a file from outside the gallery."""
from __future__ import annotations

from PyQt6.QtWidgets import QFileDialog, QWidget

from origenerator.media import MediaType

FILE_FILTERS = {
    MediaType.IMAGE: "Images (*.png *.jpg *.jpeg *.webp);;All Files (*)",
    MediaType.VIDEO: "Videos (*.mp4 *.webm *.mkv *.mov);;All Files (*)",
}
AUDIO_FILE_FILTER = "Audio (*.wav *.mp3 *.flac *.m4a *.ogg);;All Files (*)"


def pick_a_file(parent: QWidget | None, what: str, file_filter: str,
                start: str = "") -> str | None:
    path, _ = QFileDialog.getOpenFileName(parent, f"Select {what}", start, file_filter)
    return path or None
