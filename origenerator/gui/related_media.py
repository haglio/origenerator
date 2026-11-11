from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from shared_ui.spacing import GAP_MEDIUM

from origenerator.gallery import (
    media_type_of_row,
    start_images_among,
    videos_from_source_image,
    was_made_from,
    was_taken_from,
)
from origenerator.gui.change_tip import change_tip
from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.source_tile import SourceTile
from origenerator.gui.trash_box import TILE_GAP, place_tiles
from origenerator.media import MediaType
from origenerator.output_files import produced_output
from origenerator.voice.dictation import words_of


def _is_request(record: dict | None) -> bool:
    return bool(words_of(record))


def _change_tip(record: dict, before: dict | None, after: dict | None) -> str:
    return change_tip((before or {}).get("thumbnail_path"), (after or {}).get("thumbnail_path"),
                      tuple(record.get(side) or "" for side in (
                          "old_positive", "old_negative", "new_positive", "new_negative")))


LINKS = "Links"
ANIMATED_FROM = "Animated from"
ANIMATED_FROM_STARTING_FRAME_OF = "Animated from starting frame of"
ANIMATED_USING_VIDEO_SETTINGS_OF = "Animated using video settings of"
ANIMATED_INTO = "Animated into"
STARTING_FRAME_ANIMATED_INTO = "Starting frame animated into"
VIDEO_SETTINGS_USED_FOR_ANIMATION_OF = "Video settings used for animation of"
TRIMMED_FROM = "Trimmed from"
TRIMMED_INTO = "Trimmed into"


class _LinkRow(QWidget):
    activated = pyqtSignal(str)

    def __init__(self, movie_of: Callable[[dict], str | None]):
        super().__init__()
        self._movie_of = movie_of
        self._flow = FlowLayout(self, spacing=TILE_GAP)
        self.hide()

    def show_links(self, links: list[tuple[str, dict]], name_of: Callable[[str], str],
                   in_trash: frozenset[str] = frozenset(),
                   tips: dict[str, str] | None = None) -> None:
        while self._flow.count():
            placed = self._flow.takeAt(0).widget()
            placed.setParent(None)
            placed.deleteLater()
        tiles = [(self._tile(heading, row, name_of, (tips or {}).get(row["prompt_id"], "")),
                  row["prompt_id"] in in_trash)
                 for heading, row in links]
        place_tiles(tiles, self._flow.addWidget)
        for tile, _held in tiles:
            tile.show()
        self.setVisible(bool(links))

    def _tile(self, heading: str, row: dict, name_of, tip: str) -> SourceTile:
        tile = SourceTile()
        tile.setToolTip(tip)
        tile.activated.connect(self.activated)
        tile.show_source(row, name_of(row["prompt_id"]), heading=heading,
                         media_type=media_type_of_row(row), movie=self._movie_of(row),
                         gray=heading == ANIMATED_USING_VIDEO_SETTINGS_OF)
        return tile


@dataclass(frozen=True, kw_only=True)
class RelatedLookups:
    row_of: Callable[[str], dict | None]
    name_of: Callable[[str], str]
    animated_preview: Callable[[dict], str | None]
    request_of: Callable[[str], dict | None]
    requests_about: Callable[[str], list[dict]]
    video_rows: Callable[[], list[dict]] = list
    held_rows: Callable[[], list[dict]] = list


