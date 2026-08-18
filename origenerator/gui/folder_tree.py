"""The gallery's folder tree, with per-leaf star/delete actions on the left.

Only a leaf folder (a row with no sub-folders) carries actions, and they sit in
the empty indentation just left of its label — a star right beside the text and,
further left, a delete. Because that space is the row's existing indentation, the
icons appear there on hover without moving the text at all. The star doubles as
the starred indicator: filled and always shown for a starred leaf, an outline
offered on hover otherwise, so clicking it to star a folder just leaves the star
in place. Clicking an icon emits ``star_clicked`` / ``delete_clicked`` with the
folder's key instead of selecting the row; the tree hit-tests clicks against the
same rects it paints. A row carrying a QIcon under ``BRANCH_ICON_ROLE`` (the
Starred and Recents shelves) draws that icon in its caret column so its label
lines up with the sibling folders'. Which group a row holds is injected, so this
stays free of the gallery model.

Folders can be picked several at a time (Shift for a run, Ctrl for a scattered
set) and dragged onto a *collecting* row — one carrying its key under
``DROP_KEY_ROLE``: the Starred shelf, or a custom folder. A drop emits
``folders_dropped`` and is never applied to the tree itself, so nothing is ever
reparented; what a collecting row does with the dropped folders is the view's
business, not this widget's.
"""

from PyQt6.QtWidgets import QTreeWidget, QAbstractItemView
from PyQt6.QtGui import QDrag, QIcon
from PyQt6.QtCore import Qt, QItemSelectionModel, QMimeData, QRect, QSize, pyqtSignal

from origenerator.gui import icons

_ICON = 16   # on-screen size of each action
_PAD = 4     # gap between the label and the icons, and between the two icons

# A row carrying a QIcon here draws it where its disclosure chevron would go, so a
# childless shelf row (Starred, Recents) aligns with the sibling folders instead
# of shifting a glyph into its label. Distinct from the injected group role (plain
# UserRole).
BRANCH_ICON_ROLE = Qt.ItemDataRole.UserRole + 1
# A row carrying its own key here collects dropped folders (Starred, a custom
# folder). Rows without it refuse a drop, so a folder can never be dragged into
# the derived hierarchy, whose shape belongs to the generations' settings.
DROP_KEY_ROLE = Qt.ItemDataRole.UserRole + 2

# The dragged folders' keys, newline-joined. A private type, so a drag out of the
# tree lands nowhere except on a row that collects folders.
FOLDER_KEYS_MIME = "application/x-origenerator-folder-keys"


def _action_rects(content: QRect):
    """The (star, delete) icon rects, laid into the indentation to the left of the
    row's label: the star hugs the text and the delete sits beyond it. The star
    keeps its place next to the label, so revealing the hover-only delete never
    shifts it."""
    y = content.y() + (content.height() - _ICON) // 2
    star = QRect(content.left() - _PAD - _ICON, y, _ICON, _ICON)
    delete = QRect(star.left() - _PAD - _ICON, y, _ICON, _ICON)
    return star, delete


