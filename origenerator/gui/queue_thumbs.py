from __future__ import annotations

import os
from collections import OrderedDict

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import QLabel
from shared_ui.colors import BORDER_SUBTLE
from shared_ui.spacing import HAIRLINE

from origenerator.gui.combination import Combination, draw_plus, draw_source_video, plus_width
from origenerator.gui.grayscale import grayscale_pixmap
from origenerator.gui.thumbnail_box import centered_in_square, fitted_in

_GAP = HAIRLINE
FOLDER_CELLS = 4


def block_width(cell: int) -> int:
    return FOLDER_CELLS * cell + (FOLDER_CELLS - 1) * _GAP


_CELLS: OrderedDict[tuple[str, int, bool, int | None], QPixmap | None] = OrderedDict()
_MOST_CELLS = 1024


def _written(path) -> int | None:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


def fitted_cell(path, side: int, gray: bool = False) -> QPixmap | None:
    return _held(path, side, gray, squared=True)


def fitted_thumbnail(path, side: int, gray: bool = False) -> QPixmap | None:
    return _held(path, side, gray, squared=False)


def _held(path, side: int, gray: bool, *, squared: bool) -> QPixmap | None:
    if not path:
        return None
    key = (str(path), side, gray, squared, _written(path))
    if key in _CELLS:
        _CELLS.move_to_end(key)
    else:
        fitted = _fitted(QPixmap(str(path)), side, squared)
        _CELLS[key] = (grayscale_pixmap(fitted)
                       if gray and fitted is not None else fitted)
        if len(_CELLS) > _MOST_CELLS:
            _CELLS.popitem(last=False)
    return _CELLS[key]


def _fitted(pixmap: QPixmap, side: int, squared: bool) -> QPixmap | None:
    if pixmap.isNull():
        return None
    scaled = fitted_in(pixmap, QSize(side, side))
    return centered_in_square(scaled, side) if squared else scaled


def _empty_cell_color() -> QColor:
    color = QColor(BORDER_SUBTLE)
    color.setAlpha(110)
    return color


def _canvas(cell: int) -> QPixmap:
    canvas = QPixmap(block_width(cell), cell)
    canvas.fill(Qt.GlobalColor.transparent)
    return canvas


def source_pixmap(made_from: Combination, cell: int) -> QPixmap | None:
    frame = fitted_cell(made_from.image, cell)
    source_video = fitted_cell(made_from.source_video, cell, gray=True)
    if frame is None and source_video is None:
        return None
    canvas = _canvas(cell)
    painter = QPainter(canvas)
    if frame is not None:
        painter.drawPixmap(0, 0, frame)
    if source_video is not None:
        if frame is not None:
            draw_plus(painter, cell, cell)
        draw_source_video(painter, cell + plus_width(cell), source_video, made_from.prompt_edited)
    painter.end()
    return canvas


def folder_pixmap(paths, cell: int) -> QPixmap:
    canvas = _canvas(cell)
    painter = QPainter(canvas)
    for index in range(FOLDER_CELLS):
        x = index * (cell + _GAP)
        image = fitted_cell(paths[index], cell) if index < len(paths) else None
        if image is None:
            painter.fillRect(x, 0, cell, cell, _empty_cell_color())
        else:
            painter.drawPixmap(x, 0, image)
    painter.end()
    return canvas


class QueueThumbs(QLabel):
    def __init__(self, cell: int, parent=None):
        super().__init__(parent)
        self._cell = cell
        self._showing = None
        self.setFixedSize(block_width(cell), cell)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

    def show_source(self, made_from: Combination) -> bool:
        showing = ("source", made_from)
        if self._showing == showing:
            return True
        pixmap = source_pixmap(made_from, self._cell)
        if pixmap is None:
            return False
        self._showing = showing
        self.setPixmap(pixmap)
        self.show()
        return True

    def show_folder(self, paths):
        paths = [str(p) for p in list(paths)[:FOLDER_CELLS]]
        if self._showing == ("folder", tuple(paths)):
            return
        self._showing = ("folder", tuple(paths))
        self.setPixmap(folder_pixmap(paths, self._cell))
        self.show()

    def clear_block(self):
        if self._showing is None:
            return
        self._showing = None
        self.clear()
        self.hide()
