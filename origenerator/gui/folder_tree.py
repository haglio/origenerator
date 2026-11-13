from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QItemSelectionModel, QMimeData, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QDrag, QDragLeaveEvent, QFontMetricsF, QIcon, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
)
from shared_ui.colors import BLUE, BORDER_SUBTLE, TEXT_MUTED, TEXT_PRIMARY
from shared_ui.spacing import BUTTON_ICON, GAP_SMALL

from origenerator.gui import drop_style, icons
from origenerator.gui.drags import carry, under_way
from origenerator.gui.generation_drag import dragged_generation

_ICON = BUTTON_ICON
_PAD = GAP_SMALL
_DOT = 6

DROP_KEY_ROLE = Qt.ItemDataRole.UserRole + 2
TREE_KEY_ROLE = Qt.ItemDataRole.UserRole + 3
COUNT_ROLE = Qt.ItemDataRole.UserRole + 4
RECENT_ROLE = Qt.ItemDataRole.UserRole + 5

_SETTLING_ROUNDS = 4

FOLDER_KEYS_MIME = "application/x-origenerator-folder-keys"


def _action_rects(content: QRect):
    y = content.y() + (content.height() - _ICON) // 2
    star = QRect(content.left() - _PAD - _ICON, y, _ICON, _ICON)
    delete = QRect(star.left() - _PAD - _ICON, y, _ICON, _ICON)
    return star, delete


def offer_collapse_and_expand(menu: QMenu, rows) -> dict:
    if not any(row.childCount() for row in rows):
        return {}
    menu.addSeparator()
    return {menu.addAction("Collapse all"): lambda: _expand_throughout(rows, False),
            menu.addAction("Expand all"): lambda: _expand_throughout(rows, True)}


def _expand_throughout(rows, expanded: bool) -> None:
    for row in rows:
        if row.childCount():
            row.setExpanded(expanded)
            _expand_throughout((row.child(i) for i in range(row.childCount())), expanded)


def _mark_rect(content: QRect) -> QRect:
    return QRect(_PAD, content.y() + (content.height() - _DOT) // 2, _DOT, _DOT)


def _is_all(row, group_role, all_key) -> bool:
    return getattr(row.data(0, group_role), "key", None) == all_key


def _path_of(row, group_role, all_key) -> list:
    return [] if _is_all(row, group_role, all_key) else [*_folders_around(row, group_role, all_key), row]


def _folders_around(row, group_role, all_key) -> list:
    folders = []
    node = row.parent() if row is not None else None
    while node is not None and not _is_all(node, group_role, all_key):
        folders.append(node)
        node = node.parent()
    return folders[::-1]


def _holds(folder, row) -> bool:
    while row is not None:
        if row is folder:
            return True
        row = row.parent()
    return False


_DIGIT_WIDE_SPACE = "\u2007"


class _CountBeforeName(QStyledItemDelegate):
    def __init__(self, parent):
        super().__init__(parent)
        self._widest_among_siblings: dict = {}

    def forget_the_widest_counts(self, *_changed) -> None:
        self._widest_among_siblings.clear()

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        widest = self._widest_count(index)
        if widest:
            option.text = _DIGIT_WIDE_SPACE * _spaces_for_counts(option, widest) + option.text

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        count = self.count_shown(index)
        if not count:
            return
        shown = QStyleOptionViewItem(option)
        self.initStyleOption(shown, index)
        _draw_count(painter, shown, count_place(shown, self._widest_count(index)), count)

    @staticmethod
    def count_shown(index) -> str:
        count = index.data(COUNT_ROLE)
        return f"({count})" if count else ""

    def _widest_count(self, index) -> int:
        parent = index.parent()
        place = (parent.row(), parent.column(), parent.internalId()) if parent.isValid() else None
        if place not in self._widest_among_siblings:
            model = index.model()
            self._widest_among_siblings[place] = max(
                len(str(model.index(row, 0, parent).data(COUNT_ROLE) or ""))
                for row in range(model.rowCount(parent)))
        return self._widest_among_siblings[place]


def _draw_count(painter, option, place: QRectF, count: str) -> None:
    painter.save()
    painter.setFont(option.font)
    picked = bool(option.state & QStyle.StateFlag.State_Selected)
    painter.setPen(TEXT_PRIMARY if picked else TEXT_MUTED)
    painter.drawText(place, Qt.AlignmentFlag.AlignCenter, count)
    painter.restore()


def _spaces_for_counts(option, widest: int) -> int:
    metrics = QFontMetricsF(option.font)
    needed = metrics.horizontalAdvance(f"({'0' * widest}) ")
    return math.ceil(needed / metrics.horizontalAdvance(_DIGIT_WIDE_SPACE))


def count_place(option, widest: int) -> QRectF:
    widget = option.widget
    style = widget.style() if widget is not None else QApplication.style()
    text = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, option, widget)
    margin = style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, option, widget) + 1
    metrics = QFontMetricsF(option.font)
    column = (_spaces_for_counts(option, widest) * metrics.horizontalAdvance(_DIGIT_WIDE_SPACE)
              - metrics.horizontalAdvance(" "))
    return QRectF(text.left() + margin, text.top(), column, text.height())


