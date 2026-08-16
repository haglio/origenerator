"""A card for one in-flight generation, on the gallery's Recents shelf.

The shelf leads with a card per generation currently queued or running — from a
Generate tab or a gallery re-roll — so all in-flight work is visible in one
place. Each card mirrors the job's latest live preview frame (or a
"Generating…/Queued…" placeholder until one arrives) and, when clicked, opens the
gallery folder the job is running in and selects its live tile.

A card is fed by an :class:`origenerator.gui.inflight.InFlightItem`, so this
widget stays unaware of where a job comes from or how it is revealed. The gallery
holds the items and calls ``reveal`` on a click.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, pyqtSignal

from origenerator.gui.inflight import InFlightItem, queue_wait_text
from origenerator.gui.media_badge import MediaBadge

_CARD_SIZE = (180, 200)   # matches ThumbnailWidget so cards flow with finished tiles
_IMAGE_SIZE = (172, 160)
_BORDER = "2px solid #3080e0"  # a blue "in progress" edge, distinct from a resting tile


class InFlightCard(QWidget):
    """A clickable card mirroring one in-flight generation's live frame and status."""

    clicked = pyqtSignal(str)   # the item's key

    def __init__(self, item: InFlightItem, parent=None):
        super().__init__(parent)
        self._key = item.key
        self.setObjectName("thumbnailTile")  # share the finished-tile background
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(*_CARD_SIZE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self._image = QLabel()
        self._image.setFixedSize(*_IMAGE_SIZE)
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setWordWrap(True)  # the queue-wait line is a sentence, not a word
        self._image.setStyleSheet(
            f"background-color: transparent; border: {_BORDER}; border-radius: 3px;"
        )
        self._caption = QLabel()
        self._caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._caption.setWordWrap(True)
        self._caption.setMaximumHeight(30)
        self._caption.setStyleSheet("background-color: transparent;")

        # Let clicks fall through the children to the card itself.
        self._image.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout.addWidget(self._image)
        layout.addWidget(self._caption)
        self.update_item(item)

        # The kind is fixed for a job, so the badge is placed once here (not in the
        # in-place update_item). It matches the badge a finished tile will wear.
        if item.media_type:
            MediaBadge(item.media_type, self)

    @property
    def key(self) -> str:
        return self._key

    def update_item(self, item: InFlightItem):
        """Refresh the card in place from a fresh descriptor — a new live frame or a
        queued→running flip — so a live update never rebuilds the whole shelf."""
        self._caption.setText(item.caption)
        pixmap = QPixmap()
        if item.frame and pixmap.loadFromData(item.frame) and not pixmap.isNull():
            self._image.setPixmap(pixmap.scaled(
                *_IMAGE_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            # No frame yet: name the stage instead of showing a blank square —
            # and when ComfyUI is what's holding it up, say how much is in front.
            self._image.setText(
                queue_wait_text(item.foreign_ahead)
                or ("Generating…" if item.status == "running" else "Queued…")
            )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._key)
