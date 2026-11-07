from __future__ import annotations

from PyQt6.QtCore import QEvent, QItemSelectionModel, QMimeData, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QDrag, QDragLeaveEvent, QIcon, QPainter
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
)
from shared_ui.colors import BLUE, BORDER_SUBTLE
from shared_ui.spacing import BUTTON_ICON, GAP_SMALL

from origenerator.gallery.tree import ALL_KEY
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


def _folders_around(row, group_role) -> list:
    folders = []
    node = row.parent() if row is not None else None
    while node is not None and getattr(node.data(0, group_role), "key", None) != ALL_KEY:
        folders.append(node)
        node = node.parent()
    return folders[::-1]


def _holds(folder, row) -> bool:
    while row is not None:
        if row is folder:
            return True
        row = row.parent()
    return False


class _CountBeforeName(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        count = index.data(COUNT_ROLE)
        if count:
            option.text = f"({count}) {option.text}"


class FolderTree(QTreeWidget):
    favorite_clicked = pyqtSignal(object)
    delete_clicked = pyqtSignal(object)
    dropped = pyqtSignal(str, list, list)

    def __init__(self, group_role, takes_item=lambda _row_key, _prompt_id: False,
                 takes_folder=lambda _row_key, _folder_key: True, parent=None):
        super().__init__(parent)
        self._role = group_role
        self._takes_item = takes_item
        self._takes_folder = takes_folder
        self._delete = icons.delete_icon()
        self._star = icons.star_icon(filled=False)
        self._star_on = icons.star_icon(filled=True)
        self._recent = icons.recent_mark_icon()
        self._hover_key = None
        self._delete_on_picked_rows = True
        self.setItemDelegate(_CountBeforeName(self))
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
        frozen = []
        while True:
            depth = sum(self.visualItemRect(row).height() for row in frozen)
            folders = _folders_around(self.itemAt(0, depth), self._role)
            if len(folders) <= len(frozen):
                return frozen
            folder = folders[len(frozen)]
            below = self.itemAt(0, depth + self.visualItemRect(folder).height())
            if not _holds(folder, below):
                return frozen
            frozen.append(folder)

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
        super().mouseMoveEvent(event)
        index = self.indexAt(event.pos())
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

    def _swallowed_by_frozen(self, event) -> bool:
        if self._frozen_at(event.pos()) is None:
            return False
        event.accept()
        return True

    def mouseDoubleClickEvent(self, event):
        if not self._swallowed_by_frozen(event):
            super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        if not self._swallowed_by_frozen(event):
            super().mouseReleaseEvent(event)

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.ContextMenu and self._swallowed_by_frozen(event):
            return True
        return super().viewportEvent(event)

    def mousePressEvent(self, event):
        if self._swallowed_by_frozen(event):
            return
        if event.button() != Qt.MouseButton.LeftButton:
            # Qt: QTreeView toggles the caret under any button's press; QAbstractItemView's press only picks the row, so a right-click never shuts a folder
            QAbstractItemView.mousePressEvent(self, event)
            return
        index = self.indexAt(event.pos())
        group = self._group_with_actions(index)
        if group is not None:
            star_rect, delete_rect = _action_rects(self.visualRect(index))
            if delete_rect.contains(event.pos()) and self._offers_delete(index):
                self.delete_clicked.emit(group.key)
                return
            if star_rect.contains(event.pos()):
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
