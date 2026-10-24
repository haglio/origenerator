from __future__ import annotations

from collections.abc import Callable
from functools import cache, lru_cache
from pathlib import Path

from PyQt6.QtCore import QMargins, QPoint, QPointF, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import (
    QColor,
    QImageReader,
    QMovie,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)
from shared_ui.colors import BORDER_DEFAULT, TEXT_MUTED
from shared_ui.icons import draw_glyph_filling
from shared_ui.spacing import GAP_SMALL

from origenerator.gui.grayscale import grayscale_pixmap
from origenerator.gui.looping_preview import looping_movie
from origenerator.gui.no_wheel import NoWheelComboBox
from origenerator.gui.queue_thumbs import fitted_picture
from origenerator.gui.thumbnail_box import THUMBNAIL_BOX

PICTURES_ROLE = Qt.ItemDataRole.UserRole
_ROW_INSET = QMargins(GAP_SMALL, GAP_SMALL, GAP_SMALL, GAP_SMALL)
_BRACE_GAP = GAP_SMALL
_BRACE_WIDTH = 10
_BRACE_COLUMN = 2 * _BRACE_GAP + _BRACE_WIDTH
_LIT = (QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver
        | QStyle.StateFlag.State_HasFocus)


@cache
def unmade_picture(side: int, size: tuple[int, int] | None) -> QPixmap:
    width, height = size or (1, 1)
    scale = side / max(width, height)
    shape = QRect(0, 0, max(1, round(width * scale)), max(1, round(height * scale)))
    picture = QPixmap(shape.size())
    picture.fill(Qt.GlobalColor.transparent)
    painter = QPainter(picture)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.fillRect(shape, QColor(BORDER_DEFAULT))
    inset = min(shape.width(), shape.height()) * 0.1
    draw_glyph_filling(painter, "question", QColor(TEXT_MUTED),
                       QRectF(shape).adjusted(inset, inset, -inset, -inset))
    painter.end()
    return picture


def _height_of(margins: QMargins) -> int:
    return QRect(0, 0, 0, 0).marginsAdded(margins).height()


_INSET_HEIGHT = _height_of(_ROW_INSET)


def picture_of(picture, side: int, gray: bool = False) -> QPixmap | None:
    return (fitted_picture(picture.thumbnail, side, gray) if picture.thumbnail
            else unmade_picture(side, picture.size))


def _shape_in_the_box(picture) -> QSize:
    return _shape_of(picture).scaled(THUMBNAIL_BOX, Qt.AspectRatioMode.KeepAspectRatio)


def _shape_of(picture) -> QSize:
    if picture.thumbnail:
        width, height = _shape_on_disk(str(picture.thumbnail))
        if width > 0 and height > 0:
            return QSize(width, height)
    width, height = picture.size or (1, 1)
    return QSize(width, height)


@lru_cache(maxsize=1024)
def _shape_on_disk(path: str) -> tuple[int, int]:
    size = QImageReader(path).size()
    return size.width(), size.height()


def _brace(span: QRectF) -> QPainterPath:
    left, middle, right = span.left(), span.center().x(), span.right()
    top, waist, lower = span.top(), span.center().y(), span.bottomLeft().y()
    curl = min(span.width() / 2, span.height() / 4)
    brace = QPainterPath(QPointF(left, top))
    brace.quadTo(middle, top, middle, top + curl)
    brace.lineTo(middle, waist - curl)
    brace.quadTo(middle, waist, right, waist)
    brace.quadTo(middle, waist, middle, waist + curl)
    brace.lineTo(middle, lower - curl)
    brace.quadTo(middle, lower, left, lower)
    return brace


def _lettering_color(option: QStyleOptionViewItem) -> QColor:
    state = option.state
    group = (QPalette.ColorGroup.Disabled if not state & QStyle.StateFlag.State_Enabled
             else QPalette.ColorGroup.Active if state & QStyle.StateFlag.State_Active
             else QPalette.ColorGroup.Inactive)
    role = (QPalette.ColorRole.HighlightedText if state & QStyle.StateFlag.State_Selected
            else QPalette.ColorRole.Text)
    return option.palette.color(group, role)


