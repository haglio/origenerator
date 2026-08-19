"""A card for one in-flight generation, on the gallery's Recents shelf.

The shelf leads with a card per generation currently queued or running — from a
Generate tab or a gallery re-roll — so all in-flight work is visible in one
place. Each card mirrors the job's latest live preview frame and, when clicked,
opens the gallery folder the job is running in and selects its live tile.

Two things are read over that frame rather than in place of it. The stage —
"Generating…", "Queued…", or what another app is holding the server for — sits
on a dimming scrim (:class:`origenerator.gui.stage_scrim.StageScrim`), the same
one a finished thumbnail wears while its enhancement cooks; and along the frame's
foot a bar carries how far along the run is and how long that has taken
(:func:`origenerator.timing.progress_status_label`), in the same words the bottom
strip's queue uses for the same job. A stage message that *replaced* the picture
hid the one thing worth looking at, and a percentage that lived only in the queue
left the card and the strip each telling half of one story.

A card is fed by an :class:`origenerator.gui.inflight.InFlightItem`, so this
widget stays unaware of where a job comes from or how it is revealed. The gallery
holds the items and calls ``reveal`` on a click.
"""

import time

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, QRect, QTimer, pyqtSignal

from origenerator.gui.inflight import InFlightItem, queue_wait_text
from origenerator.gui.media_badge import MediaBadge
from origenerator.gui.progress_caption import ProgressCaption
from origenerator.gui.stage_scrim import StageScrim
from origenerator.timing import progress_status_label

_CARD_SIZE = (180, 200)   # matches ThumbnailWidget so cards flow with finished tiles
_IMAGE_SIZE = (172, 160)
_BORDER_PX = 2
# A blue "in progress" edge, distinct from a resting tile's.
_BORDER = f"{_BORDER_PX}px solid #3080e0"
_BAR_HEIGHT = 26  # the bar laid along the frame's foot, the way a player's is
# How often the card re-reads the clock. Its own timer rather than the gallery's
# 1.5s poll, which would make a seconds count skip every other tick.
_TICK_MS = 1000


class InFlightCard(QWidget):
    """A clickable card mirroring one in-flight generation's live frame and status."""

    clicked = pyqtSignal(str)   # the item's key

    def __init__(self, item: InFlightItem, parent=None):
        super().__init__(parent)
        self._key = item.key
        self._item = item
        self.setObjectName("thumbnailTile")  # share the finished-tile background
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self._image = QLabel()
        self._image.setFixedSize(*_IMAGE_SIZE)
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
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

        # Both ride over the frame rather than taking a row of their own, so the
        # picture keeps the height a finished tile's has.
        self._scrim = StageScrim(self)
        self._bar = ProgressCaption(self)
        self._bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        # Its own clock rather than the gallery's poll, so the count advances a
        # second at a time whether or not a refresh has landed.
        self._tick = QTimer(self)
        self._tick.setInterval(_TICK_MS)
        self._tick.timeout.connect(self._render_timing)

        self.setFixedSize(*_CARD_SIZE)
        self._place_overlays()  # once: the card is a fixed size and never moves them
        self.update_item(item)

        # The kind is fixed for a job, so the badge is placed once here (not in the
        # in-place update_item). It matches the badge a finished tile will wear.
        if item.media_type:
            MediaBadge(item.media_type, self)

    @property
    def key(self) -> str:
        return self._key

    def update_item(self, item: InFlightItem):
        """Refresh the card in place from a fresh descriptor — a new live frame, a
        queued→running flip, another step of progress — so a live update never
        rebuilds the whole shelf."""
        self._item = item
        self._caption.setText(item.caption)
        pixmap = QPixmap()
        if item.frame and pixmap.loadFromData(item.frame) and not pixmap.isNull():
            self._image.setPixmap(pixmap.scaled(
                *_IMAGE_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        self._scrim.cover(self._image, self._stage_message(item), inset=_BORDER_PX)
        self._bar.raise_()  # the scrim it sits on was just raised over everything
        self._render_timing()
        # Only a job ComfyUI has actually started has a clock to advance; ticking a
        # queued one would redraw a line that cannot change.
        if item.started_at is None:
            self._tick.stop()
        else:
            self._tick.start()

    @staticmethod
    def _stage_message(item: InFlightItem) -> str:
        """What the scrim says about this job: the stage it is at, or — when the
        hold is another app's — what it is waiting behind."""
        return (queue_wait_text(item.foreign_ahead)
                or ("Generating…" if item.status == "running" else "Queued…"))

    def _render_timing(self):
        """Write the run's reading across the bar at the frame's foot.

        A job ComfyUI hasn't started has no elapsed time and no steps to report,
        so the bar stays indeterminate with nothing written on it: its wait is the
        queue's to explain, not a zero counting up over a bar that has not moved.
        """
        started = self._item.started_at
        elapsed = None if started is None else max(0.0, time.time() - started)
        self._bar.show_progress(
            # A tile's width takes the compact reading: how far along, and how
            # much longer. The strip's queue has the room for the elapsed count.
            progress_status_label(elapsed, self._item.progress,
                                  self._item.typical_seconds, compact=True),
            self._item.progress if self._item.status == "running" else None,
        )

    def _place_overlays(self):
        """Lay the bar along the frame's foot, inside the frame's own border so it
        doesn't sit on the blue edge (the scrim is placed by ``cover``).

        The frame is only positioned once the card's layout has run, so that is
        forced here rather than waited for: an overlay placed before it sits in
        the card's top-left corner instead of over the picture.
        """
        self.layout().activate()
        frame = self._image.geometry()
        self._bar.setGeometry(QRect(
            frame.x() + _BORDER_PX,
            frame.y() + frame.height() - _BORDER_PX - _BAR_HEIGHT,
            frame.width() - 2 * _BORDER_PX,
            _BAR_HEIGHT,
        ))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._key)
