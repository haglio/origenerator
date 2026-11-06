from __future__ import annotations

from functools import cache

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from shared_ui import palette
from shared_ui.colors import (
    BG_PRIMARY,
    BLUE,
    GREEN,
    MAGENTA,
    RED,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WHITE,
    YELLOW,
)
from shared_ui.icons import CANVAS, draw_icon, icon_pixmap, qt_icon
from shared_ui.spacing import BUTTON_ICON
from shared_ui.type_scale import FONT_UI, SIZE_TINY, in_pixels

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
from origenerator.media import MediaType

_SIZE = int(CANVAS)

LEVEL_LABELS = {
    "workflow": "Workflow", "model": "Model", "lora": "LoRA",
    "source_image": "Source Image",
}
_TOC_INITIALS = {
    "workflow": ("W", BLUE), "model": ("M", MAGENTA), "lora": ("L", YELLOW),
    "source_image": ("I", GREEN),
}

_ITEM_TYPE_ICON_GROUND = QColor(*palette.BLACK, 160)
_ITEM_TYPE_ICON_INK = WHITE
_ITEM_TYPE_ICON_SIZE = 22
_TOC_INITIAL_LETTER = round(in_pixels(SIZE_TINY) * _SIZE / BUTTON_ICON)

_GLYPH_ON_GROUND = 44
_GROUND_INSET = (_SIZE - _GLYPH_ON_GROUND) / 2

_STAR_GLYPH = GREEN
_REROLL_GLYPH = WHITE

_REROLL_MEDIA = 34
_REROLL_MEDIA_AT = 1


def back_icon() -> QIcon:
    return qt_icon("chevron_left", size=_SIZE)


def forward_icon() -> QIcon:
    return qt_icon("chevron_right", size=_SIZE)


def undo_icon() -> QIcon:
    return qt_icon("undo_arrow", size=_SIZE)


def redo_icon() -> QIcon:
    return qt_icon("redo_arrow", size=_SIZE)


def auto_generate_icon() -> QIcon:
    return qt_icon("bolt", size=_SIZE)


def shield_icon() -> QIcon:
    return qt_icon("shield", size=_SIZE)


def move_up_icon() -> QIcon:
    return qt_icon("chevron_up", size=_SIZE)


def move_down_icon() -> QIcon:
    return qt_icon("chevron_down", size=_SIZE)


def slideshow_icon() -> QIcon:
    return qt_icon("slideshow", size=_SIZE)


def enhance_icon() -> QIcon:
    return qt_icon("plus", color=YELLOW, size=_SIZE)


def play_icon() -> QIcon:
    return qt_icon("play", size=_SIZE)


def pause_icon() -> QIcon:
    return qt_icon("pause", size=_SIZE)


def mic_icon() -> QIcon:
    return qt_icon("mic", size=_SIZE)


def radio_icon(*, lit_ink=None) -> QIcon:
    icon = qt_icon("speaker", size=_SIZE)
    if lit_ink is not None:
        icon.addPixmap(icon_pixmap("speaker", _SIZE, lit_ink), QIcon.Mode.Normal, QIcon.State.On)
    return icon


def trash_icon(*, color=None) -> QIcon:
    return qt_icon("trash", color=color, size=_SIZE)


def delete_icon() -> QIcon:
    return trash_icon(color=RED)


def star_icon(*, filled: bool) -> QIcon:
    if filled:
        icon = qt_icon("star", color=_STAR_GLYPH, size=_SIZE)
        icon.addPixmap(_painted(_ringed_star), QIcon.Mode.Selected)
        return icon
    return qt_icon("star_outline", size=_SIZE)


def _ringed_star(painter: QPainter):
    draw_icon(painter, "star_ring", TEXT_PRIMARY, size=_SIZE)
    draw_icon(painter, "star", _STAR_GLYPH, size=_SIZE)


@cache
def thumbs_up_icon() -> QIcon:
    return qt_icon("thumbs_up", size=_SIZE)


