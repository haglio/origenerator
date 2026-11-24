from __future__ import annotations

from functools import cache

from PySide6.QtGui import QColor, QIcon, QPixmap
from shared_ui import colors
from shared_ui.colors import TEXT_PRIMARY
from shared_ui.icons import icon_pixmap

from origenerator.gallery.collection import Glyph, collection
from origenerator.gallery.groups import MediaGroup, SettingsGroup, folder_level, rows_under
from origenerator.gallery.labels import item_type_labels
from origenerator.gallery.output import item_type_of
from origenerator.gallery.shapes import BOTH, LANDSCAPE, PORTRAIT
from origenerator.gui import icons
from origenerator.workflows.non_ai import folder_kind

LEVEL_LABELS = {
    "workflow": "Workflow", "site": "Site", "non_ai": "Non-AI", "model": "Model", "lora": "LoRA",
    "source_image": "Source image",
}
MARK_BESIDE_A_WORD = 15
_SIDE_MARKS = {PORTRAIT: PORTRAIT, LANDSCAPE: LANDSCAPE, BOTH: "portrait_and_landscape"}


def _color_of(glyph: Glyph) -> QColor | None:
    return getattr(colors, glyph.color) if glyph.color is not None else None


@cache
def collection_icon(which: str) -> QIcon:
    glyph = collection(which).glyph
    return icons.collection_glyph_icon(glyph.name, _color_of(glyph))


def collection_mark(which: str) -> tuple[str, QColor] | None:
    marked = collection(which)
    return (marked.glyph.name, _color_of(marked.glyph)) if marked.marked else None


def collection_kind_icon(which: str) -> tuple[QIcon, str]:
    return collection_icon(which), collection(which).label


@cache
def shape_mark(shape: str, size: int = MARK_BESIDE_A_WORD) -> QPixmap:
    return icon_pixmap(_SIDE_MARKS[shape], size, TEXT_PRIMARY)


@cache
def separate_mark(size: int) -> QPixmap:
    return icon_pixmap("portrait_beside_landscape", size, TEXT_PRIMARY)


def folder_kind_icon(group) -> tuple[QIcon, str] | None:
    level = folder_level(group)
    if level == "workflow":
        level = folder_kind(group.workflow_name)
    if level is not None:
        return icons.toc_initial_icon(level), LEVEL_LABELS[level]
    if isinstance(group, (MediaGroup, SettingsGroup)):
        item_type = item_type_of(rows_under(group)[0])
        return icons.item_type_mark(item_type), item_type_labels()[item_type]
    return None