class RelatedMedia(QWidget):
    link_clicked = pyqtSignal(str)

    def __init__(self, lookups: RelatedLookups, parent=None):
        super().__init__(parent)
        self._video_rows = lookups.video_rows
        self._row_of = lookups.row_of
        self._name_of = lookups.name_of
        self._held_rows = lookups.held_rows
        self._animated_preview = lookups.animated_preview
        self._request_of = lookups.request_of
        self._requests_about = lookups.requests_about
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._section = CollapsibleSection(LINKS)
        layout.addWidget(self._section)
        rows_host = QWidget()
        rows = QVBoxLayout(rows_host)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(GAP_MEDIUM)
        self._section.content_form().addRow(rows_host)
        self._requests = _LinkRow(self._movie_of)
        self._batch_modified = _LinkRow(self._movie_of)
        self._animations = _LinkRow(self._movie_of)
        self._trims = _LinkRow(self._movie_of)
        for row in self._rows():
            row.activated.connect(self.link_clicked)
            rows.addWidget(row)
        self._follow_the_rows()

    def _movie_of(self, row: dict) -> str | None:
        return self._animated_preview(row) if media_type_of_row(row) == MediaType.VIDEO else None

    def _follow_the_rows(self) -> None:
        self.setVisible(any(not row.isHidden() for row in self._rows()))

    def show_row(self, row: dict, image_rows: list[dict]) -> None:
        start_image_of = start_images_among([*image_rows, *self._held_of_kind(MediaType.IMAGE)])
        videos = [video for video in (*self._video_rows(), *self._held_of_kind(MediaType.VIDEO))
                  if produced_output(video)]
        prompt_id = row.get("prompt_id")
        self.show_requests_and_batch_modified(prompt_id)
        trimmed_from, animated_from = self._made_from(row, start_image_of, videos)
        into = (STARTING_FRAME_ANIMATED_INTO if media_type_of_row(row) == MediaType.VIDEO
                else ANIMATED_INTO)
        self._animations.show_links(
            animated_from + self._settings_from(row)
            + [(into, video) for video in self._animated_videos(row, start_image_of, videos)]
            + self._made_with_settings_of(prompt_id, videos),
            self._name_of, self._trashed())
        self._trims.show_links(
            trimmed_from + [(TRIMMED_INTO, video) for video in videos
                            if prompt_id and video.get("trimmed_from") == prompt_id],
            self._name_of, self._trashed())
        self._follow_the_rows()

    def folds(self) -> dict[str, bool]:
        return {LINKS: self._section.is_collapsed()}

    def set_folds(self, saved: dict) -> None:
        folded = saved.get(LINKS)
        if isinstance(folded, bool):
            self._section.set_collapsed(folded)

    def _rows(self) -> tuple[_LinkRow, ...]:
        return (self._requests, self._batch_modified, self._animations, self._trims)

    def clear(self) -> None:
        for row in self._rows():
            row.show_links([], self._name_of)
        self._follow_the_rows()

    def _trimmed_from(self, row: dict) -> dict | None:
        return self._item(row["trimmed_from"]) if row.get("trimmed_from") else None

    def _source_of(self, row: dict, start_image_of) -> dict | None:
        trimmed = self._trimmed_from(row)
        if trimmed is not None:
            return trimmed
        frame = start_image_of(row)
        return frame if frame is not None and was_made_from(row, frame) else None

    def _made_from(self, row: dict, start_image_of, videos: list[dict]):
        trimmed = self._trimmed_from(row)
        if trimmed is not None:
            return [(TRIMMED_FROM, trimmed)], []
        frame = self._source_of(row, start_image_of)
        if frame is None:
            return [], []
        taken_from = next((video for video in videos if was_taken_from(frame, video)
                           and start_image_of(video) == frame), None)
        if taken_from is not None:
            return [], [(ANIMATED_FROM_STARTING_FRAME_OF, taken_from)]
        return [], [(ANIMATED_FROM, frame)]

    def _settings_from(self, row: dict) -> list[tuple[str, dict]]:
        video_id = row.get("source_video")
        video = self._item(video_id) if video_id else None
        return [(ANIMATED_USING_VIDEO_SETTINGS_OF, video)] if video is not None else []

    def _made_with_settings_of(self, prompt_id: str | None, videos: list[dict]) -> list:
        return [(VIDEO_SETTINGS_USED_FOR_ANIMATION_OF, video) for video in videos
                if prompt_id and video.get("source_video") == prompt_id]

    def show_requests_and_batch_modified(self, prompt_id: str | None) -> None:
        request = self._request_of(prompt_id) if prompt_id else None
        made_from = self._item(request["source_prompt_id"]) if request else None
        made_into = [(record, made)
                     for record in (self._requests_about(prompt_id) if prompt_id else [])
                     if (made := self._item(record["prompt_id"])) is not None]
        shown = self._item(prompt_id) if made_from is not None or made_into else None
        for links, is_request, from_heading, into_heading in (
                (self._requests, True, "Requested from", "Requested into"),
                (self._batch_modified, False, "Batch-modified from", "Batch-modified into")):
            here = ([(from_heading, made_from, request, (made_from, shown))]
                    if made_from is not None and _is_request(request) == is_request else [])
            here += [(into_heading, made, record, (shown, made)) for record, made in made_into
                     if _is_request(record) == is_request]
            links.show_links(
                [(heading, row) for heading, row, _record, _pair in here],
                self._name_of, self._trashed(),
                tips=None if is_request else {
                    row["prompt_id"]: _change_tip(record, *pair)
                    for _heading, row, record, pair in here})
        self._follow_the_rows()

    def _trashed(self) -> frozenset[str]:
        return frozenset(held["prompt_id"] for held in self._held_rows())

    def _held_of_kind(self, kind: MediaType) -> list[dict]:
        return [held for held in self._held_rows() if media_type_of_row(held) == kind]

    def _item(self, prompt_id: str) -> dict | None:
        return self._row_of(prompt_id) or next(
            (held for held in self._held_rows() if held["prompt_id"] == prompt_id), None)

    def _animated_videos(self, row: dict, start_image_of, videos: list[dict]) -> list[dict]:
        image = row
        if media_type_of_row(row) != MediaType.IMAGE:
            image = start_image_of(row)
            if image is None or not was_taken_from(image, row):
                return []
        could_name_it = videos_from_source_image(image, videos)
        return [video for video in could_name_it
                if (self._source_of(video, start_image_of) or {}).get("prompt_id")
                == image["prompt_id"]]
