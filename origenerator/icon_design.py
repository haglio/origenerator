from __future__ import annotations

from PIL import Image
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QGuiApplication, QImage, QPainter, QPainterPath
from shared_ui.app_icon import CANVAS, GRID, INSET, UNIT
from shared_ui.colors import MAGENTA

from origenerator.config import PROJECT_DIR

CORNER_RADIUS = 5
ICON_SIZES = (16, 32, 48, 256)


def render_icon(size: int = CANVAS) -> Image.Image:
    scale = size / CANVAS
    inset = INSET * scale
    grid = GRID * scale
    unit = UNIT * scale
    radius = CORNER_RADIUS * scale
    cutout = grid - 2 * unit

    qimg = QImage(size, size, QImage.Format.Format_RGBA8888)
    qimg.fill(Qt.GlobalColor.transparent)

    painter = QPainter(qimg)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(MAGENTA)

    outer = QPainterPath()
    outer.addRoundedRect(QRectF(inset, inset, grid, grid), radius, radius)
    inner = QPainterPath()
    inner.addRoundedRect(QRectF(inset + unit, inset + unit, cutout, cutout), radius, radius)
    painter.drawPath(outer.subtracted(inner))
    painter.end()

    return _to_pillow(qimg)


def _to_pillow(qimg: QImage) -> Image.Image:
    qimg = qimg.convertToFormat(QImage.Format.Format_RGBA8888)
    width, height, stride = qimg.width(), qimg.height(), qimg.bytesPerLine()
    buffer = qimg.constBits()
    buffer.setsize(height * stride)
    raw = bytes(buffer)
    tight = b"".join(raw[y * stride : y * stride + width * 4] for y in range(height))
    return Image.frombytes("RGBA", (width, height), tight)


def save_ico(path) -> None:
    master = render_icon(CANVAS)
    master.save(path, format="ICO", sizes=[(s, s) for s in ICON_SIZES])


def main() -> int:
    QGuiApplication([])
    save_ico(PROJECT_DIR / "icon.ico")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
