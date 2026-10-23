"""The item a generation was built from, shown as a clickable thumbnail tile.

Under a config tab's form: the item's thumbnail with its name centered beneath,
styled like the gallery's other thumbnail tiles — a thin border and a media-type
badge in the corner. Clicking anywhere emits ``activated`` with the item's
prompt_id, so the gallery navigates to it.

A video's start frame is what it shows most often. The other relations borrow
it — the item a spoken request revised, the clip a cycle was cut out of, the
video whose settings Combine ran — which is why its heading, its badge and
whether its picture is drained of color are set with each showing.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget
from shared_ui.colors import BORDER_SUBTLE

from origenerator.gui import grid_card
from origenerator.gui.grayscale import grayscale_pixmap
from origenerator.gui.link_heading import link_heading
from origenerator.gui.media_badge import MediaBadge
from origenerator.gui.thumbnail_box import THUMBNAIL_BOX, fitted_in_the_box
from origenerator.media import MediaType

# What the tile says and draws when a showing names neither: a video's start
# frame, which is what this slot was built for and still shows most often.
_DEFAULT_HEADING = "From source image"
_DEFAULT_MEDIA_TYPE = MediaType.IMAGE


class SourceTile(QWidget):
    """A clickable thumbnail with its name centered beneath, for what a
    generation was built from.

    ``show_source`` fills and reveals it; ``clear`` hides it and forgets the id so
    a stale click can't navigate. A left click emits ``activated(prompt_id)``.
    """

    activated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._prompt_id: str | None = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        self._heading = link_heading(_DEFAULT_HEADING)
        column.addWidget(self._heading, 0, Qt.AlignmentFlag.AlignHCenter)

        self._thumb = QLabel()
        self._thumb.setFixedSize(THUMBNAIL_BOX)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setStyleSheet(
            f"border: 1px solid {BORDER_SUBTLE.name()}; border-radius: 3px;"
        )
        column.addWidget(self._thumb, 0, Qt.AlignmentFlag.AlignHCenter)
        # A photo (or play) badge in the thumbnail's top-left corner, like the
        # gallery tiles.
        self._badge = MediaBadge(_DEFAULT_MEDIA_TYPE, self._thumb)

        self._name = QLabel()
        self._name.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        grid_card.style_caption(self._name)
        column.addWidget(self._name, 0, Qt.AlignmentFlag.AlignHCenter)

        self.hide()

    def show_source(self, prompt_id: str, thumbnail_path, name: str,
                    heading: str | None = None, media_type: str | None = None,
                    gray: bool = False):
        """Point the tile at an item. ``heading`` names the relation when it
        isn't the usual one — "requested from" for what a request revised,
        "trimmed from" for the clip a single cycle was cut out of, "from source
        video" for the video whose settings Combine ran. The last two are
        videos, so ``media_type`` moves the badge with them, and ``gray`` drains
        the one shown only for its settings. All three are per-showing, because
        the next row put in this tile may be a different relation to a
        different kind of thing."""
        self._prompt_id = prompt_id
        self._heading.setText(heading or _DEFAULT_HEADING)
        self._badge.set_media_type(media_type or _DEFAULT_MEDIA_TYPE)
        self._name.setText(name)
        thumb = self._scaled_thumb(thumbnail_path)
        self._thumb.setPixmap(grayscale_pixmap(thumb) if gray else thumb)
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
        return fitted_in_the_box(pixmap)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._prompt_id:
            self.activated.emit(self._prompt_id)
