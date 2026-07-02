from PyQt6.QtCore import Qt, QRect, QPoint
from PyQt6.QtWidgets import QTreeWidgetItem

from origenerator.gui.folder_tree import FolderTree, _action_rects

_ROLE = Qt.ItemDataRole.UserRole


class _Group:
    def __init__(self, key, starred=False):
        self.key = key
        self.starred = starred


def test_action_rects_right_align_star_then_delete():
    row = QRect(0, 0, 200, 24)
    star, delete = _action_rects(row, deletable=True)
    assert delete is not None
    assert delete.right() < row.right()          # inset from the edge
    assert star.right() <= delete.left()          # star sits left of delete
    assert row.contains(star) and row.contains(delete)


def test_action_rects_drops_delete_for_a_non_deletable_row():
    star, delete = _action_rects(QRect(0, 0, 200, 24), deletable=False)
    assert delete is None
    assert star.right() < 200                      # star takes the rightmost slot


def _tree_with_one_row(qtbot, *, deletable=True, starred=False):
    tree = FolderTree(_ROLE, lambda g: deletable)
    qtbot.addWidget(tree)
    item = QTreeWidgetItem(["A folder"])
    item.setData(0, _ROLE, _Group("media/wf/key", starred=starred))
    tree.addTopLevelItem(item)
    tree.resize(300, 120)
    tree.show()
    qtbot.waitExposed(tree)
    return tree, item


def test_clicking_the_delete_icon_emits_delete_clicked(qtbot):
    tree, item = _tree_with_one_row(qtbot)
    fired = []
    tree.delete_clicked.connect(fired.append)

    _, delete_rect = _action_rects(tree.visualRect(tree.indexFromItem(item)), deletable=True)
    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=delete_rect.center())

    assert fired == ["media/wf/key"]


def test_clicking_the_star_icon_emits_star_clicked(qtbot):
    tree, item = _tree_with_one_row(qtbot)
    fired = []
    tree.star_clicked.connect(fired.append)

    star_rect, _ = _action_rects(tree.visualRect(tree.indexFromItem(item)), deletable=True)
    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=star_rect.center())

    assert fired == ["media/wf/key"]


def test_clicking_the_label_still_selects_without_firing_actions(qtbot):
    tree, item = _tree_with_one_row(qtbot)
    fired = []
    tree.star_clicked.connect(fired.append)
    tree.delete_clicked.connect(fired.append)

    row = tree.visualRect(tree.indexFromItem(item))
    label_pos = QPoint(row.left() + 8, row.center().y())  # on the text, far from the icons
    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=label_pos)

    assert fired == []
    assert tree.currentItem() is item  # a normal click still selects the row