class FolderTree(QTreeWidget):
    favorite_clicked = Signal(object)
    delete_clicked = Signal(object)
    dropped = Signal(str, list, list)

    def __init__(self, group_role, *, all_key: str, takes_item=lambda _row_key, _prompt_id: False,
                 takes_folder=lambda _row_key, _folder_key: True, parent=None):
        super().__init__(parent)
        self._role = group_role
        self._all_key = all_key
        self._takes_item = takes_item
        self._takes_folder = takes_folder
        self._delete = icons.delete_icon()
        self._star = icons.star_icon(filled=False)
        self._star_on = icons.star_icon(filled=True)
        self._recent = icons.recent_mark_icon()
        self._hover_key = None
        self._delete_on_picked_rows = True
        self._pressed_on_frozen = False
        counts = _CountBeforeName(self)
        self.setItemDelegate(counts)
        for changed in (self.model().dataChanged, self.model().rowsInserted,
                        self.model().rowsRemoved, self.model().layoutChanged,
                        self.model().modelReset):
            changed.connect(counts.forget_the_widest_counts)
        self.setIconSize(QSize(_ICON, _ICON))
        # Qt's default 20px indentation leaves a six-level tree in the narrowest column too little room for the label
        self.setIndentation(_ICON)
        self.setMouseTracking(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self._under_way = None
        self._aimed = None
        under_way.started.connect(self._light_for)
        under_way.ended.connect(self._put_out)
        self.verticalScrollBar().valueChanged.connect(self.viewport().update)

    def setCurrentItem(self, item, column=0, command=None):
        # Qt reads the live keyboard modifiers when no command is given, so Ctrl or Shift held during a programmatic move would extend the selection
        if command is None:
            command = QItemSelectionModel.SelectionFlag.ClearAndSelect
        super().setCurrentItem(item, column, command)

    def _group_with_actions(self, index):
        group = index.data(self._role) if index.isValid() else None
        if group is None or self.model().hasChildren(index) or index.data(DROP_KEY_ROLE):
            return None
        return group

    def frozen_rows(self) -> list:
        held = []
        for _round in range(_SETTLING_ROUNDS):
            frozen = self._frozen_while_scrolling(held)
            passed = self._in_list_order(
                [folder for row in self.selectedItems() if self._scrolled_past(row, frozen)
                 for folder in _path_of(row, self._role, self._all_key)])
            if len(passed) == len(held) and all(a is b for a, b in zip(passed, held, strict=True)):
                break
            held = passed
        return frozen

    def _frozen_while_scrolling(self, held: list) -> list:
        chain = []
        while True:
            shown = self._in_list_order(chain + held)
            folders = _folders_around(self.itemAt(0, self._height_of(shown)), self._role, self._all_key)
            if len(folders) <= len(chain) or folders[:len(chain)] != chain:
                return shown
            folder = folders[len(chain)]
            below = self.itemAt(0, self._height_of(self._in_list_order([*chain, folder, *held])))
            if not _holds(folder, below):
                return shown
            chain.append(folder)

    def _scrolled_past(self, row, frozen: list) -> bool:
        place = self.visualItemRect(row)
        return place.isValid() and place.top() < self._height_of(frozen)

    def _in_list_order(self, rows) -> list:
        unique = []
        for row in rows:
            if not any(row is seen for seen in unique):
                unique.append(row)
        return sorted(unique, key=lambda row: self.visualItemRect(row).top())

    def _height_of(self, rows) -> int:
        return sum(self.visualItemRect(row).height() for row in rows)

    def selectionChanged(self, selected, deselected):
        super().selectionChanged(selected, deselected)
        self.viewport().update()

    def _frozen_places(self) -> list:
        places, top = [], 0
        for row in self.frozen_rows():
            height = self.visualItemRect(row).height()
            places.append((row, QRect(0, top, self.viewport().width(), height)))
            top += height
        return places

    def paintEvent(self, event):
        super().paintEvent(event)
        places = self._frozen_places()
        if not places:
            return
        painter = QPainter(self.viewport())
        for row, place in places:
            self._paint_frozen(painter, self.indexFromItem(row), place)
        under = places[-1][1].bottom() + 1
        painter.fillRect(QRect(0, under, self.viewport().width(), 1), BORDER_SUBTLE)
        painter.end()

    def _paint_frozen(self, painter, index, place: QRect) -> None:
        painter.fillRect(place, self.viewport().palette().color(self.viewport().backgroundRole()))
        content = self.visualRect(index)
        content.moveTop(place.top())
        option = QStyleOptionViewItem()
        self.initViewItemOption(option)
        option.state |= QStyle.StateFlag.State_Children | QStyle.StateFlag.State_Open
        if self.selectionModel().isSelected(index):
            option.state |= QStyle.StateFlag.State_Selected
            painter.fillRect(QRect(0, place.top(), content.left(), place.height()), BLUE)
        option.rect = QRect(content.left() - self.indentation(), place.top(),
                            self.indentation(), place.height())
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorBranch, option, painter, self)
        option.rect = content
        self.itemDelegate().paint(painter, option, index)
        self._paint_marks(painter, content, index)

    def offer_delete_on_picked_rows(self, offered: bool) -> None:
        if offered != self._delete_on_picked_rows:
            self._delete_on_picked_rows = offered
            self.viewport().update()

    def _offers_delete(self, index) -> bool:
        return self._delete_on_picked_rows or not self.selectionModel().isSelected(index)

    def _set_hover(self, key):
        if key != self._hover_key:
            self._hover_key = key
            self.viewport().update()

    def mouseMoveEvent(self, event):
        if self._pressed_on_frozen:
            event.accept()
            return
        super().mouseMoveEvent(event)
        index = self.indexAt(event.position().toPoint())
        hovered = index.data(TREE_KEY_ROLE) if self._group_with_actions(index) else None
        self._set_hover(hovered)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._set_hover(None)

    def _light_for(self, mime, source):
        self._under_way = (mime, source)
        self.viewport().update()

    def _put_out(self):
        self._under_way = self._aimed = None
        self.viewport().update()

    def _aim(self, row):
        key = row.data(0, TREE_KEY_ROLE) if row is not None else None
        if key != self._aimed:
            self._aimed = key
            self.viewport().update()

    def _drop_style_of(self, index) -> str | None:
        if self._under_way is None:
            return None
        if self._aimed is not None and index.data(TREE_KEY_ROLE) == self._aimed:
            return drop_style.AIMED
        landing = self.landing_on(self.itemFromIndex(index), *self._under_way)
        return drop_style.LIT if landing is not None else None

    def drawRow(self, painter, option, index):
        state = self._drop_style_of(index)
        if state is not None:
            drop_style.paint(painter, QRect(0, option.rect.y(), self.viewport().width(),
                                            option.rect.height()), drop_style.GROUNDS[state])
        super().drawRow(painter, option, index)
        self._paint_marks(painter, self.visualRect(index), index)

    def _paint_marks(self, painter, content: QRect, index) -> None:
        mode = (QIcon.Mode.Selected if self.selectionModel().isSelected(index)
                else QIcon.Mode.Normal)
        if index.data(RECENT_ROLE):
            self._recent.paint(painter, _mark_rect(content),
                               Qt.AlignmentFlag.AlignCenter, mode)
        group = self._group_with_actions(index)
        if group is None:
            return
        hovered = index.data(TREE_KEY_ROLE) == self._hover_key
        if not (group.favorite or hovered):
            return
        star_rect, delete_rect = _action_rects(content)
        if group.favorite:
            self._star_on.paint(painter, star_rect, Qt.AlignmentFlag.AlignCenter, mode)
        else:
            self._star.paint(painter, star_rect)
        if hovered and self._offers_delete(index):
            self._delete.paint(painter, delete_rect)

    def _frozen_at(self, point):
        return next((row for row, place in self._frozen_places() if place.contains(point)), None)

    def _swallowed_by_frozen(self, event, point) -> bool:
        if self._frozen_at(point) is None:
            return False
        event.accept()
        return True

    def _pick_frozen(self, row, modifiers) -> None:
        if not modifiers & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier):
            self._bring_back(row)
            return
        scrolls = self.hasAutoScroll()
        self.setAutoScroll(False)
        self._pick_in_place(self.indexFromItem(row), modifiers)
        self.setAutoScroll(scrolls)

    def _pick_in_place(self, index, modifiers) -> None:
        flags = QItemSelectionModel.SelectionFlag
        if modifiers & Qt.KeyboardModifier.ShiftModifier and self.currentIndex().isValid():
            keep = flags.Select if modifiers & Qt.KeyboardModifier.ControlModifier else flags.ClearAndSelect
            span = self.visualRect(self.currentIndex()).united(self.visualRect(index))
            self.setSelection(span, keep | flags.Rows)
            self.selectionModel().setCurrentIndex(index, flags.NoUpdate)
        else:
            self.selectionModel().setCurrentIndex(index, flags.Toggle | flags.Rows)

    def _bring_back(self, row) -> None:
        self.setCurrentItem(row)
        self.scrollToItem(row, QAbstractItemView.ScrollHint.PositionAtTop)
        bar = self.verticalScrollBar()
        while bar.value() > bar.minimum() and row in self.frozen_rows():
            bar.setValue(bar.value() - 1)

    def mouseDoubleClickEvent(self, event):
        if not self._swallowed_by_frozen(event, event.position().toPoint()):
            super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        if self._pressed_on_frozen:
            self._pressed_on_frozen = False
            event.accept()
            return
        if not self._swallowed_by_frozen(event, event.position().toPoint()):
            super().mouseReleaseEvent(event)

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.ContextMenu and self._swallowed_by_frozen(event, event.pos()):
            return True
        return super().viewportEvent(event)

    def mousePressEvent(self, event):
        frozen = self._frozen_at(event.position().toPoint())
        if frozen is not None:
            event.accept()
            self._pressed_on_frozen = True
            self._pick_frozen(frozen, event.modifiers())
            return
        if event.button() != Qt.MouseButton.LeftButton:
            # Qt: QTreeView toggles the caret under any button's press; QAbstractItemView's press only picks the row, so a right-click never shuts a folder
            QAbstractItemView.mousePressEvent(self, event)
            return
        index = self.indexAt(event.position().toPoint())
        group = self._group_with_actions(index)
        if group is not None:
            star_rect, delete_rect = _action_rects(self.visualRect(index))
            if delete_rect.contains(event.position().toPoint()) and self._offers_delete(index):
                self.delete_clicked.emit(group.key)
                return
            if star_rect.contains(event.position().toPoint()):
                self.favorite_clicked.emit(group.key)
                return
        super().mousePressEvent(event)

    def selected_folder_keys(self) -> list[str]:
        return [item.data(0, TREE_KEY_ROLE) for item in self.selectedItems()
                if item.data(0, self._role) is not None]

    def startDrag(self, supported_actions):
        pressed = self.currentItem()
        if pressed is None or pressed.data(0, self._role) is None:
            return
        keys = self.selected_folder_keys()
        if pressed.data(0, TREE_KEY_ROLE) not in keys:
            keys = [pressed.data(0, TREE_KEY_ROLE)]
        mime = QMimeData()
        mime.setData(FOLDER_KEYS_MIME, "\n".join(keys).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        carry(drag, mime, self, Qt.DropAction.CopyAction)

    def _row_and_landing(self, event):
        row = self.itemAt(event.position().toPoint())
        return row, self.landing_on(row, event.mimeData(), event.source())

    def landing_on(self, row, mime, source) -> tuple[str, list, list] | None:
        target = row.data(0, DROP_KEY_ROLE) if row is not None else None
        if not isinstance(target, str):
            return None
        row_key = row.data(0, TREE_KEY_ROLE)
        folders = [key for key in self._dragged_keys(mime, source)
                   if key not in (target, row_key) and self._takes_folder(row_key, key)]
        item = dragged_generation(mime)
        items = [item] if item is not None and self._takes_item(row_key, item) else []
        return (target, folders, items) if folders or items else None

    def _dragged_keys(self, mime, source) -> list[str]:
        if isinstance(source, FolderTree) and source is not self:
            return []
        data = mime.data(FOLDER_KEYS_MIME)
        if data.isEmpty():
            return []
        return [key for key in bytes(data).decode("utf-8").split("\n") if key]

    def dragEnterEvent(self, event):
        # Qt: a drag refused on entry is sent no moves, so it would never be offered a row to land on.
        mime = event.mimeData()
        if self._dragged_keys(mime, event.source()) or dragged_generation(mime) is not None:
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        super().dragMoveEvent(event)
        if event.position().y() < self.autoScrollMargin():
            self.scrollToTop()
        row, landing = self._row_and_landing(event)
        self._aim(row if landing is not None else None)
        if landing is None:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def dragLeaveEvent(self, event):
        super().dragLeaveEvent(event)
        self._aim(None)

    def dropEvent(self, event):
        super().dragLeaveEvent(QDragLeaveEvent())
        _row, landing = self._row_and_landing(event)
        if landing is None:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.dropped.emit(*landing)
