from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import (
    QFont,
    QImage,
    QImageReader,
    QPainter,
    QTextCursor,
    QTextDocument,
    QTextImageFormat,
    QTextLength,
    QTextTableFormat,
)
from shared_ui.colors import TEXT_MUTED, TEXT_PRIMARY
from shared_ui.spacing import GAP_SMALL

from origenerator import config
from origenerator.gui.diff_text import write_request_change
from origenerator.gui.thumbnail_box import THUMBNAIL_BOX

_COMPARED = THUMBNAIL_BOX * 2
_NOT_MADE = "?"
_MARK_SHARE = 0.7
_NOT_MADE_FILL = TEXT_MUTED
_NOT_MADE_INK = TEXT_PRIMARY


def change_tip(before: str | None, after: str | None, change: tuple[str, str, str, str],
               settings=(), *, with_thumbnails: bool = True) -> str:
    document = QTextDocument()
    cursor = QTextCursor(document)
    if with_thumbnails:
        _write_comparison(cursor, before, after)
    write_request_change(cursor, *change, settings=settings)
    return document.toHtml()


def fitted(thumbnail: str | None, box: QSize) -> QTextImageFormat | None:
    size = QImageReader(thumbnail).size() if thumbnail else QSize()
    if not size.isValid():
        return None
    scaled = size.scaled(box, Qt.AspectRatioMode.KeepAspectRatio)
    image_format = QTextImageFormat()
    image_format.setName(thumbnail)
    image_format.setWidth(scaled.width())
    image_format.setHeight(scaled.height())
    return image_format


def _write_comparison(cursor: QTextCursor, *thumbnails: str | None) -> None:
    shape = QTextTableFormat()
    shape.setBorder(0)
    shape.setCellSpacing(GAP_SMALL)
    shape.setColumnWidthConstraints([QTextLength(QTextLength.Type.FixedLength, _COMPARED.width())]
                                    * len(thumbnails))
    table = cursor.insertTable(1, len(thumbnails), shape)
    image_formats = [fitted(thumbnail, _COMPARED) for thumbnail in thumbnails]
    made = next((image_format for image_format in image_formats if image_format is not None), None)
    size = (QSize(round(made.width()), round(made.height())) if made is not None
            else _COMPARED)
    for column, image_format in enumerate(image_formats):
        cell = table.cellAt(0, column).firstCursorPosition()
        cell.insertImage(image_format if image_format is not None else _not_made(size))
    cursor.movePosition(QTextCursor.MoveOperation.End)


def _not_made(size: QSize) -> QTextImageFormat:
    drawn = f"{size.width()}x{size.height()} {_NOT_MADE_FILL.name()[1:]} {_NOT_MADE_INK.name()[1:]}"
    path = config.STATE_DIR / "not made" / f"not made {drawn}.png"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        stand_in = QImage(size, QImage.Format.Format_RGB32)
        stand_in.fill(_NOT_MADE_FILL)
        painter = QPainter(stand_in)
        font = QFont()
        font.setPixelSize(round(min(size.width(), size.height()) * _MARK_SHARE))
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(_NOT_MADE_INK)
        painter.drawText(stand_in.rect(), Qt.AlignmentFlag.AlignCenter, _NOT_MADE)
        painter.end()
        stand_in.save(str(path))
    image_format = QTextImageFormat()
    image_format.setName(str(path))
    image_format.setWidth(size.width())
    image_format.setHeight(size.height())
    return image_format
