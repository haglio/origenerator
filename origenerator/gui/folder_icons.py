from __future__ import annotations

from functools import cache

from PySide6.QtGui import QColor, QIcon, QPixmap
from shared_ui.colors import TEXT_PRIMARY
from shared_ui.icons import icon_pixmap

from origenerator.gallery.collection import (
    COLLECTION_LABELS,
    ENHANCED_KEY,
    EXPERIMENTS_KEY,
    FAVORITES_KEY,
    LATEST_KEY,
    TRASH_KEY,
)
from origenerator.gallery.groups import MediaGroup, SettingsGroup, folder_level, rows_under
from origenerator.gallery.labels import MEDIA_LABELS
from origenerator.gallery.output import media_type_of_row
from origenerator.gallery.shapes import BOTH, LANDSCAPE, PORTRAIT
from origenerator.gui import icons
from origenerator.workflows.outside import outside_source

LEVEL_LABELS = {
    "workflow": "Workflow", "site": "Site", "model": "Model", "lora": "LoRA",
    "source_image": "Source Image",
}
_COLLECTION_MARKS = {
    FAVORITES_KEY: ("star", icons.STAR_GLYPH), ENHANCED_KEY: icons.ENHANCE_MARK,
    TRASH_KEY: icons.DELETE_MARK,
}
MARK_BESIDE_A_WORD = 15
_SIDE_MARKS = {PORTRAIT: PORTRAIT, LANDSCAPE: LANDSCAPE, BOTH: "portrait_and_landscape"}


@cache
def collection_icon(collection: str) -> QIcon:
    return {
        LATEST_KEY: icons.latest_icon, FAVORITES_KEY: lambda: icons.star_icon(filled=True),
        ENHANCED_KEY: icons.enhance_icon, EXPERIMENTS_KEY: icons.flask_icon,
        TRASH_KEY: icons.delete_icon,
    }[collection]()


def collection_mark(collection: str) -> tuple[str, QColor] | None:
    return _COLLECTION_MARKS.get(collection)


def collection_kind_icon(collection: str) -> tuple[QIcon, str]:
    return collection_icon(collection), COLLECTION_LABELS[collection]


@cache
def shape_mark(shape: str, size: int = MARK_BESIDE_A_WORD) -> QPixmap:
    return icon_pixmap(_SIDE_MARKS[shape], size, TEXT_PRIMARY)


@cache
def separate_mark(size: int) -> QPixmap:
    return icon_pixmap("portrait_beside_landscape", size, TEXT_PRIMARY)


def folder_kind_icon(group) -> tuple[QIcon, str] | None:
    level = folder_level(group)
    if level == "workflow" and outside_source(group.workflow_name) is not None:
        level = "site"
    if level is not None:
        return icons.toc_initial_icon(level), LEVEL_LABELS[level]
    if isinstance(group, (MediaGroup, SettingsGroup)):
        media = media_type_of_row(rows_under(group)[0])
        return icons.media_type_icon(media), MEDIA_LABELS[media]
    return None
