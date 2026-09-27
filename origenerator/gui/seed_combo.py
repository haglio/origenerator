from __future__ import annotations

from collections.abc import Callable
from functools import cache
from itertools import groupby
from operator import attrgetter

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
    QLabel,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)
from shared_ui.colors import BORDER_DEFAULT, TEXT_MUTED

from origenerator.gui.no_wheel import NoWheelComboBox
from origenerator.gui.queue_thumbs import fitted_cell
from origenerator.seed_history import SeedUse

_THUMBNAIL_SIDE = 48
_USES_ROLE = Qt.ItemDataRole.UserRole
_ROW_INSET = QMargins(3, 3, 3, 3)
_BRACE_GAP = 4
_BRACE_WIDTH = 10
_BRACE_COLUMN = 2 * _BRACE_GAP + _BRACE_WIDTH
_TALLEST_ROW_A_LIST_LAYS_OUT = 32767


@cache
def _unmade_cell(side: int, size: tuple[int, int] | None) -> QPixmap:
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


def _picture_of(use: SeedUse, side: int) -> QPixmap | None:
    return fitted_cell(use.thumbnail, side) if use.thumbnail else _unmade_cell(side, use.size)


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


class _WithThumbnails(QStyledItemDelegate):
    def sizeHint(self, option, index):
        widest = super().sizeHint(option, index).grownBy(_ROW_INSET).width() + _BRACE_COLUMN
        return QSize(widest, self.pitch(option) * len(index.data(_USES_ROLE)))

    def pitch(self, option) -> int:
        return super().sizeHint(option, QModelIndex()).grownBy(_ROW_INSET).height()

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.features |= QStyleOptionViewItem.ViewItemFeature.HasDecoration
        option.decorationSize = QSize(_THUMBNAIL_SIDE, _THUMBNAIL_SIDE)

    def paint(self, painter, option, index):
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter,
                            option.widget)
        filled = QStyleOptionViewItem(option)
        self.initStyleOption(filled, index)
        uses = index.data(_USES_ROLE)
        places = _picture_places(style, filled, len(uses))
        for use, place in zip(uses, places):
            picture = _picture_of(use, _THUMBNAIL_SIDE) if place.intersects(
                painter.viewport()) else None
            if picture is not None:
                painter.drawPixmap(place.topLeft(), picture)
        span = QRectF(places[0].right() + _BRACE_GAP, places[0].top(), _BRACE_WIDTH,
                      places[-1].bottomLeft().y() - places[0].top())
        if len(uses) > 1:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.strokePath(_brace(span), QPen(_lettering_color(option), 2))
            painter.restore()
        seed = QStyleOptionViewItem(filled)
        seed.features &= ~QStyleOptionViewItem.ViewItemFeature.HasDecoration
        seed.rect = option.rect.marginsRemoved(_ROW_INSET)
        seed.rect.setLeft(round(span.right()) + _BRACE_GAP)
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, seed, painter, option.widget)


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


class SeedComboBox(NoWheelComboBox):
    floor_chars = 1

    def __init__(self, history: Callable[[], list[SeedUse]], parent=None):
        super().__init__(parent)
        self._history = history
        self._item: SeedUse | None = None
        self._tab_size: tuple[int, int] | None = None
        self._picked: SeedUse | None = None
        self.setEditable(True)
        self.setCompleter(None)
        self.setItemDelegate(_WithThumbnails(self))
        self.view().setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._picture = QLabel(self)
        self._picture.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.editTextChanged.connect(self._refresh_picture)
        self.activated.connect(self._remember_pick)
        self._refresh_picture()

    def describe(self, item_seed: int | None, item_thumbnail: str | None,
                 tab_size: tuple[int, int] | None) -> None:
        self._item = (SeedUse(item_seed, item_thumbnail)
                      if item_seed is not None and item_thumbnail else None)
        self._tab_size = tab_size
        self._refresh_picture()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_picture()

    def _picture_side(self) -> int:
        return max(12, self.height() - 6)

    def _place_picture(self) -> None:
        side = self._picture_side()
        self._picture.setGeometry(self.lineEdit().x() + 1, (self.height() - side) // 2, side, side)
        self._picture.raise_()
        self.lineEdit().setTextMargins(side + 4, 0, 0, 0)

    def _remember_pick(self, row: int) -> None:
        self._picked = self.itemData(row, _USES_ROLE)[0]
        self._refresh_picture()

    def _refresh_picture(self, *_) -> None:
        side = self._picture_side()
        use = self._use_the_field_shows()
        picture = _picture_of(use, side) if use is not None else None
        self._picture.setPixmap(
            picture or _unmade_cell(side, use.size if use is not None else self._tab_size))
        self._place_picture()

    def _use_the_field_shows(self) -> SeedUse | None:
        return next((use for use in (self._picked, self._item)
                     if use is not None and str(use.seed) == self.currentText()), None)

    def showPopup(self):
        seed = self.currentText()
        blocked = self.blockSignals(True)
        self._list(self._history())
        self.setEditText(seed)
        self.blockSignals(blocked)
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

    def _list(self, uses: list[SeedUse]) -> None:
        self.clear()
        most_in_a_row = max(1, _TALLEST_ROW_A_LIST_LAYS_OUT // self._pitch())
        for seed, stretch in groupby(uses, key=attrgetter("seed")):
            stretch = tuple(stretch)
            for start in range(0, len(stretch), most_in_a_row):
                self.addItem(str(seed))
                self.setItemData(self.count() - 1, stretch[start:start + most_in_a_row],
                                 _USES_ROLE)
        self.setCurrentIndex(-1)
        if uses:
            self._widen_to_the_longest_seed()

    def _widen_to_the_longest_seed(self) -> None:
        longest = max(range(self.count()), key=lambda row: len(self.itemText(row)))
        view = self.view()
        row = self.itemDelegate().sizeHint(self._row_option(), self.model().index(longest, 0))
        view.setMinimumWidth(row.width() + view.verticalScrollBar().sizeHint().width()
                             + 2 * view.frameWidth())
