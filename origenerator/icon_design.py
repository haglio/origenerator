"""Generates the Origenerator app icon: a PINK "O" on the suite's grid.

Every app in the suite draws a single PINK letter on a 5x5 grid inset 31px
inside a 256px canvas, with each stroke exactly one grid unit -- 1/5 of the
glyph box -- thick and near-square corners.  This module renders Origenerator's
"O" as a 1/5-thick square ring to match.

Run ``python -m origenerator.icon_design`` to regenerate ``icon.ico``.  The
contract the output must satisfy lives in ``tests/test_icon.py``.
"""

from __future__ import annotations

from PIL import Image
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QImage, QPainter, QPainterPath

from origenerator.paths import ensure_shared_ui_on_path

# Before any shared_ui import: that checkout is a sibling on the path, not a
# dependency the launch interpreter has installed (see tests/test_sibling_imports).
ensure_shared_ui_on_path()

from shared_ui.colors import PINK

CANVAS = 256  # icon master size
INSET = 31  # glyph box offset within the canvas
BOX = CANVAS - 2 * INSET  # 194 -- glyph box size, shared across the suite
UNIT = BOX / 5  # 38.8 -- one grid unit == stroke width ("1/5-based")
CORNER_RADIUS = 5  # renders to a ~3px outer corner, matching the suite
ICON_SIZES = (16, 32, 48, 256)  # frames stored in the .ico


def render_icon(size: int = CANVAS) -> Image.Image:
    """Render the "O" ring at ``size``x``size`` as an RGBA Pillow image."""
    scale = size / CANVAS
    inset = INSET * scale
    box = BOX * scale
    unit = UNIT * scale
    radius = CORNER_RADIUS * scale
    hole = box - 2 * unit

    qimg = QImage(size, size, QImage.Format.Format_RGBA8888)
    qimg.fill(Qt.GlobalColor.transparent)

    painter = QPainter(qimg)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(PINK)

    outer = QPainterPath()
    outer.addRoundedRect(QRectF(inset, inset, box, box), radius, radius)
    inner = QPainterPath()
    inner.addRoundedRect(QRectF(inset + unit, inset + unit, hole, hole), radius, radius)
    painter.drawPath(outer.subtracted(inner))
    painter.end()

    return _to_pillow(qimg)


def _to_pillow(qimg: QImage) -> Image.Image:
    """Convert an RGBA8888 QImage to a Pillow image, dropping any row padding."""
    qimg = qimg.convertToFormat(QImage.Format.Format_RGBA8888)
    width, height, stride = qimg.width(), qimg.height(), qimg.bytesPerLine()
    buffer = qimg.constBits()
    buffer.setsize(height * stride)
    raw = bytes(buffer)
    tight = b"".join(raw[y * stride : y * stride + width * 4] for y in range(height))
    return Image.frombytes("RGBA", (width, height), tight)


def save_ico(path) -> None:
    """Write the multi-resolution ``.ico`` from the 256px master."""
    master = render_icon(CANVAS)
    master.save(path, format="ICO", sizes=[(s, s) for s in ICON_SIZES])


def main() -> int:
    from PyQt6.QtGui import QGuiApplication

    from origenerator.config import PROJECT_DIR

    QGuiApplication([])
    save_ico(PROJECT_DIR / "icon.ico")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
