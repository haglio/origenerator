from __future__ import annotations

from itertools import groupby

from PySide6.QtCore import QEvent, QRect
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget
from shared_ui.flow_layout import FlowLayout
from shared_ui.spacing import GAP_MEDIUM, GAP_SMALL

from origenerator.gui.thin_divider import THIN_DIVIDER_COLOR

_BETWEEN_PARTS = 2 * GAP_MEDIUM + 1
_BETWEEN_ROWS = 2 * GAP_SMALL + 1


class PartsInARow(QWidget):
    def __init__(self, *parts: QWidget):
        super().__init__()
        self._parts = parts
        row = FlowLayout(self, spacing=_BETWEEN_PARTS, row_spacing=_BETWEEN_ROWS)
        for part in parts:
            row.add_group([part])

    def line_rects(self) -> list[QRect]:
        shown = sorted((part for part in self._parts if not part.isHidden()),
                       key=lambda part: (part.y(), part.x()))
        rows = [list(row) for _top, row in groupby(shown, key=lambda part: part.y())]
        lines = []
        for index, row in enumerate(rows):
            top = row[0].y()
            height = max(part.height() for part in row)
            if index:
                lines.append(QRect(0, top - GAP_SMALL - 1, self.width(), 1))
            lines.extend(QRect(part.x() - GAP_MEDIUM - 1, top, 1, height) for part in row[1:])
        return lines

    def hasHeightForWidth(self) -> bool:  # noqa: N802 -- Qt's name
        return False

    def resizeEvent(self, event):  # noqa: N802 -- Qt's name
        super().resizeEvent(event)
        self._ask_for_the_rows_it_needs()

    def event(self, event):
        if event.type() == QEvent.Type.LayoutRequest:
            self._ask_for_the_rows_it_needs()
        return super().event(event)

    def _ask_for_the_rows_it_needs(self) -> None:
        self.setMinimumHeight(self.layout().heightForWidth(self.width()))

    def paintEvent(self, event):  # noqa: N802 -- Qt's name
        painter = QPainter(self)
        for line in self.line_rects():
            painter.fillRect(line, THIN_DIVIDER_COLOR)
        painter.end()
