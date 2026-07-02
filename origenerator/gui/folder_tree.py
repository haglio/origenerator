"""The gallery's folder tree, with per-leaf star/delete actions on the left.

Only a leaf folder (a row with no sub-folders) carries actions: a star flush at
its left edge and, on hover, a delete just inside it. The star doubles as the
starred indicator — filled and always shown for a starred leaf, an outline
offered on hover otherwise — so clicking it to star a folder just leaves the star
in place. A row grows a left gutter (and slides its label past it) only while it
actually shows an action, so parent folders and unstarred leaves at rest keep
their normal indentation. Clicking an icon emits ``star_clicked`` /
``delete_clicked`` with the folder's key instead of selecting the row; the tree
hit-tests clicks against the same rects the delegate paints. Which group a row
holds is injected, so this stays free of the gallery model.
"""

from PyQt6.QtWidgets import (
    QApplication, QTreeWidget, QStyledItemDelegate, QStyleOptionViewItem, QStyle,
)
from PyQt6.QtCore import Qt, QRect, pyqtSignal

from origenerator.gui import icons

_ICON = 16   # on-screen size of each action
_PAD = 4     # gap at the edges and between the two icons


def _action_rects(row: QRect):
    """The (star, delete) icon rects at the row's left edge — star flush left,
    delete just inside it. The star keeps a fixed slot so a folder's star doesn't
    shift when the hover-only delete appears beside it."""
    y = row.y() + (row.height() - _ICON) // 2
    star = QRect(row.left() + _PAD, y, _ICON, _ICON)
    delete = QRect(row.left() + _PAD + _ICON + _PAD, y, _ICON, _ICON)
    return star, delete


class _FolderRowDelegate(QStyledItemDelegate):
    def __init__(self, group_role, parent=None):
        super().__init__(parent)
        self._role = group_role
        self._delete = icons.delete_icon()
        self._star = icons.star_icon(filled=False)
        self._star_on = icons.star_icon(filled=True)

    def paint(self, painter, option, index):
        group = index.data(self._role)
        leaf = group is not None and not index.model().hasChildren(index)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        starred = bool(getattr(group, "starred", False))
        show_star = leaf and (starred or hovered)
        show_delete = leaf and hovered
        if not (show_star or show_delete):
            super().paint(painter, option, index)  # no gutter — normal indentation
            return

        # Reserve a left gutter for the shown actions and slide the label past it:
        # paint the full-row background/selection first (no text), then the text in
        # the shifted rect — so the highlight still fills the row but the name clears
        # the icons rather than sitting under them.
        gutter = _PAD + _ICON + _PAD + (_ICON + _PAD if show_delete else 0)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        background = QStyleOptionViewItem(opt)
        background.text = ""
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, background, painter, widget)
        opt.rect = opt.rect.adjusted(gutter, 0, 0, 0)
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)

        star_rect, delete_rect = _action_rects(option.rect)
        if show_star:
            (self._star_on if starred else self._star).paint(painter, star_rect)
        if show_delete:
            self._delete.paint(painter, delete_rect)


class FolderTree(QTreeWidget):
    """A QTreeWidget whose leaf rows carry left-edge star/delete actions."""

    star_clicked = pyqtSignal(object)    # folder key
    delete_clicked = pyqtSignal(object)  # folder key

    def __init__(self, group_role, parent=None):
        super().__init__(parent)
        self._role = group_role
        self.setMouseTracking(True)  # keep the hovered row's actions live as the mouse moves
        self.setItemDelegate(_FolderRowDelegate(group_role, self))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.pos())
            group = index.data(self._role) if index.isValid() else None
            if group is not None and not self.model().hasChildren(index):  # a leaf's actions
                star_rect, delete_rect = _action_rects(self.visualRect(index))
                if delete_rect.contains(event.pos()):
                    self.delete_clicked.emit(group.key)
                    return
                if star_rect.contains(event.pos()):
                    self.star_clicked.emit(group.key)
                    return
        super().mousePressEvent(event)
