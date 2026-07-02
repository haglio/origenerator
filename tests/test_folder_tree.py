from PyQt6.QtCore import Qt, QRect, QPoint
from PyQt6.QtWidgets import QTreeWidgetItem

from origenerator.gui.folder_tree import FolderTree, _action_rects

_ROLE = Qt.ItemDataRole.UserRole


class _Group:
    def __init__(self, key, starred=False):
        self.key = key
        self.starred = starred


def test_action_rects_sit_left_of_the_label_star_nearest():
    content = QRect(60, 0, 140, 24)  # a label indented 60px, leaving room to its left
    star, delete = _action_rects(content)
    assert star.right() <= content.left()      # both sit left of the label...
    assert delete.right() <= star.left()       # ...delete beyond the star
    assert delete.left() >= 0                   # and within the indentation, not off-screen


def _tree_with_leaf(qtbot, *, starred=False):
    tree = FolderTree(_ROLE)
    qtbot.addWidget(tree)
    # Nest the leaf a few levels deep, as real folders are, so its indentation has
    # room for the icons to its left.
    media = QTreeWidgetItem(["Media"]); media.setData(0, _ROLE, _Group("m"))
    wf = QTreeWidgetItem(["Workflow"]); wf.setData(0, _ROLE, _Group("m/w"))
    model = QTreeWidgetItem(["Model"]); model.setData(0, _ROLE, _Group("m/w/mo"))
    leaf = QTreeWidgetItem(["A folder"]); leaf.setData(0, _ROLE, _Group("m/w/mo/key", starred=starred))
    media.addChild(wf)
    wf.addChild(model)
    model.addChild(leaf)
    tree.addTopLevelItem(media)
    tree.expandAll()
    tree.resize(320, 200)
    tree.show()
    qtbot.waitExposed(tree)
    return tree, leaf


def test_clicking_the_delete_icon_on_a_leaf_emits_delete_clicked(qtbot):
    tree, leaf = _tree_with_leaf(qtbot)
    fired = []
    tree.delete_clicked.connect(fired.append)

    _, delete_rect = _action_rects(tree.visualRect(tree.indexFromItem(leaf)))
    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=delete_rect.center())

    assert fired == ["m/w/mo/key"]


def test_clicking_the_star_icon_on_a_leaf_emits_star_clicked(qtbot):
    tree, leaf = _tree_with_leaf(qtbot)
    fired = []
    tree.star_clicked.connect(fired.append)

    star_rect, _ = _action_rects(tree.visualRect(tree.indexFromItem(leaf)))
    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=star_rect.center())

    assert fired == ["m/w/mo/key"]


def test_a_parent_row_offers_no_actions(qtbot):
    tree, leaf = _tree_with_leaf(qtbot)
    parent = leaf.parent()  # "Model" has a child, so it is a non-leaf
    fired = []
    tree.star_clicked.connect(fired.append)
    tree.delete_clicked.connect(fired.append)

    # Where a leaf would show its icons, a parent shows nothing and just selects.
    star_rect, delete_rect = _action_rects(tree.visualRect(tree.indexFromItem(parent)))
    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=star_rect.center())
    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=delete_rect.center())

    assert fired == []
    assert tree.currentItem() is parent


def test_hovering_tracks_the_leaf_under_the_mouse(qtbot):
    tree, leaf = _tree_with_leaf(qtbot)

    qtbot.mouseMove(tree.viewport(), pos=tree.visualRect(tree.indexFromItem(leaf)).center())
    assert tree._hover_key == "m/w/mo/key"  # the hovered leaf, so its delete is drawn

    parent = leaf.parent()
    qtbot.mouseMove(tree.viewport(), pos=tree.visualRect(tree.indexFromItem(parent)).center())
    assert tree._hover_key is None          # a parent isn't tracked — it has no actions


def test_clicking_a_leafs_label_still_selects_without_firing_actions(qtbot):
    tree, leaf = _tree_with_leaf(qtbot)
    fired = []
    tree.star_clicked.connect(fired.append)
    tree.delete_clicked.connect(fired.append)

    row = tree.visualRect(tree.indexFromItem(leaf))
    label_pos = QPoint(row.center().x(), row.center().y())  # on the label, right of the icons
    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=label_pos)

    assert fired == []
    assert tree.currentItem() is leaf  # a normal click still selects the row
