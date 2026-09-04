"""What else in the library a shown generation is tied to.

Two links, stacked under a config tab's settings form: the item this row was
built from, and the videos an image was animated into. They are mutually
exclusive in practice — a video has a start frame and no animations, an image is
the other way round — and both are hidden whenever the tab is blank or showing a
bare autoshow rather than a generation someone chose.

Fed one row at a time and nothing else: the panel that owns it reads the library
and hands over the rows this needs, so this touches no database and can be stood
up on its own. It is deliberately not the whole of what a tab says about the row
on display: the File/Created block is the rest, and it sits ABOVE the form,
where what the settings made is named before the settings themselves.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from origenerator.config import COMFYUI_OUTPUT_DIR, THUMB_DIR
from origenerator.gallery import (
    animated_preview_path,
    find_source_image_id,
    media_type_of_row,
    row_output_files,
    videos_from_source_image,
)
from origenerator.gui.animated_strip import AnimatedVideoStrip
from origenerator.gui.source_image_tile import SourceImageTile

logger = logging.getLogger(__name__)

# Most animation previews shown for one image at once. A prolific image can have
# dozens, and a strip of dozens is a wall rather than a set of links.
ANIMATED_STRIP_LIMIT = 8


class RelatedMedia(QWidget):
    """The links under a tab's form, about the row on display."""

    source_activated = pyqtSignal(str)     # the source tile was clicked (prompt_id)
    animated_activated = pyqtSignal(str)   # an animation tile was clicked (prompt_id)

    def __init__(self, parent=None, *, video_rows=None):
        """``video_rows`` answers the library's videos, and is asked only for a
        row that could have animations — which is why it is a call rather than a
        list. Reading it is a whole-table read and a parse per row, and every
        video shown would otherwise pay for it to be told it has none.
        """
        super().__init__(parent)
        self._video_rows = video_rows or (list)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        # One tile, one place: the start frame for a video, and for something a
        # spoken request made, the item it was asked about — the same kind of
        # link (this came from that) in the same spot, rather than a second tile
        # teaching the reader a second place to look.
        self._source_tile = SourceImageTile()
        self._source_tile.activated.connect(self.source_activated)
        layout.addWidget(self._source_tile)
        self._animated_strip = AnimatedVideoStrip()
        self._animated_strip.video_activated.connect(self.animated_activated)
        layout.addWidget(self._animated_strip)

    def show_row(self, row: dict, image_rows: list[dict], request=None) -> None:
        """Point at what ``row`` is tied to, and at nothing the last one was.

        ``image_rows`` is the pool a video's start frame is matched against —
        the owner's, because the owner is what holds the library. ``request`` is
        the spoken request that made this row, when one did.
        """
        self._show_source_tile(row, image_rows, request)
        # Hides itself when empty, which for anything but an animated image it is.
        self._animated_strip.show_videos(self._animated_items(row))

    def clear(self) -> None:
        """Put both links down — a blank tab, or one showing a bare autoshow
        rather than a generation someone chose."""
        self._source_tile.clear()
        self._animated_strip.hide()

    def _show_source_tile(self, row: dict, image_rows: list[dict], request=None):
        """Reveal the source tile for whatever this row was built from, else hide
        it. The tile shows that item's thumbnail and filename and names it on
        click, for the owner to navigate to.

        For a video that is its start frame. For something a spoken request made
        it is the item the request was asked about — the same relation in the
        same place, since a requested image has no start frame and a requested
        video's start frame is the one it already had.
        """
        source_id = find_source_image_id(row, image_rows)
        source_row = next(
            (r for r in image_rows if r.get("prompt_id") == source_id), None
        ) if source_id else None
        heading = None
        if source_row is None and request is not None:
            source_row = request.get("source_row")
            heading = "Requested from"
        if not source_row:
            self._source_tile.clear()
            return
        files = row_output_files(source_row)
        self._source_tile.show_source(
            source_row["prompt_id"], source_row.get("thumbnail_path"),
            files[0]["filename"] if files else "", heading=heading,
        )

    def _animated_items(self, row: dict) -> list[tuple]:
        """(prompt_id, looping-preview path, still path) for each video an image
        was animated into — empty for anything but an image with animations.

        The library's videos are asked for only past that first test, so showing
        a video costs no read at all.
        """
        if media_type_of_row(row) != "image":
            return []
        videos = videos_from_source_image(row, self._video_rows())
        if len(videos) > ANIMATED_STRIP_LIMIT:
            logger.info("Image %s has %d animations; showing the first %d",
                        row["prompt_id"], len(videos), ANIMATED_STRIP_LIMIT)
        return [
            (v["prompt_id"], animated_preview_path(v, COMFYUI_OUTPUT_DIR, THUMB_DIR),
             v.get("thumbnail_path"))
            for v in videos[:ANIMATED_STRIP_LIMIT]
        ]
