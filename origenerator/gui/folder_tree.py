"""The gallery's folder tree, with per-leaf star/delete actions on the left.

Only a leaf folder (a row with no sub-folders) that collects nothing carries
actions, and they sit in the empty indentation just left of its mark — a star right
beside the mark and, further left, a delete. Because that space is the row's
existing indentation, the icons appear there on hover without moving the row at
all. The star doubles as the favorited indicator: filled and always shown for a
favorited leaf, an outline offered on hover otherwise, so clicking it to favorite
a folder just leaves the star in place. Clicking an icon emits
``favorite_clicked`` / ``delete_clicked`` with the folder's key instead of
selecting the row; the tree hit-tests clicks against the same rects it paints.
Only a left click ever works the caret: a right one just picks the row it lands
on, so opening a folder's menu never shuts the folder. Which group a row holds is
injected, so this stays free of the gallery model.

A row carrying ``RECENT_ROLE`` is one of the folders lately worked in, and wears
a dot at the pane's own left edge — the same place on every row, whatever its
depth, so the marks read down the edge as one column. The tree no longer lifts a
folder when something lands in it — it stays where the row that made it put it,
so the order the settings were tried in survives — and the dot is what is left to
say where the work has been.

Folders can be picked several at a time (Shift for a run, Ctrl for a scattered
set) and dragged onto a *collecting* row — one carrying its key under
``DROP_KEY_ROLE``: the Favorites collection, or a custom folder — and so can an
item dragged from anywhere in the window, onto a row the view says takes it. A
drop emits ``dropped`` and is never applied to the tree itself, so nothing is ever
reparented; what a collecting row does with what lands on it is the view's
business, not this widget's.
"""
from __future__ import annotations

from PyQt6.QtCore import QItemSelectionModel, QMimeData, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QDrag, QDragLeaveEvent, QIcon
from PyQt6.QtWidgets import QAbstractItemView, QMenu, QStyledItemDelegate, QTreeWidget
from shared_ui.spacing import BUTTON_ICON, GAP_SMALL

from origenerator.gui import drop_style, icons
from origenerator.gui.drags import carry, under_way
from origenerator.gui.generation_drag import dragged_generation

_ICON = BUTTON_ICON   # on-screen size of each action
_PAD = GAP_SMALL     # gap between the label and the icons, and between the two icons
_DOT = 6     # diameter of the lately-worked-in mark

# A row carrying its own key here collects dropped folders (Favorites, a custom
# folder). Rows without it refuse a drop, so a folder can never be dragged into
# the derived hierarchy, whose shape belongs to the generations' settings.
DROP_KEY_ROLE = Qt.ItemDataRole.UserRole + 2
# A row's own key in the tree: its folder's key with the side it is drawn on
# appended, so the two copies of one folder are tellable apart (see
# origenerator.orientation). What a folder key alone can't say is which of
# them you picked, hovered, or dragged.
TREE_KEY_ROLE = Qt.ItemDataRole.UserRole + 3
COUNT_ROLE = Qt.ItemDataRole.UserRole + 4
# A row carrying a true value here is one of the folders lately worked in, and
# wears a dot at the pane's left edge. Which folders those are is the gallery
# model's answer (see origenerator.gallery.recently_worked_folders); all this
# knows is the mark.
RECENT_ROLE = Qt.ItemDataRole.UserRole + 5

# The dragged folders' keys, newline-joined. A private type, so a drag out of the
# tree lands nowhere except on a row that collects folders.
FOLDER_KEYS_MIME = "application/x-origenerator-folder-keys"


