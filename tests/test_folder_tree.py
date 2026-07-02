from PyQt6.QtCore import Qt, QRect, QPoint
from PyQt6.QtWidgets import QTreeWidgetItem

from origenerator.gui.folder_tree import FolderTree, _action_rects

_ROLE = Qt.ItemDataRole.UserRole


class _Group:
    def __init__(self, key, starred=False):
        self.key = key
        self.starred = starred


def test_action_rects_put_the_star_flush_left_then_the_delete():
    row = QRect(0, 0, 200, 24)
    star, delete = _action_rects(row)
    assert star.left() >= row.left()          # star flush at the left edge
    assert star.right() <= delete.left()      # delete sits just inside the star
    assert row.contains(star) and row.contains(delete)


def _tree_with_leaf(qtbot, *, starred=False):
    tree = FolderTree(_ROLE)
    qtbot.addWidget(tree)
    item = QTreeWidgetItem(["A folder"])  # no children -> a leaf that carries actions
    item.setData(0, _ROLE, _Group("media/wf/key", starred=starred))
    tree.addTopLevelItem(item)
    tree.resize(300, 120)
    tree.show()
    qtbot.waitExposed(tree)
    return tree, item


def test_clicking_the_delete_icon_on_a_leaf_emits_delete_clicked(qtbot):
    tree, item = _tree_with_leaf(qtbot)
    fired = []
    tree.delete_clicked.connect(fired.append)

    _, delete_rect = _action_rects(tree.visualRect(tree.indexFromItem(item)))
    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=delete_rect.center())

    assert fired == ["media/wf/key"]


def test_clicking_the_star_icon_on_a_leaf_emits_star_clicked(qtbot):
    tree, item = _tree_with_leaf(qtbot)
    fired = []
    tree.star_clicked.connect(fired.append)

    star_rect, _ = _action_rects(tree.visualRect(tree.indexFromItem(item)))
    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=star_rect.center())

    assert fired == ["media/wf/key"]


def test_a_parent_row_offers_no_actions(qtbot):
    tree = FolderTree(_ROLE)
    qtbot.addWidget(tree)
    parent = QTreeWidgetItem(["Parent"])
    parent.setData(0, _ROLE, _Group("media/wf"))
    child = QTreeWidgetItem(["Child"])
    child.setData(0, _ROLE, _Group("media/wf/leaf"))
    parent.addChild(child)  # having a child makes the parent a non-leaf
    tree.addTopLevelItem(parent)
    tree.expandAll()
    tree.resize(300, 120)
    tree.show()
    qtbot.waitExposed(tree)

    fired = []
    tree.star_clicked.connect(fired.append)
    tree.delete_clicked.connect(fired.append)
    star_rect, delete_rect = _action_rects(tree.visualRect(tree.indexFromItem(parent)))
    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=star_rect.center())
    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=delete_rect.center())

    assert fired == []                    # a folder with sub-folders has no star/delete
    assert tree.currentItem() is parent   # the clicks just select it


def test_clicking_a_leafs_label_still_selects_without_firing_actions(qtbot):
    tree, item = _tree_with_leaf(qtbot)
    fired = []
    tree.star_clicked.connect(fired.append)
    tree.delete_clicked.connect(fired.append)

    row = tree.visualRect(tree.indexFromItem(item))
    label_pos = QPoint(row.right() - 8, row.center().y())  # right side, clear of the left icons
    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=label_pos)

    assert fired == []
    assert tree.currentItem() is item  # a normal click still selects the row
