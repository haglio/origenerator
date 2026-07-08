"""The image an image-to-video was built from, shown as a clickable tile.

In the info pane of a video generation: the source image's thumbnail beside its
filename, under a "From source image" heading. Clicking anywhere on it emits
``activated`` with the source image's prompt_id, so the gallery navigates to it —
the same jump the old bare text link made, now with a real thumbnail.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, pyqtSignal

_THUMB = 120


class SourceImageTile(QWidget):
    """A clickable thumbnail with its filename beneath, for a video's source image.

    Laid out like the gallery's other thumbnail tiles — the caption sits under the
    image, not beside it. ``show_source`` fills and reveals it; ``clear`` hides it
    and forgets the id so a stale click can't navigate. A left click emits
    ``activated(prompt_id)``.
    """

    activated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._prompt_id: str | None = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        heading = QLabel("From source image")
        heading.setStyleSheet("font-weight: 600;")
        box.addWidget(heading)

        self._thumb = QLabel()
        self._thumb.setFixedSize(_THUMB, _THUMB)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self._thumb, 0, Qt.AlignmentFlag.AlignLeft)
        self._filename = QLabel()
        self._filename.setWordWrap(True)
        self._filename.setMaximumWidth(_THUMB * 2)  # wrap under the thumbnail, not across the pane
        box.addWidget(self._filename, 0, Qt.AlignmentFlag.AlignLeft)

        self.hide()

    def show_source(self, prompt_id: str, thumbnail_path, filename: str):
        self._prompt_id = prompt_id
        self._filename.setText(filename)
        self._thumb.setPixmap(self._scaled_thumb(thumbnail_path))
        self.show()

    def clear(self):
        self._prompt_id = None
        self.hide()

    def _scaled_thumb(self, thumbnail_path) -> QPixmap:
        """The thumbnail scaled to the tile, or an empty pixmap when the file is
        missing or unset — a blank square, never a crash."""
        pixmap = QPixmap(str(thumbnail_path)) if thumbnail_path else QPixmap()
        if pixmap.isNull():
            return QPixmap()
        return pixmap.scaled(
            _THUMB, _THUMB,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._prompt_id:
            self.activated.emit(self._prompt_id)