@cache
def unmarked_icon() -> QIcon:
    canvas = QPixmap(_SIZE, _SIZE)
    canvas.fill(Qt.GlobalColor.transparent)
    return QIcon(canvas)


def latest_icon() -> QIcon:
    return qt_icon("latest", size=_SIZE)


def flask_icon() -> QIcon:
    return qt_icon("flask", size=_SIZE)


@cache
def collection_icon(collection: str) -> QIcon:
    return {
        LATEST_KEY: latest_icon, FAVORITES_KEY: lambda: star_icon(filled=True),
        ENHANCED_KEY: enhance_icon, EXPERIMENTS_KEY: flask_icon, TRASH_KEY: trash_icon,
    }[collection]()


def collection_kind_icon(collection: str) -> tuple[QIcon, str]:
    return collection_icon(collection), COLLECTION_LABELS[collection]


def all_icon() -> QIcon:
    return qt_icon("database", size=_SIZE)


def custom_collection_icon() -> QIcon:
    return qt_icon("folder", size=_SIZE)



@cache
def recent_mark_icon() -> QIcon:
    icon = QIcon(_painted(_disc(BLUE)))
    icon.addPixmap(_painted(_disc(TEXT_PRIMARY)), QIcon.Mode.Selected)
    return icon


def _disc(color):
    def draw(painter: QPainter):
        draw_icon(painter, "disc", color, size=_SIZE)

    return draw


@cache
def experiment_verdict_icon(verdict: str) -> QIcon:
    return QIcon(icon_pixmap("check" if verdict == "up" else "cross",
                             _SIZE, _REROLL_GLYPH))


@cache
def item_type_icon(media_type: str) -> QPixmap:
    icon = "play" if media_type == MediaType.VIDEO else "photo"
    return _display_size(_render_on_ground(_ITEM_TYPE_ICON_GROUND, icon, _ITEM_TYPE_ICON_INK))


@cache
def media_type_icon(media_type: str) -> QIcon:
    return qt_icon("play" if media_type == MediaType.VIDEO else "photo", size=_SIZE)


MARK_BESIDE_A_WORD = 15
_SIDE_MARKS = {PORTRAIT: PORTRAIT, LANDSCAPE: LANDSCAPE, BOTH: "portrait_and_landscape"}


@cache
def shape_mark(shape: str, size: int = MARK_BESIDE_A_WORD) -> QPixmap:
    return icon_pixmap(_SIDE_MARKS[shape], size, TEXT_PRIMARY)


@cache
def separate_mark(size: int) -> QPixmap:
    return icon_pixmap("portrait_beside_landscape", size, TEXT_PRIMARY)


ENHANCE_OPEN = "open"
ENHANCE_HELD = "held"
ENHANCE_MORE = "more"

_CORNER_REST = TEXT_MUTED
_CORNER_ARMED = TEXT_SECONDARY
_RESTORE_UNAVAILABLE_OPACITY = 0.4
_CORNER_MARK = 40.0
_CORNER_MARK_AT = 4.0
_ENHANCE_SHADOW = 5.0


@cache
def corner_star_icon(*, favorite: bool, armed: bool) -> QIcon:
    return _corner_icon("star" if favorite else "star_outline",
                        _STAR_GLYPH if favorite else _CORNER_REST, armed)


@cache
def corner_trash_icon(*, armed: bool) -> QIcon:
    return _corner_icon("trash", _CORNER_REST, armed, arm_color=RED)


def corner_restore_icon(*, can_restore: bool, armed: bool) -> QIcon:
    if can_restore:
        return _corner_icon("undo_arrow", _CORNER_REST, armed)

    mark = _painted(lambda painter: _mark(painter, "undo_arrow", _CORNER_REST))

    def draw(painter: QPainter):
        painter.setOpacity(_RESTORE_UNAVAILABLE_OPACITY)
        painter.drawPixmap(0, 0, mark)

    return _same_when_dead(_painted(draw))


