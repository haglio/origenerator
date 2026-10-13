"""Long tooltips as a block of lines: Qt wraps a plain tooltip only once it would
run wider than the whole screen."""
from __future__ import annotations

import html
import textwrap

from PyQt6.QtCore import QEvent, QObject, QRect, Qt
from PyQt6.QtWidgets import QAbstractItemView, QToolTip, QWidget

LONGEST_LINE = 80


def shaped(text: str) -> str:
    if len(text) <= LONGEST_LINE or Qt.mightBeRichText(text):
        return text
    lines = "\n".join(textwrap.fill(part, LONGEST_LINE) for part in text.split("\n"))
    return '<p style="white-space:pre">' + html.escape(lines, quote=False) + "</p>"


class ShapeLongTooltips(QObject):
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.ToolTip or not isinstance(watched, QWidget):
            return False
        text, area = _tooltip_under(watched, event.pos())
        block = shaped(text)
        if block == text:
            return False
        QToolTip.showText(event.globalPos(), block, watched, area)
        return True


def shape_long_tooltips(app) -> None:
    if app.findChild(ShapeLongTooltips) is None:
        app.installEventFilter(ShapeLongTooltips(app))


def _tooltip_under(widget: QWidget, pos) -> tuple[str, QRect]:
    view = widget.parent()
    if isinstance(view, QAbstractItemView) and view.viewport() is widget:
        index = view.indexAt(pos)
        if not index.isValid():
            return "", QRect()
        return str(index.data(Qt.ItemDataRole.ToolTipRole) or ""), view.visualRect(index)
    return widget.toolTip(), QRect()
