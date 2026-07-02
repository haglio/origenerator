"""The gallery's folder tree, with per-row star/delete actions on the left.

Every row reserves a small left gutter (so text never sits under the actions):
the star nearest the name and the delete to its left. The star doubles as the
starred indicator — filled and always shown for a starred folder, an outline
offered on hover otherwise, so clicking it to star a folder just leaves the star
in place. Delete shows on hover, for a deletable folder only. Clicking either
emits ``star_clicked`` / ``delete_clicked`` with the folder's key instead of
selecting the row; the tree hit-tests clicks against the same rects the delegate
paints. Which group a row holds and whether it's deletable are injected, so this
stays free of the gallery model.
"""

from PyQt6.QtWidgets import (
    QApplication, QTreeWidget, QStyledItemDelegate, QStyleOptionViewItem, QStyle,
)
from PyQt6.QtCore import Qt, QRect, pyqtSignal

from origenerator.gui import icons

_ICON = 16   # on-screen size of each action
_PAD = 4     # gap at the edges and between the two icons
_GUTTER = _PAD + _ICON + _PAD + _ICON + _PAD  # left space reserved: delete, star, then text


def _action_rects(row: QRect):
    """The (star, delete) icon rects in the row's left gutter — star nearest the
    text, delete to its left. Both are laid out for every row so text lines up;
    the caller decides which to actually show and hit-test."""
    y = row.y() + (row.height() - _ICON) // 2
    delete = QRect(row.left() + _PAD, y, _ICON, _ICON)
    star = QRect(row.left() + _PAD + _ICON + _PAD, y, _ICON, _ICON)
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
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        # The full-row background/selection first (no text), then the text shifted
        # past the gutter — so the highlight still fills the whole row but the name
        # clears the action icons rather than sitting under them.
        background = QStyleOptionViewItem(opt)
        background.text = ""
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, background, painter, widget)
        opt.rect = opt.rect.adjusted(_GUTTER, 0, 0, 0)
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)

        group = index.data(self._role)
        if group is None:
            return
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        starred = getattr(group, "starred", False)
        star_rect, delete_rect = _action_rects(option.rect)
        if starred or hovered:
            (self._star_on if starred else self._star).paint(painter, star_rect)
        if hovered and self._is_deletable(group):
            self._delete.paint(painter, delete_rect)


class FolderTree(QTreeWidget):
    """A QTreeWidget whose rows carry left-gutter star/delete actions."""

    star_clicked = pyqtSignal(object)    # folder key
    delete_clicked = pyqtSignal(object)  # folder key

    def __init__(self, group_role, is_deletable, parent=None):
        super().__init__(parent)
        self._role = group_role
        self._is_deletable = is_deletable
        self.setMouseTracking(True)  # keep the hovered row's actions live as the mouse moves
        self.setItemDelegate(_FolderRowDelegate(group_role, is_deletable, self))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.pos())
            group = index.data(self._role) if index.isValid() else None
            if group is not None:
                star_rect, delete_rect = _action_rects(self.visualRect(index))
                if self._is_deletable(group) and delete_rect.contains(event.pos()):
                    self.delete_clicked.emit(group.key)
                    return
                if star_rect.contains(event.pos()):
                    self.star_clicked.emit(group.key)
                    return
        super().mousePressEvent(event)
