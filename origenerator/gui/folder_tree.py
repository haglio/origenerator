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
"""

from PyQt6.QtWidgets import QTreeWidget
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt, QRect, QSize, pyqtSignal

from origenerator.gui import icons

_ICON = 16   # on-screen size of each action
_PAD = 4     # gap between the label and the icons, and between the two icons

# A row carrying a QIcon here draws it where its disclosure chevron would go, so a
# childless shelf row (Starred, Recents) aligns with the sibling folders instead
# of shifting a glyph into its label. Distinct from the injected group role (plain
# UserRole).
BRANCH_ICON_ROLE = Qt.ItemDataRole.UserRole + 1


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
    """A QTreeWidget whose leaf rows carry star/delete actions in their left margin."""

    star_clicked = pyqtSignal(object)    # folder key
    delete_clicked = pyqtSignal(object)  # folder key

    def __init__(self, group_role, parent=None):
        super().__init__(parent)
        self._role = group_role
        self._delete = icons.delete_icon()
        self._star = icons.star_icon(filled=False)
        self._star_on = icons.star_icon(filled=True)  # a starred leaf's filled star
        self._hover_key = None  # key of the leaf under the mouse, so its delete shows
        self.setIconSize(QSize(_ICON, _ICON))  # size the per-level chip like the star/delete
        self.setMouseTracking(True)  # so hover is tracked without a button held

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
        chevron-width off. Every other row keeps its normal disclosure control."""
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
