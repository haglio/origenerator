"""What else in the library a shown generation is tied to.

The links under a config tab's settings form: a section headed Source holding
the item this row was built from and, beside it, the video whose settings
Combine ran on it, then the videos an image was animated into. A video has a
Source and no animations, an image the other way round.

"Built from" is one slot answering three relations, because they are one
question: a video's start frame, the item a spoken request revised, and — for the
single cycle the Genau lane cuts out of a clip — the clip it was cut out of.

Fed one row at a time and nothing else: the panel that owns it reads the library
and hands over the rows this needs, so this touches no database and can be stood
up on its own. It is deliberately not the whole of what a tab says about the row
on display: the File/Created block is the rest, and it sits ABOVE the form,
where what the settings made is named before the settings themselves.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from shared_ui.spacing import GAP_MEDIUM

from origenerator.config import OUTPUT_PLACES, THUMB_DIR
from origenerator.gallery import (
    animated_preview_path,
    find_source_image_id,
    media_type_of_row,
    videos_from_source_image,
)
from origenerator.gui.animated_strip import AnimatedVideoStrip
from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.source_tile import SourceTile
from origenerator.media import MediaType

logger = logging.getLogger(__name__)

# Most animation previews shown for one image at once. A prolific image can have
# dozens, and a strip of dozens is a wall rather than a set of links.
ANIMATED_STRIP_LIMIT = 8


class RelatedMedia(QWidget):
    """The links under a tab's form, about the row on display."""

    source_activated = pyqtSignal(str)     # a source tile was clicked (prompt_id)
    animated_activated = pyqtSignal(str)   # an animation tile was clicked (prompt_id)

    def __init__(self, parent=None, *, video_rows=None,
                 row_of: Callable[[str], dict | None],
                 name_of: Callable[[str], str]):
        """``video_rows`` answers the library's videos, and is asked only for a
        row that could have animations, or is a cycle cut out of one of them —
        which is why it is a call rather than a list. Reading it is a whole-table
        read and a parse per row, and every video shown would otherwise pay for
        it to be told it has none.
        """
        super().__init__(parent)
        self._video_rows = video_rows or (list)
        self._row_of = row_of
        self._name_of = name_of
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(GAP_MEDIUM)
        self._source_tile = SourceTile()
        self._source_video_tile = SourceTile()
        self._source_section = self._section_holding(self._source_tile,
                                                     self._source_video_tile)
        layout.addWidget(self._source_section)
        self._animated_strip = AnimatedVideoStrip()
        self._animated_strip.video_activated.connect(self.animated_activated)
        layout.addWidget(self._animated_strip)

    def _section_holding(self, *tiles: SourceTile) -> CollapsibleSection:
        side_by_side = QWidget()
        row = QHBoxLayout(side_by_side)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(GAP_MEDIUM)
        for tile in tiles:
            tile.activated.connect(self.source_activated)
            row.addWidget(tile)
        row.addStretch(1)
        section = CollapsibleSection("Source")
        section.content_form().addRow(side_by_side)
        section.hide()
        return section

    def show_row(self, row: dict, image_rows: list[dict], request=None) -> None:
        """Point at what ``row`` is tied to, and at nothing the last one was.

        ``image_rows`` is the pool a video's start frame is matched against —
        the owner's, because the owner is what holds the library. ``request`` is
        the spoken request that made this row, when one did.
        """
        self._show_source_tile(row, image_rows, request)
        self._show_source_video_tile(row)
        self._source_section.setVisible(
            not (self._source_tile.isHidden() and self._source_video_tile.isHidden()))
        # Hides itself when empty, which for anything but an animated image it is.
        self._animated_strip.show_videos(self._animated_items(row))

    def is_source_folded(self) -> bool:
        return self._source_section.is_collapsed()

    def set_source_folded(self, folded: bool) -> None:
        self._source_section.set_collapsed(folded)

    def clear(self) -> None:
        """Put every link down — the tab has no generation on display."""
        self._source_tile.clear()
        self._source_video_tile.clear()
        self._source_section.hide()
        self._animated_strip.hide()

    def _show_source_tile(self, row: dict, image_rows: list[dict], request=None):
        """Reveal the source tile for whatever this row was built from, else hide
        it. The tile shows that item's thumbnail and name and names it on
        click, for the owner to navigate to.
        """
        source_row, heading, media_type = self._built_from(row, image_rows, request)
        if not source_row:
            self._source_tile.clear()
            return
        self._source_tile.show_source(
            source_row["prompt_id"], source_row.get("thumbnail_path"),
            self._name_of(source_row["prompt_id"]),
            heading=heading, media_type=media_type,
        )

    def _show_source_video_tile(self, row: dict) -> None:
        video_id = row.get("recipe_video_id")
        video = self._row_of(video_id) if video_id else None
        if video is None:
            self._source_video_tile.clear()
            return
        self._source_video_tile.show_source(
            video["prompt_id"], video.get("thumbnail_path"),
            self._name_of(video["prompt_id"]),
            heading="From source video", media_type=MediaType.VIDEO, gray=True,
        )

    def _built_from(self, row: dict, image_rows: list[dict], request):
        """``(the row this was built from, what to head the tile, its kind)``.

        Three relations, most particular first. A cycle the Genau lane cut is
        the only one whose source is a VIDEO, and it has to be asked about first:
        a cut carries its source clip's params, start frame included, so asking
        for a start frame would answer with the picture the ORIGINAL was animated
        from and quietly point the link past the clip the user is looking for. A
        video that is not a cut links to its start frame; something a spoken
        request made links to the item the request was asked about — a requested
        image has no start frame, and a requested video's start frame is the one
        it already had.
        """
        cut_from = row.get("trimmed_from")
        if cut_from:
            clip = next((v for v in self._video_rows()
                         if v.get("prompt_id") == cut_from), None)
            if clip is not None:
                return clip, "Trimmed from", MediaType.VIDEO
        source_id = find_source_image_id(row, image_rows)
        if source_id:
            frame = next(
                (r for r in image_rows if r.get("prompt_id") == source_id), None)
            if frame is not None:
                return frame, None, MediaType.IMAGE
        if request is not None and request.get("source_row"):
            asked_about = request["source_row"]
            return asked_about, "Requested from", media_type_of_row(asked_about)
        return None, None, None

    def _animated_items(self, row: dict) -> list[tuple]:
        """(prompt_id, looping-preview path, still path) for each video an image
        was animated into — empty for anything but an image with animations.

        The library's videos are asked for only past that first test, so showing
        a video costs no read at all.
        """
        if media_type_of_row(row) != MediaType.IMAGE:
            return []
        videos = videos_from_source_image(row, self._video_rows())
        if len(videos) > ANIMATED_STRIP_LIMIT:
            logger.info("Image %s has %d animations; showing the first %d",
                        row["prompt_id"], len(videos), ANIMATED_STRIP_LIMIT)
        return [
            (v["prompt_id"], animated_preview_path(v, OUTPUT_PLACES, THUMB_DIR),
             v.get("thumbnail_path"))
            for v in videos[:ANIMATED_STRIP_LIMIT]
        ]
