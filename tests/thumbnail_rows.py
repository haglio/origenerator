from __future__ import annotations

from PIL import Image
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QStyle, QStyleOptionViewItem


def square(tmp_path, color):
    path = tmp_path / f"made-{color}.png"
    thumbnail = QImage(40, 40, QImage.Format.Format_RGB32)
    thumbnail.fill(QColor(color))
    thumbnail.save(str(path))
    return str(path)


def looping_video(tmp_path) -> str:
    path = tmp_path / "clip.webp"
    frames = [Image.new("RGB", (160, 90), color) for color in ((255, 0, 0), (0, 255, 0))]
    frames[0].save(path, format="WEBP", save_all=True, append_images=frames[1:],
                   duration=100, loop=0)
    return str(path)


def where_the_thumbnail_is(row: QImage) -> QRect:
    inked = [(x, y) for y in range(row.height()) for x in range(row.width())
             if QColor(row.pixel(x, y)).lightness() > 40]
    xs, ys = [x for x, _ in inked], [y for _, y in inked]
    return QRect(QPoint(min(xs), min(ys)), QPoint(max(xs), max(ys)))


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
