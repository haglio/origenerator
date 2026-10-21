from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QStyle, QStyleOptionViewItem


def square(tmp_path, color):
    path = tmp_path / f"made-{color}.png"
    picture = QImage(40, 40, QImage.Format.Format_RGB32)
    picture.fill(QColor(color))
    picture.save(str(path))
    return str(path)


def painted_row(field, row, *, under_the_mouse=False):
    view, index = field.view(), field.model().index(row, 0)
    size = view.visualRect(index).size()
    canvas = QImage(size, QImage.Format.Format_ARGB32)
    canvas.fill(QColor("black"))
    option = QStyleOptionViewItem()
    option.initFrom(view)
    option.state &= ~QStyle.StateFlag.State_HasFocus  # the view gives it to its current row alone
    option.rect = QRect(QPoint(0, 0), size)
    option.widget = view
    option.displayAlignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    option.decorationAlignment = Qt.AlignmentFlag.AlignCenter
    if under_the_mouse:
        option.state |= QStyle.StateFlag.State_Selected
    painter = QPainter(canvas)
    field.itemDelegate().paint(painter, option, index)
    painter.end()
    return canvas
