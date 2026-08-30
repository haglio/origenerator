"""A folder's pictures, all of them, tiled edge to edge.

What the preview shows when the tab is about a whole folder rather than one
generation: the folder itself. A rewrite lands on every picture in it, so the
pane above the prompt has to be every picture — showing the newest one alone
would say the edit was about that picture.

The wall fills the pane. The grid is whichever column count leaves the cells
squarest for the space there is (:func:`rows_for`), the last rows share out the
remainder so no row ends ragged (:func:`row_counts`), and each picture is scaled
to cover its cell and cropped to it. Nothing is letterboxed and nothing is
lettered: this is a picture of a folder, not a sheet to read filenames off.

Both grid functions are pure, so how the wall lays out is testable without a
screen.
"""

import math
from pathlib import Path

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtWidgets import QWidget


def rows_for(count: int, width: int, height: int) -> int:
    """How many rows ``count`` cells take filling a ``width``×``height`` rect.

    Chosen by trying every row count and keeping the one whose cells come out
    least oblong — which is what makes a wall of pictures read as a wall rather
    than as a row of slivers or a stack of bands. A rect with no area, or nothing
    to put in it, is ``0``.

    The rows are the whole answer: how many cells each one holds is
    :func:`row_counts`, which shares the remainder out row by row, and the widest
    row is what a candidate's cell width is measured at. Searching columns
    instead would score a cell shape no row ends up drawn at.
    """
    if count <= 0 or width <= 0 or height <= 0:
        return 0
    best = None
    for rows in range(1, count + 1):
        cell = (width / math.ceil(count / rows), height / rows)
        oblong = max(cell) / min(cell)
        if best is None or oblong < best[0]:
            best = (oblong, rows)
    return best[1]


def row_counts(count: int, rows: int) -> list[int]:
    """How many cells each row holds, sharing out the remainder from the top.

    Nine pictures over four rows is 3/2/2/2, not 3/3/3/0 — the wall fills, and no
    row ends in a gap where the grid simply ran out of pictures.
    """
    if rows <= 0 or count <= 0:
        return []
    base, extra = divmod(count, rows)
    return [base + 1] * extra + [base] * (rows - extra)


def _readable(path) -> QPixmap | None:
    """The picture at ``path``, or ``None`` when there is none to load — a file
    the library has since moved is an ordinary case here, not an error."""
    if not path or not Path(path).is_file():
        return None
    picture = QPixmap(str(path))
    return None if picture.isNull() else picture


def _cover(picture: QPixmap, cell: QRect) -> QPixmap:
    """``picture`` filling ``cell`` exactly: scaled up until it covers, then
    cropped about its middle."""
    scaled = picture.scaled(cell.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation)
    return scaled.copy(
        (scaled.width() - cell.width()) // 2, (scaled.height() - cell.height()) // 2,
        cell.width(), cell.height(),
    )


class ContactSheet(QWidget):
    """Every picture handed to it, tiled to fill the widget."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pictures: list[QPixmap] = []

    def show_pictures(self, paths) -> None:
        """Tile these files. Ones that can't be read are left out rather than
        drawn as holes — the wall says how big the folder is, and a missing file
        is not a picture in it."""
        self._pictures = [p for path in paths if (p := _readable(path)) is not None]
        self.update()

    def clear(self) -> None:
        self._pictures = []
        self.update()

    def count(self) -> int:
        """How many pictures are actually on the wall."""
        return len(self._pictures)

    def cells(self) -> list[QRect]:
        """Where each picture goes, in drawing order — the layout on its own, so
        it can be read without painting."""
        if not self._pictures:
            return []
        rows = rows_for(len(self._pictures), self.width(), self.height())
        laid = []
        for row, columns in enumerate(row_counts(len(self._pictures), rows)):
            top = round(row * self.height() / rows)
            bottom = round((row + 1) * self.height() / rows)
            for column in range(columns):
                left = round(column * self.width() / columns)
                right = round((column + 1) * self.width() / columns)
                laid.append(QRect(left, top, right - left, bottom - top))
        return laid

    def paintEvent(self, event):
        painter = QPainter(self)
        for picture, cell in zip(self._pictures, self.cells()):
            if cell.width() > 0 and cell.height() > 0:
                painter.drawPixmap(cell, _cover(picture, cell))