def _action_rects(content: QRect):
    """The (star, delete) icon rects, laid into the indentation to the left of the
    row's mark: the star hugs the mark and the delete sits beyond it. The star
    keeps its place next to the mark, so revealing the hover-only delete never
    shifts it."""
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
    """Where a lately-worked-in row's dot goes: the pane's own left edge, level
    with the row. The same place on every row whatever its depth, so a column of
    them reads down the edge — and far left of the actions, which follow the
    label inward as a folder nests deeper."""
    return QRect(_PAD, content.y() + (content.height() - _DOT) // 2, _DOT, _DOT)


class _CountBeforeName(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        count = index.data(COUNT_ROLE)
        if count:
            option.text = f"({count}) {option.text}"


class FolderTree(QTreeWidget):
    """A QTreeWidget whose leaf rows carry star/delete actions in their left margin,
    whose folders can be picked several at a time, and whose collecting rows accept
    folders dragged onto them."""

    favorite_clicked = pyqtSignal(object)    # folder key
    delete_clicked = pyqtSignal(object)  # folder key
    dropped = pyqtSignal(str, list, list)  # collecting row's key, folder keys, prompt ids

    def __init__(self, group_role, takes_item=lambda _row_key, _prompt_id: False,
                 takes_folder=lambda _row_key, _folder_key: True, parent=None):
        super().__init__(parent)
        self._role = group_role
        self._takes_item = takes_item  # whether the row under a dragged item takes it
        self._takes_folder = takes_folder  # and the same for each dragged folder
        self._delete = icons.delete_icon()
        self._star = icons.star_icon(filled=False)
        self._star_on = icons.star_icon(filled=True)  # a favorited leaf's filled star
        self._recent = icons.recent_mark_icon()  # a lately-worked-in row's dot
        self._hover_key = None  # key of the leaf under the mouse, so its delete shows
        self._delete_on_picked_rows = True
        self.setItemDelegate(_CountBeforeName(self))
        self.setIconSize(QSize(_ICON, _ICON))  # each row's mark, the size of the star/delete
        # One indentation per level, no wider than the caret that sits in it. The
        # tree is six levels deep by the time it reaches a settings folder and it
        # lives in the window's narrowest column, so the platform default spends
        # most of that column on empty margin: at Qt's 20px a leaf's label starts
        # 120px in, leaving a thin sliver for the label itself.
        self.setIndentation(_ICON)
        self.setMouseTracking(True)  # so hover is tracked without a button held
        # Several folders at once: Shift takes a run, Ctrl a scattered set — the
        # gesture that composes a custom folder.
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # Folders drag out; only a collecting row takes them (see landing_on).
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self._under_way = None  # the payload and source of a drag in flight
        self._aimed = None  # the tree key of the row that drag would land in
        under_way.started.connect(self._light_for)
        under_way.ended.connect(self._put_out)

    def setCurrentItem(self, item, column=0, command=None):
        """Navigate to one row, replacing whatever was picked.

        The default has to be spelled out because the tree allows several rows at
        once: with no explicit command Qt reads the *live* keyboard modifiers, so a
        programmatic move made while the user happens to be holding Ctrl or Shift
        would toggle or extend the selection instead of replacing it — every caller
        here means "go here", never "add this to the picked set".
        """
        if command is None:
            command = QItemSelectionModel.SelectionFlag.ClearAndSelect
        super().setCurrentItem(item, column, command)

    def _group_with_actions(self, index):
        group = index.data(self._role) if index.isValid() else None
        if group is None or self.model().hasChildren(index) or index.data(DROP_KEY_ROLE):
            return None
        return group

    def offer_delete_on_picked_rows(self, offered: bool) -> None:
        if offered != self._delete_on_picked_rows:
            self._delete_on_picked_rows = offered
            self.viewport().update()

    def _offers_delete(self, index) -> bool:
        return self._delete_on_picked_rows or not self.selectionModel().isSelected(index)

    def _set_hover(self, key):
        if key != self._hover_key:
            self._hover_key = key
            self.viewport().update()  # repaint so the row's actions appear/disappear

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        index = self.indexAt(event.pos())
        # The row's key, not the folder's: both sides draw the folder, and only
        # the row under the mouse should light up.
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
        mode = (QIcon.Mode.Selected if self.selectionModel().isSelected(index)
                else QIcon.Mode.Normal)
        if index.data(RECENT_ROLE):
            self._recent.paint(painter, _mark_rect(self.visualRect(index)),
                               Qt.AlignmentFlag.AlignCenter, mode)
        group = self._group_with_actions(index)
        if group is None:
            return
        hovered = index.data(TREE_KEY_ROLE) == self._hover_key
        if not (group.favorite or hovered):
            return
        star_rect, delete_rect = _action_rects(self.visualRect(index))
        if group.favorite:
            self._star_on.paint(painter, star_rect, Qt.AlignmentFlag.AlignCenter, mode)
        else:
            self._star.paint(painter, star_rect)
        if hovered and self._offers_delete(index):
            self._delete.paint(painter, delete_rect)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            # QTreeView toggles the caret under the cursor on a press of *any*
            # button, so a right-click landing in the caret column shuts the row
            # it is opening a menu for. A folder with sub-folders carries no star
            # of its own (the row's actions are a leaf's), so that menu is the
            # only way to favorite one — and the menu pops over the tree, hiding the
            # collapse until it closes, which reads as something the star did.
            # QAbstractItemView's press is the rest of what QTreeView would have
            # done here: pick the row under the cursor, and nothing else.
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

    # --- dragging folders onto a collecting row ----------------------------

    def selected_folder_keys(self) -> list[str]:
        """The tree keys of the picked folder rows, top-down. Collection rows that hold
        no folder of their own (Latest, Experiments) contribute nothing.

        Tree keys rather than folder keys so a set picked across both sides
        stays two distinct folders: composing one out of a folder key alone
        would resolve every folder onto whichever side happened to be open, and
        a grouping of mixed shapes is the one thing the split exists to stop.
        """
        keys = []
        for item in self.selectedItems():
            if item.data(0, self._role) is not None:
                keys.append(item.data(0, TREE_KEY_ROLE))
        return keys

    def startDrag(self, supported_actions):
        """Drag the picked folders as their keys. Dragging one row that isn't in
        the selection drags that row alone — the file-manager behavior, and what
        keeps a stale multi-selection from being dropped by accident."""
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
        """``row``'s collecting key and the folders and items a drag would leave
        there, or ``None`` where it would land on an ordinary folder, a
        collection that collects nothing, or the empty space below the tree.

        A row can't collect itself, and dropping a folder back where it came from
        is nothing, so neither counts as landing."""
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
        """Accept only where the drag would land, so the cursor says outright
        where the folders or the item can go."""
        super().dragMoveEvent(event)  # scrolls the tree while a drag is held at its foot
        if event.position().y() < self.autoScrollMargin():
            self.scrollToTop()  # the folders of your own are there, where a drag nearly always goes
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
        """Hand the drop to the view and consume it. The base implementation is
        deliberately not called: the tree's shape is derived from the generations,
        so a drop must never move a row."""
        super().dragLeaveEvent(QDragLeaveEvent())  # the drag is over, and so is its scrolling
        _row, landing = self._row_and_landing(event)
        if landing is None:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.dropped.emit(*landing)
