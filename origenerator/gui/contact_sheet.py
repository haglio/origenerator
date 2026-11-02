from __future__ import annotations

import math
from pathlib import Path

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtWidgets import QWidget


def rows_for(count: int, width: int, height: int) -> int:
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
    if rows <= 0 or count <= 0:
        return []
    base, extra = divmod(count, rows)
    return [base + 1] * extra + [base] * (rows - extra)


def _readable(path) -> QPixmap | None:
    if not path or not Path(path).is_file():
        return None
    thumbnail = QPixmap(str(path))
    return None if thumbnail.isNull() else thumbnail


def _cover(thumbnail: QPixmap, cell: QRect) -> QPixmap:
    scaled = thumbnail.scaled(cell.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                              Qt.TransformationMode.SmoothTransformation)
    return scaled.copy(
        (scaled.width() - cell.width()) // 2, (scaled.height() - cell.height()) // 2,
        cell.width(), cell.height(),
    )


class ContactSheet(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._thumbnails: list[QPixmap] = []

    def show_thumbnails(self, paths) -> None:
        self._thumbnails = [p for path in paths if (p := _readable(path)) is not None]
        self.update()

    def clear(self) -> None:
        self._thumbnails = []
        self.update()

    def count(self) -> int:
        return len(self._thumbnails)

    def cells(self) -> list[QRect]:
        if not self._thumbnails:
            return []
        rows = rows_for(len(self._thumbnails), self.width(), self.height())
        laid = []
        for row, columns in enumerate(row_counts(len(self._thumbnails), rows)):
            top = round(row * self.height() / rows)
            lower = round((row + 1) * self.height() / rows)
            for column in range(columns):
                left = round(column * self.width() / columns)
                right = round((column + 1) * self.width() / columns)
                laid.append(QRect(left, top, right - left, lower - top))
        return laid

    def paintEvent(self, event):
        painter = QPainter(self)
        for thumbnail, cell in zip(self._thumbnails, self.cells(), strict=True):
            if cell.width() > 0 and cell.height() > 0:
                painter.drawPixmap(cell, _cover(thumbnail, cell))
