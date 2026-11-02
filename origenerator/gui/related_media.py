from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from shared_ui.spacing import GAP_MEDIUM

from origenerator.gallery import (
    media_type_of_row,
    start_images_among,
    videos_from_source_image,
    was_made_from,
    was_taken_from,
)
from origenerator.gui.animations import Animations
from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.source_tile import SourceTile
from origenerator.media import MediaType
from origenerator.voice.dictation import words_of


def _is_request(record: dict | None) -> bool:
    return bool(words_of(record))


class _Links(CollapsibleSection):
    activated = pyqtSignal(str)

    def __init__(self, title: str):
        super().__init__(title)
        host = QWidget()
        self._flow = FlowLayout(host, spacing=GAP_MEDIUM)
        self.content_form().addRow(host)
        self._tiles: list[SourceTile] = []
        self.hide()

    def show_links(self, links: list[tuple[str, dict]], name_of: Callable[[str], str]) -> None:
        for tile in self._tiles:
            self._flow.removeWidget(tile)
            tile.setParent(None)
            tile.deleteLater()
        self._tiles = [self._tile(heading, row, name_of) for heading, row in links]
        for tile in self._tiles:
            self._flow.addWidget(tile)
        self.setVisible(bool(self._tiles))

    def _tile(self, heading: str, row: dict, name_of) -> SourceTile:
        tile = SourceTile()
        tile.activated.connect(self.activated)
        tile.show_source(row["prompt_id"], row.get("thumbnail_path"),
                         name_of(row["prompt_id"]), heading=heading,
                         media_type=media_type_of_row(row))
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
        layout.setSpacing(GAP_MEDIUM)
        self._source_tile = SourceTile()
        self._source_video_tile = SourceTile()
        self._source_section = self._source_section_of(self._source_tile,
                                                       self._source_video_tile)
        layout.addWidget(self._source_section)
        self._requests_section = _Links("Requests")
        self._modifications_section = _Links("Modifications")
        self._animations = Animations()
        self._animations.video_activated.connect(self.link_clicked)
        self._animations_section = CollapsibleSection("Animations")
        self._animations_section.content_form().addRow(self._animations)
        self._animations_section.hide()
        self._combine_section = _Links("Combine")
        self._trims_section = _Links("Trims")
        for section in (self._requests_section, self._modifications_section,
                        self._combine_section, self._trims_section):
            section.activated.connect(self.link_clicked)
        for section in self._sections():
            layout.addWidget(section)
        self._follow_the_sections()

    def _follow_the_sections(self) -> None:
        self.setVisible(any(not section.isHidden() for section in self._sections()))

    def _source_section_of(self, *tiles: SourceTile) -> CollapsibleSection:
        side_by_side = QWidget()
        row = QHBoxLayout(side_by_side)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(GAP_MEDIUM)
        for tile in tiles:
            tile.activated.connect(self.link_clicked)
            row.addWidget(tile)
        row.addStretch(1)
        section = CollapsibleSection("Source")
        section.content_form().addRow(side_by_side)
        section.hide()
        return section

    def show_row(self, row: dict, image_rows: list[dict]) -> None:
        start_image_of = start_images_among([*image_rows, *self._held_of_kind(MediaType.IMAGE)])
        videos = [*self._video_rows(), *self._held_of_kind(MediaType.VIDEO)]
        self._show_source_tile(row, start_image_of, videos)
        self._show_source_video_tile(row)
        self._source_section.setVisible(
            not (self._source_tile.isHidden() and self._source_video_tile.isHidden()))
        self.show_requests_and_modifications(row.get("prompt_id"))
        items = self._animated_items(row, start_image_of, videos)
        self._animations.set_heading("Starting frame animated in"
                                     if media_type_of_row(row) == MediaType.VIDEO else "")
        self._animations.show_videos(items)
        self._animations_section.setVisible(not self._animations.isHidden())
        self._show_videos_made_from(row.get("prompt_id"), videos)
        self._follow_the_sections()

    def folds(self) -> dict[str, bool]:
        return {section.title(): section.is_collapsed() for section in self._sections()}

    def set_folds(self, saved: dict) -> None:
        for section in self._sections():
            folded = saved.get(section.title())
            if isinstance(folded, bool):
                section.set_collapsed(folded)

    def _sections(self) -> tuple[CollapsibleSection, ...]:
        return (self._source_section, self._requests_section, self._modifications_section,
                self._animations_section, self._combine_section, self._trims_section)

    def clear(self) -> None:
        self._source_tile.clear()
        self._source_video_tile.clear()
        self._source_section.hide()
        self.show_requests_and_modifications(None)
        self._animations.hide()
        self._animations_section.hide()
        self._show_videos_made_from(None, [])
        self._follow_the_sections()

    def _show_source_tile(self, row: dict, start_image_of, videos: list[dict]):
        source_row, heading, media_type = self._built_from(row, start_image_of)
        if not source_row:
            self._source_tile.clear()
            return
        taken_from = next((video for video in videos if was_taken_from(source_row, video)
                           and start_image_of(video) == source_row), None)
        if taken_from is not None:
            source_row, heading, media_type = taken_from, "From starting frame of", MediaType.VIDEO
        self._source_tile.show_source(
            source_row["prompt_id"], source_row.get("thumbnail_path"),
            self._name_of(source_row["prompt_id"]),
            heading=heading, media_type=media_type,
        )

    def show_requests_and_modifications(self, prompt_id: str | None) -> None:
        request = self._request_of(prompt_id) if prompt_id else None
        made_from = self._item(request["source_prompt_id"]) if request else None
        made_into = [(record, made)
                     for record in (self._requests_about(prompt_id) if prompt_id else [])
                     if (made := self._item(record["prompt_id"])) is not None]
        for section, is_request, from_heading, into_heading in (
                (self._requests_section, True, "Requested from", "Requested into"),
                (self._modifications_section, False, "Modified from", "Modified into")):
            section.show_links(
                ([(from_heading, made_from)]
                 if made_from is not None and _is_request(request) == is_request else [])
                + [(into_heading, made) for record, made in made_into
                   if _is_request(record) == is_request],
                self._name_of)
        self._follow_the_sections()

    def _show_videos_made_from(self, prompt_id: str | None, videos: list[dict]) -> None:
        for section, names_it, heading in (
                (self._combine_section, "source_video", "Source video for"),
                (self._trims_section, "trimmed_from", "Trimmed into")):
            section.show_links([(heading, video) for video in videos
                                if prompt_id and video.get(names_it) == prompt_id],
                               self._name_of)

    def _show_source_video_tile(self, row: dict) -> None:
        video_id = row.get("source_video")
        video = self._item(video_id) if video_id else None
        if video is None:
            self._source_video_tile.clear()
            return
        self._source_video_tile.show_source(
            video["prompt_id"], video.get("thumbnail_path"),
            self._name_of(video["prompt_id"]),
            heading="From source video", media_type=MediaType.VIDEO, gray=True,
        )

    def _built_from(self, row: dict, start_image_of):
        video = self._item(row["trimmed_from"]) if row.get("trimmed_from") else None
        if video is not None:
            return video, "Trimmed from", MediaType.VIDEO
        frame = start_image_of(row)
        if frame is not None and was_made_from(row, frame):
            return frame, None, MediaType.IMAGE
        return None, None, None

    def _held_of_kind(self, kind: MediaType) -> list[dict]:
        return [held for held in self._held_rows() if media_type_of_row(held) == kind]

    def _item(self, prompt_id: str) -> dict | None:
        return self._row_of(prompt_id) or next(
            (held for held in self._held_rows() if held["prompt_id"] == prompt_id), None)

    def _animated_items(self, row: dict, start_image_of, videos: list[dict]) -> list[tuple]:
        image = row
        if media_type_of_row(row) != MediaType.IMAGE:
            image = start_image_of(row)
            if image is None or not was_taken_from(image, row):
                return []
        could_name_it = videos_from_source_image(image, videos)
        return [(video["prompt_id"], self._animated_preview(video), video.get("thumbnail_path"))
                for video in could_name_it
                if (self._built_from(video, start_image_of)[0] or {}).get("prompt_id")
                == image["prompt_id"]]