class FolderTree(QTreeWidget):
    """A QTreeWidget whose leaf rows carry star/delete actions in their left margin,
    whose folders can be picked several at a time, and whose collecting rows accept
    folders dragged onto them."""

    star_clicked = pyqtSignal(object)    # folder key
    delete_clicked = pyqtSignal(object)  # folder key
    folders_dropped = pyqtSignal(str, list)  # collecting row's key, dropped folder keys

    def __init__(self, group_role, parent=None):
        super().__init__(parent)
        self._role = group_role
        self._delete = icons.delete_icon()
        self._star = icons.star_icon(filled=False)
        self._star_on = icons.star_icon(filled=True)  # a starred leaf's filled star
        self._hover_key = None  # key of the leaf under the mouse, so its delete shows
        self.setIconSize(QSize(_ICON, _ICON))  # size the per-level chip like the star/delete
        # One indentation per level, no wider than the caret that sits in it. The
        # tree is six levels deep by the time it reaches a settings folder and it
        # lives in the window's narrowest column, so the platform default spends
        # most of that column on empty margin: at Qt's 20px a leaf's label starts
        # 120px in, leaving a thin strip for the label itself.
        self.setIndentation(_ICON)
        self.setMouseTracking(True)  # so hover is tracked without a button held
        # Several folders at once: Shift takes a run, Ctrl a scattered set — the
        # gesture that composes a custom folder.
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # Folders drag out; only a collecting row takes them (see _drop_target_key).
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)

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

    def _leaf_group(self, index):
        """The folder a leaf row holds (one with no sub-folders), else None — parent
        folders and the synthetic shelf get no actions."""
        group = index.data(self._role) if index.isValid() else None
        if group is None or self.model().hasChildren(index):
            return None
        return group

    def _set_hover(self, key):
        if key != self._hover_key:
            self._hover_key = key
            self.viewport().update()  # repaint so the row's actions appear/disappear

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        group = self._leaf_group(self.indexAt(event.pos()))
        self._set_hover(group.key if group is not None else None)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._set_hover(None)

    def drawRow(self, painter, option, index):
        super().drawRow(painter, option, index)
        group = self._leaf_group(index)
        if group is None:
            return
        starred = bool(getattr(group, "starred", False))
        hovered = group.key == self._hover_key
        if not (starred or hovered):
            return
        star_rect, delete_rect = _action_rects(self.visualRect(index))
        (self._star_on if starred else self._star).paint(painter, star_rect)
        if hovered:
            self._delete.paint(painter, delete_rect)

    def drawBranches(self, painter, rect, index):
        """Paint a shelf row's icon (Starred's star, Recents' clock) in its caret
        column, so its label aligns with the sibling folders' rather than sitting a
        chevron-width off. Every other row keeps its normal disclosure control —
        and a folder's level chip is its row *icon*, drawn to the right of the
        caret with the label, because the chip is part of the folder's name."""
        icon = index.data(BRANCH_ICON_ROLE)
        if isinstance(icon, QIcon):
            x = rect.left() + (rect.width() - _ICON) // 2
            y = rect.top() + (rect.height() - _ICON) // 2
            icon.paint(painter, QRect(x, y, _ICON, _ICON))
            return
        super().drawBranches(painter, rect, index)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.pos())
            group = self._leaf_group(index)
            if group is not None:
                star_rect, delete_rect = _action_rects(self.visualRect(index))
                if delete_rect.contains(event.pos()):
                    self.delete_clicked.emit(group.key)
                    return
                if star_rect.contains(event.pos()):
                    self.star_clicked.emit(group.key)
                    return
        super().mousePressEvent(event)

    # --- dragging folders onto a collecting row ----------------------------

    def selected_folder_keys(self) -> list[str]:
        """The keys of the picked folder rows, top-down. Shelf rows that hold no
        folder of their own (Recents, Experiments) contribute nothing."""
        keys = []
        for item in self.selectedItems():
            group = item.data(0, self._role)
            if group is not None:
                keys.append(group.key)
        return keys

    def startDrag(self, supported_actions):
        """Drag the picked folders as their keys. Dragging one row that isn't in
        the selection drags that row alone — the file-manager behavior, and what
        keeps a stale multi-selection from being dropped by accident."""
        pressed = self.currentItem()
        group = pressed.data(0, self._role) if pressed is not None else None
        if group is None:
            return
        keys = self.selected_folder_keys()
        if group.key not in keys:
            keys = [group.key]
        mime = QMimeData()
        mime.setData(FOLDER_KEYS_MIME, "\n".join(keys).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

    def _drop_target_key(self, pos) -> str | None:
        """The key of the collecting row under ``pos``, or ``None`` where a drop
        would land on an ordinary folder, a shelf that collects nothing, or the
        empty space below the tree."""
        index = self.indexAt(pos)
        key = index.data(DROP_KEY_ROLE) if index.isValid() else None
        return key if isinstance(key, str) else None

    def _dragged_keys(self, event) -> list[str]:
        data = event.mimeData().data(FOLDER_KEYS_MIME)
        if data.isEmpty():
            return []
        return [key for key in bytes(data).decode("utf-8").split("\n") if key]

    def dragEnterEvent(self, event):
        if self._dragged_keys(event):
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        """Accept only over a collecting row, so the cursor says outright where the
        folders can land."""
        target = self._drop_target_key(event.position().toPoint())
        keys = self._dragged_keys(event)
        # A row can't collect itself, and dropping a folder back where it came from
        # is nothing — refuse both rather than accept a no-op.
        if target is not None and [k for k in keys if k != target]:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        """Hand the drop to the view and consume it. The base implementation is
        deliberately not called: the tree's shape is derived from the generations,
        so a drop must never move a row."""
        target = self._drop_target_key(event.position().toPoint())
        keys = [k for k in self._dragged_keys(event) if k != target]
        if target is None or not keys:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.folders_dropped.emit(target, keys)
