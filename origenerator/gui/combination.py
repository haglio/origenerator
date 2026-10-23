from __future__ import annotations

from typing import NamedTuple

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QFont, QPainter, QPixmap
from shared_ui.colors import TEXT_MUTED
from shared_ui.icons import draw_glyph

# The plus, as a fraction of a picture's side — big enough to read as the operator
# joining them rather than as a mark on one of the pictures.
_PLUS_SHARE = 0.28
_MIN_PLUS_PT = 12
_PAREN_SHARE = 0.25
_PAREN_HEIGHT_SHARE = 0.8


class Combination(NamedTuple):
    picture: str | None = None
    recipe: str | None = None
    recipe_prompt_edited: bool = False


def pair_side(size: QSize, both: bool, enclosed: bool) -> int:
    across = (2 + _PLUS_SHARE if both else 1) + (2 * _PAREN_SHARE if enclosed else 0)
    return max(1, int(min(size.width() / across, size.height())))


def plus_width(side: int) -> int:
    return max(_MIN_PLUS_PT, int(side * _PLUS_SHARE))


def paren_width(side: int) -> int:
    return max(1, int(side * _PAREN_SHARE))


def paren_font(font: QFont, side: int) -> QFont:
    enclosing = QFont(font)
    enclosing.setPixelSize(max(1, int(side * _PAREN_HEIGHT_SHARE)))
    enclosing.setWeight(QFont.Weight.Light)
    return enclosing


def draw_plus(painter: QPainter, x: int, side: int) -> None:
    width = plus_width(side)
    draw_glyph(painter, "plus", TEXT_MUTED, size=width, x=x, y=(side - width) / 2)


def draw_recipe(painter: QPainter, x: int, recipe: QPixmap, prompt_edited: bool) -> None:
    side = recipe.height()
    if prompt_edited:
        paren = paren_width(side)
        _draw_paren(painter, QRect(x, 0, paren, side), "(")
        _draw_paren(painter, QRect(x + paren + recipe.width(), 0, paren, side), ")")
        x += paren
    painter.drawPixmap(x, 0, recipe)


def _draw_paren(painter: QPainter, band: QRect, glyph: str) -> None:
    painter.setFont(paren_font(painter.font(), band.height()))
    painter.setPen(TEXT_MUTED)
    painter.drawText(band, Qt.AlignmentFlag.AlignCenter, glyph)