@cache
def corner_enhance_icon(state: str, *, armed: bool) -> QIcon:
    if state == ENHANCE_HELD:
        return _corner_icon("plus", YELLOW, armed=False)
    ink = _CORNER_ARMED if armed else _CORNER_REST
    shifted = _CORNER_MARK_AT + _ENHANCE_SHADOW

    def draw(painter: QPainter):
        if state == ENHANCE_MORE:
            draw_icon(painter, "plus", YELLOW, size=_CORNER_MARK, x=shifted, y=shifted)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            _mark(painter, "plus", YELLOW)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        _mark(painter, "plus_outline", ink)

    return _same_when_dead(_painted(draw))


def _corner_icon(icon: str, ink, armed: bool, *, arm_color=None) -> QIcon:
    color = (arm_color or _CORNER_ARMED) if armed else ink
    return _same_when_dead(_painted(lambda painter: _mark(painter, icon, color)))


def _mark(painter: QPainter, icon: str, ink):
    draw_icon(painter, icon, ink, size=_CORNER_MARK,
              x=_CORNER_MARK_AT, y=_CORNER_MARK_AT)


def _painted(draw, size: int = _SIZE) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    draw(painter)
    painter.end()
    return pixmap


def _same_when_dead(pixmap: QPixmap) -> QIcon:
    """``pixmap`` as an icon that keeps its own look when the button is disabled (Qt fades it by default)."""
    icon = QIcon()
    icon.addPixmap(pixmap, QIcon.Mode.Normal)
    icon.addPixmap(pixmap, QIcon.Mode.Disabled)
    return icon


def _display_size(pixmap: QPixmap, size: int = _ITEM_TYPE_ICON_SIZE) -> QPixmap:
    return pixmap.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
    )


@cache
def reroll_seed_icon(media_type: str) -> QIcon:
    pixmap = QPixmap(_SIZE, _SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    draw_icon(painter, "play" if media_type == MediaType.VIDEO else "photo", _REROLL_GLYPH,
              size=_REROLL_MEDIA, x=_REROLL_MEDIA_AT, y=_REROLL_MEDIA_AT)
    draw_icon(painter, "regenerate_corner", _REROLL_GLYPH, size=_SIZE)
    painter.end()
    return QIcon(pixmap)


def tab_close_icon() -> QIcon:
    return qt_icon("cross", size=_SIZE)


def folder_kind_icon(group) -> tuple[QIcon, str] | None:
    level = folder_level(group)
    if level is not None:
        return toc_initial_icon(level), LEVEL_LABELS[level]
    if isinstance(group, (MediaGroup, SettingsGroup)):
        media = media_type_of_row(rows_under(group)[0])
        return media_type_icon(media), MEDIA_LABELS[media]
    return None


@cache
def toc_initial_icon(level: str) -> QIcon:
    icon = QIcon()
    letter, color = _TOC_INITIALS[level]
    icon.addPixmap(_render_toc_initial(letter, color))
    return icon


def _render_on_ground(ground, icon: str, ink) -> QPixmap:
    return _ground_pixmap(ground, lambda painter: draw_icon(
        painter, icon, ink, size=_GLYPH_ON_GROUND, x=_GROUND_INSET, y=_GROUND_INSET))


def _ground_pixmap(color, draw) -> QPixmap:
    pixmap = QPixmap(_SIZE, _SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawRoundedRect(QRectF(3, 3, _SIZE - 6, _SIZE - 6), 12, 12)
    draw(painter)
    painter.end()
    return pixmap


def _render_toc_initial(letter: str, color) -> QPixmap:
    def draw(painter: QPainter):
        font = QFont(FONT_UI)
        font.setBold(True)
        font.setPixelSize(_TOC_INITIAL_LETTER)
        painter.setFont(font)
        painter.setPen(_readable_on(color))
        painter.drawText(QRectF(0, 0, _SIZE, _SIZE),
                         Qt.AlignmentFlag.AlignCenter, letter)

    return _ground_pixmap(color, draw)


_READS_AS_LIGHT = 150


def _readable_on(color):
    luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    return BG_PRIMARY if luminance > _READS_AS_LIGHT else TEXT_PRIMARY
