"""The image an image-to-video was built from, shown as a clickable thumbnail tile.

In the info pane of a video generation: the source image's thumbnail with its
filename centered beneath, styled like the gallery's other thumbnail tiles — a
thin border and a media-type badge in the corner. Clicking anywhere emits
``activated`` with the source image's prompt_id, so the gallery navigates to it.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, pyqtSignal

from origenerator.gui.media_badge import MediaBadge
from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()

from shared_ui.colors import BORDER_SUBTLE

_THUMB = 120


class SourceImageTile(QWidget):
    """A clickable thumbnail with its filename centered beneath, for a video's
    source image.

    ``show_source`` fills and reveals it; ``clear`` hides it and forgets the id so
    a stale click can't navigate. A left click emits ``activated(prompt_id)``.
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
        self._thumb.setStyleSheet(
            f"border: 1px solid {BORDER_SUBTLE.name()}; border-radius: 3px;"
        )
        box.addWidget(self._thumb, 0, Qt.AlignmentFlag.AlignLeft)
        # A photo badge in the thumbnail's top-left corner, like the gallery tiles.
        MediaBadge("image", self._thumb)

        self._filename = QLabel()
        self._filename.setFixedWidth(_THUMB)  # match the thumb so the caption centers under it
        self._filename.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        box.addWidget(self._filename, 0, Qt.AlignmentFlag.AlignLeft)

        self.hide()

    def show_source(self, prompt_id: str, thumbnail_path, filename: str):
        self._prompt_id = prompt_id
        # A spaceless filename can't wrap, so middle-elide it to the tile width and
        # keep the full name in the tooltip.
        elided = self._filename.fontMetrics().elidedText(
            filename, Qt.TextElideMode.ElideMiddle, _THUMB
        )
        self._filename.setText(elided)
        self._filename.setToolTip(filename)
        self._thumb.setPixmap(self._scaled_thumb(thumbnail_path))
        self.show()

    def clear(self):
        self._prompt_id = None
        self.hide()

    def _scaled_thumb(self, thumbnail_path) -> QPixmap:
        """The thumbnail scaled to the tile, or an empty pixmap when the file is
        missing or unset — a blank bordered square, never a crash."""
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
