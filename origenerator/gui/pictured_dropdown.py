from __future__ import annotations

from functools import cache

from PyQt6.QtCore import QMargins, QModelIndex, QPointF, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QTransform,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)
from shared_ui.colors import BORDER_DEFAULT, TEXT_MUTED

from origenerator.gui.no_wheel import NoWheelComboBox
from origenerator.gui.queue_thumbs import fitted_cell

PICTURES_ROLE = Qt.ItemDataRole.UserRole
_PICTURE_SIDE = 48
_ROW_INSET = QMargins(3, 3, 3, 3)
_BRACE_GAP = 4
_BRACE_WIDTH = 10
_BRACE_COLUMN = 2 * _BRACE_GAP + _BRACE_WIDTH


@cache
def unmade_cell(side: int, size: tuple[int, int] | None) -> QPixmap:
    width, height = size or (1, 1)
    scale = side / max(width, height)
    shape = QRect(0, 0, max(1, round(width * scale)), max(1, round(height * scale)))
    shape.moveCenter(QRect(0, 0, side, side).center())
    cell = QPixmap(side, side)
    cell.fill(Qt.GlobalColor.transparent)
    painter = QPainter(cell)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.fillRect(shape, QColor(BORDER_DEFAULT))
    painter.fillPath(_question_mark_filling(QRectF(shape)), QColor(TEXT_MUTED))
    painter.end()
    return cell


def _question_mark_filling(blank: QRectF) -> QPainterPath:
    font = QFont()
    font.setBold(True)
    font.setPixelSize(100)
    mark = QPainterPath()
    mark.addText(0, 0, font, "?")
    ink = mark.boundingRect()
    inset = min(blank.width(), blank.height()) * 0.1
    room = blank.adjusted(inset, inset, -inset, -inset)
    scale = min(room.width() / ink.width(), room.height() / ink.height())
    fitted = QTransform()
    fitted.translate(blank.center().x(), blank.center().y())
    fitted.scale(scale, scale)
    fitted.translate(-ink.center().x(), -ink.center().y())
    return fitted.map(mark)


def _height_of(margins: QMargins) -> int:
    return QRect(0, 0, 0, 0).marginsAdded(margins).height()


def picture_of(picture, side: int, gray: bool = False) -> QPixmap | None:
    return (fitted_cell(picture.thumbnail, side, gray) if picture.thumbnail
            else unmade_cell(side, picture.size))


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
    def __init__(self, parent, *, gray: bool):
        super().__init__(parent)
        self._gray = gray

    def sizeHint(self, option, index):
        widest = super().sizeHint(option, index).grownBy(_ROW_INSET).width() + _BRACE_COLUMN
        return QSize(widest, self.pitch(option) * len(index.data(PICTURES_ROLE)))

    def pitch(self, option) -> int:
        return super().sizeHint(option, QModelIndex()).grownBy(_ROW_INSET).height()

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.features |= QStyleOptionViewItem.ViewItemFeature.HasDecoration
        option.decorationSize = QSize(_PICTURE_SIDE, _PICTURE_SIDE)

    def paint(self, painter, option, index):
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter,
                            option.widget)
        filled = QStyleOptionViewItem(option)
        self.initStyleOption(filled, index)
        pictures = index.data(PICTURES_ROLE)
        places = _picture_places(style, filled, len(pictures))
        for picture, place in zip(pictures, places):
            drawn = picture_of(picture, _PICTURE_SIDE, self._gray) if place.intersects(
                painter.viewport()) else None
            if drawn is not None:
                painter.drawPixmap(place.topLeft(), drawn)
        span = QRectF(places[0].right() + _BRACE_GAP, places[0].top(), _BRACE_WIDTH,
                      places[-1].bottomLeft().y() - places[0].top())
        if len(pictures) > 1:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.strokePath(_brace(span), QPen(_lettering_color(option), 2))
            painter.restore()
        text = QStyleOptionViewItem(filled)
        text.features &= ~QStyleOptionViewItem.ViewItemFeature.HasDecoration
        text.rect = option.rect.marginsRemoved(_ROW_INSET)
        text.rect.setLeft(round(span.right()) + _BRACE_GAP)
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, text, painter, option.widget)


def _picture_places(style, option: QStyleOptionViewItem, count: int) -> list[QRect]:
    pitch = option.rect.height() // count
    places = []
    for row in range(count):
        cell = QStyleOptionViewItem(option)
        cell.rect = QRect(option.rect.left(), option.rect.top() + row * pitch,
                          option.rect.width(), pitch).marginsRemoved(_ROW_INSET)
        places.append(style.subElementRect(QStyle.SubElement.SE_ItemViewItemDecoration, cell,
                                           option.widget))
    return places


class PicturedDropdown(NoWheelComboBox):
    floor_chars = 1

    def __init__(self, parent=None, *, gray: bool = False):
        super().__init__(parent)
        self.setItemDelegate(_PicturedRows(self, gray=gray))
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
        popup.setMaximumHeight(self.maxVisibleItems() * self._pitch() + chrome)

    def _pitch(self) -> int:
        return self.itemDelegate().pitch(self._row_option())

    def _row_option(self) -> QStyleOptionViewItem:
        view = self.view()
        option = QStyleOptionViewItem()
        option.initFrom(view)
        option.font = view.font()
        option.widget = view
        return option

    def _list_rows(self, rows) -> None:
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
