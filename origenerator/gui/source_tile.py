from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from shared_ui.colors import BORDER_SUBTLE
from shared_ui.spacing import BUTTON_RADIUS, GAP_SMALL

from origenerator.gui import tile_shape
from origenerator.gui.grayscale import grayscale_pixmap
from origenerator.gui.item_type_icon import ItemTypeIcon
from origenerator.gui.link_heading import link_heading
from origenerator.gui.looping_preview import play_gray_in, play_in, stop_what_plays_in
from origenerator.gui.thumbnail_box import THUMBNAIL_BOX, fitted_in_the_box
from origenerator.media import MediaType

_DEFAULT_HEADING = "From source image"
_DEFAULT_MEDIA_TYPE = MediaType.IMAGE
_WORDS_ON_ONE_LINE = 3


def _in_lines(heading: str, width_of) -> str:
    words = heading.split()
    if len(words) <= _WORDS_ON_ONE_LINE:
        return heading
    lines = min((([" ".join(words[:at]), " ".join(words[at:])]) for at in range(1, len(words))),
                key=lambda pair: max(map(width_of, pair)))
    return "\n".join(lines)


class SourceTile(QWidget):
    activated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._prompt_id: str | None = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(GAP_SMALL)
        self._heading = link_heading(_DEFAULT_HEADING)
        self._heading.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
        self._heading.setMinimumHeight(2 * self._heading.fontMetrics().lineSpacing())
        column.addWidget(self._heading, 0, Qt.AlignmentFlag.AlignHCenter)

        self._thumb = QLabel()
        self._thumb.setFixedSize(THUMBNAIL_BOX)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setStyleSheet(
            f"border: 1px solid {BORDER_SUBTLE.name()}; border-radius: {BUTTON_RADIUS}px;"
        )
        column.addWidget(self._thumb, 0, Qt.AlignmentFlag.AlignHCenter)
        self._item_type_icon = ItemTypeIcon(_DEFAULT_MEDIA_TYPE, self._thumb)

        self._name = QLabel()
        self._name.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        tile_shape.style_caption(self._name)
        column.addWidget(self._name, 0, Qt.AlignmentFlag.AlignHCenter)

        self.hide()

    @property
    def prompt_id(self) -> str | None:
        return self._prompt_id

    @property
    def heading(self) -> str:
        return self._heading.text().replace("\n", " ")

    def show_source(self, row: dict, name: str, heading: str | None = None,
                    media_type: str | None = None, movie: str | None = None,
                    gray: bool = False):
        self._prompt_id = row["prompt_id"]
        self._heading.setText(_in_lines(heading or _DEFAULT_HEADING,
                                        self._heading.fontMetrics().horizontalAdvance))
        self._item_type_icon.set_media_type(media_type or _DEFAULT_MEDIA_TYPE)
        self._name.setText(name)
        if movie:
            (play_gray_in if gray else play_in)(self._thumb, movie, THUMBNAIL_BOX)
        else:
            stop_what_plays_in(self._thumb)
            thumb = self._scaled_thumb(row.get("thumbnail_path"))
            self._thumb.setPixmap(grayscale_pixmap(thumb) if gray else thumb)
        self.show()

    def clear(self):
        self._prompt_id = None
        self.hide()

    def _scaled_thumb(self, thumbnail_path) -> QPixmap:
        pixmap = QPixmap(str(thumbnail_path)) if thumbnail_path else QPixmap()
        if pixmap.isNull():
            return QPixmap()
        return fitted_in_the_box(pixmap)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._prompt_id:
            self.activated.emit(self._prompt_id)