class _PicturedRows(QStyledItemDelegate):
    def __init__(self, parent, *, gray: bool,
                 frame_of: Callable[[object, int], QPixmap | None]):
        super().__init__(parent)
        self._gray = gray
        self._frame_of = frame_of

    def sizeHint(self, option, index):
        widest = super().sizeHint(option, index).grownBy(_ROW_INSET).width() + _BRACE_COLUMN
        return QSize(widest, sum(shape.height() + _INSET_HEIGHT for shape in _shapes(index)))

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.features |= QStyleOptionViewItem.ViewItemFeature.HasDecoration
        option.decorationSize = THUMBNAIL_BOX

    def paint(self, painter, option, index):
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, _ground_of(option), painter,
                          option.widget)
        filled = QStyleOptionViewItem(option)
        self.initStyleOption(filled, index)
        pictures = index.data(PICTURES_ROLE)
        places = _picture_places(option.rect, _shapes(index), worded=bool(index.data()))
        for picture, place in zip(pictures, places):
            drawn = (self._drawn(picture, index.row())
                     if place.intersects(painter.viewport()) else None)
            if drawn is not None:
                painter.drawPixmap(place.center() - drawn.rect().center(), drawn)
        span = QRectF(places[0].right() + _BRACE_GAP, places[0].top(), _BRACE_WIDTH,
                      places[-1].bottomLeft().y() - places[0].top())
        if len(pictures) > 1:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.strokePath(_brace(span), QPen(_lettering_color(option), 2))
            painter.restore()
        text = QStyleOptionViewItem(filled)
        text.features &= ~QStyleOptionViewItem.ViewItemFeature.HasDecoration
        text.state &= ~_LIT
        text.palette.setColor(QPalette.ColorRole.Text, _lettering_color(option))
        text.rect = option.rect.marginsRemoved(_ROW_INSET)
        text.rect.setLeft(round(span.right()) + _BRACE_GAP)
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, text, painter, option.widget)


    def _drawn(self, picture, row: int) -> QPixmap | None:
        frame = self._frame_of(picture, row)
        if frame is None:
            return picture_of(picture, THUMBNAIL_BOX.width(), self._gray)
        return grayscale_pixmap(frame) if self._gray else frame


def _ground_of(option: QStyleOptionViewItem) -> QStyleOptionViewItem:
    ground = QStyleOptionViewItem(option)
    ground.showDecorationSelected = True
    return ground


def _shapes(index) -> list[QSize]:
    pictures = index.data(PICTURES_ROLE)
    if index.data():
        return [THUMBNAIL_BOX] * len(pictures)
    return [_shape_in_the_box(picture) for picture in pictures]


def _picture_places(rect: QRect, shapes: list[QSize], *, worded: bool) -> list[QRect]:
    places = []
    top = rect.top()
    for shape in shapes:
        cell = QRect(rect.left(), top, rect.width(),
                     shape.height() + _INSET_HEIGHT).marginsRemoved(_ROW_INSET)
        if worded:
            cell.setWidth(THUMBNAIL_BOX.width())
        place = QRect(QPoint(0, 0), shape)
        place.moveCenter(cell.center())
        places.append(place)
        top += shape.height() + _INSET_HEIGHT
    return places


class PicturedDropdown(NoWheelComboBox):
    floor_chars = 1

    def __init__(self, parent=None, *, gray: bool = False,
                 looping_preview: Callable[[str], str | None] | None = None):
        super().__init__(parent)
        self._looping_preview = looping_preview or (lambda item: None)
        self._stills: set[str] = set()
        self.setItemDelegate(_PicturedRows(self, gray=gray, frame_of=self._frame_of))
        self.view().setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

    def showPopup(self):
        if self.count():
            self._hold_the_popup_to_its_usual_height()
        super().showPopup()

    def _hold_the_popup_to_its_usual_height(self) -> None:
        view = self.view()
        popup = view.parentWidget()
        chrome = sum(_height_of(margins) for margins in (
            popup.contentsMargins(), view.contentsMargins(), view.viewportMargins()))
        popup.setMaximumHeight(self.maxVisibleItems() * self._picture_row_height() + chrome)

    def _picture_row_height(self) -> int:
        return THUMBNAIL_BOX.height() + _INSET_HEIGHT

    def hidePopup(self):
        super().hidePopup()
        self._stop_playing()

    def _frame_of(self, picture, row: int) -> QPixmap | None:
        if not picture.item:
            return None
        movie = self.findChild(QMovie, picture.item) or self._play(picture.item, row)
        frame = movie.currentPixmap() if movie is not None else None
        return frame if frame is not None and not frame.isNull() else None

    def _play(self, item: str, row: int) -> QMovie | None:
        preview = None if item in self._stills else self._looping_preview(item)
        if not preview or not Path(preview).exists():
            self._stills.add(item)
            return None
        movie = looping_movie(preview, THUMBNAIL_BOX, self)
        movie.setObjectName(item)
        movie.frameChanged.connect(lambda _frame: self.view().update(self.model().index(row, 0)))
        return movie

    def _stop_playing(self) -> None:
        for movie in self.findChildren(QMovie):
            movie.stop()
            movie.setObjectName("")
            movie.deleteLater()

    def _row_option(self) -> QStyleOptionViewItem:
        view = self.view()
        option = QStyleOptionViewItem()
        option.initFrom(view)
        option.font = view.font()
        option.widget = view
        return option

    def _list_rows(self, rows) -> None:
        self._stop_playing()
        self._stills = set()
        self.clear()
        for text, pictures in rows:
            self.addItem(text)
            self.setItemData(self.count() - 1, pictures, PICTURES_ROLE)
        self.setCurrentIndex(-1)
        if self.count():
            self._widen_to_the_longest_row()

    def _widen_to_the_longest_row(self) -> None:
        longest = max(range(self.count()), key=lambda row: len(self.itemText(row)))
        view = self.view()
        row = self.itemDelegate().sizeHint(self._row_option(), self.model().index(longest, 0))
        view.setMinimumWidth(row.width() + view.verticalScrollBar().sizeHint().width()
                             + 2 * view.frameWidth())
