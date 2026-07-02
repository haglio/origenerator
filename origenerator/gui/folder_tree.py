"""The gallery's folder tree, with per-row hover actions.

Hovering a row reveals a star toggle and (for a deletable folder) a delete button
at its left edge; clicking one emits ``star_clicked`` / ``delete_clicked`` with
the folder's key instead of selecting the row. The star sits leftmost — right
where a starred folder's ★ marker shows — so toggling it reads as that marker
appearing in place. A delegate paints the icons on the hovered row; the tree
hit-tests clicks against the same rects. Which group a row holds and whether it's
deletable are injected, so this stays free of the gallery model.
"""

from PyQt6.QtWidgets import QTreeWidget, QStyledItemDelegate, QStyle
from PyQt6.QtCore import Qt, QRect, pyqtSignal

from origenerator.gui import icons

_ICON = 16   # on-screen size of each hover action
_PAD = 4     # gap from the row's left edge and between the two icons


def _action_rects(row: QRect, deletable: bool):
    """The (star, delete) icon rects, left-aligned at the row's start; ``delete``
    is ``None`` for a folder that can't be deleted. Star is leftmost — where a
    starred folder's ★ marker sits — so toggling it looks like the marker itself."""
    y = row.y() + (row.height() - _ICON) // 2
    x = row.left() + _PAD
    star = QRect(x, y, _ICON, _ICON)
    delete = QRect(x + _ICON + _PAD, y, _ICON, _ICON) if deletable else None
    return star, delete


class _FolderRowDelegate(QStyledItemDelegate):
    def __init__(self, group_role, is_deletable, parent=None):
        super().__init__(parent)
        self._role = group_role
        self._is_deletable = is_deletable
        self._delete = icons.delete_icon()
        self._star = icons.star_icon(filled=False)
        self._star_on = icons.star_icon(filled=True)

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if not (option.state & QStyle.StateFlag.State_MouseOver):
            return
        group = index.data(self._role)
        if group is None:
            return
        deletable = self._is_deletable(group)
        star_rect, delete_rect = _action_rects(option.rect, deletable)
        starred = getattr(group, "starred", False)
        (self._star_on if starred else self._star).paint(painter, star_rect)
        if delete_rect is not None:
            self._delete.paint(painter, delete_rect)


class FolderTree(QTreeWidget):
    """A QTreeWidget whose rows show hover star/delete actions."""

    star_clicked = pyqtSignal(object)    # folder key
    delete_clicked = pyqtSignal(object)  # folder key

    def __init__(self, group_role, is_deletable, parent=None):
        super().__init__(parent)
        self._role = group_role
        self._is_deletable = is_deletable
        self.setMouseTracking(True)  # keep the hovered row's icons live as the mouse moves
        self.setItemDelegate(_FolderRowDelegate(group_role, is_deletable, self))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.pos())
            group = index.data(self._role) if index.isValid() else None
            if group is not None:
                star_rect, delete_rect = _action_rects(
                    self.visualRect(index), self._is_deletable(group)
                )
                if delete_rect is not None and delete_rect.contains(event.pos()):
                    self.delete_clicked.emit(group.key)
                    return
                if star_rect.contains(event.pos()):
                    self.star_clicked.emit(group.key)
                    return
        super().mousePressEvent(event)
