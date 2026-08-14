from PyQt6.QtCore import Qt, QMimeData, QPoint, QPointF, QRect
from PyQt6.QtGui import QDragMoveEvent, QDropEvent
from PyQt6.QtWidgets import QTreeWidgetItem

from origenerator.gui.folder_tree import (
    DROP_KEY_ROLE, FOLDER_KEYS_MIME, FolderTree, _action_rects,
)

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


# --- picking several folders, and dragging them onto a collecting row ---------

def _collecting_tree(qtbot):
    """A tree with a collecting shelf row atop two ordinary folders."""
    tree = FolderTree(_ROLE)
    qtbot.addWidget(tree)
    shelf = QTreeWidgetItem(["Starred"])
    shelf.setData(0, DROP_KEY_ROLE, "__starred__")
    a = QTreeWidgetItem(["A"]); a.setData(0, _ROLE, _Group("k/a"))
    b = QTreeWidgetItem(["B"]); b.setData(0, _ROLE, _Group("k/b"))
    for item in (shelf, a, b):
        tree.addTopLevelItem(item)
    tree.resize(320, 200)
    tree.show()
    qtbot.waitExposed(tree)
    return tree, shelf, a, b


def _drag(keys):
    """The mime a folder drag carries. Every caller keeps it in a local of its
    own: a synthetic drop event does not own its QMimeData, so letting it fall out
    of scope frees it under the handler."""
    mime = QMimeData()
    mime.setData(FOLDER_KEYS_MIME, "\n".join(keys).encode("utf-8"))
    return mime


def _drop_at(tree, item, mime):
    pos = QPointF(tree.visualRect(tree.indexFromItem(item)).center())
    event = QDropEvent(pos, Qt.DropAction.CopyAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    tree.dropEvent(event)
    return event


def _drag_move_at(tree, item, mime):
    pos = QPointF(tree.visualRect(tree.indexFromItem(item)).center())
    event = QDragMoveEvent(pos.toPoint(), Qt.DropAction.CopyAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    tree.dragMoveEvent(event)
    return event


def test_several_folders_can_be_picked_at_once(qtbot):
    tree, _shelf, a, b = _collecting_tree(qtbot)

    a.setSelected(True)
    b.setSelected(True)

    assert tree.selected_folder_keys() == ["k/a", "k/b"]


def test_a_shelf_row_holding_no_folder_contributes_no_key(qtbot):
    tree, shelf, a, _b = _collecting_tree(qtbot)

    shelf.setSelected(True)
    a.setSelected(True)

    assert tree.selected_folder_keys() == ["k/a"]


def test_navigating_to_a_row_replaces_the_picked_set(qtbot):
    # setCurrentItem reads the live keyboard modifiers unless told otherwise, so
    # a programmatic move made while Ctrl is held would otherwise ADD the row.
    tree, _shelf, a, b = _collecting_tree(qtbot)
    a.setSelected(True)
    b.setSelected(True)

    tree.setCurrentItem(a)

    assert tree.selected_folder_keys() == ["k/a"]


def test_dropping_folders_on_a_collecting_row_reports_them(qtbot):
    tree, shelf, a, b = _collecting_tree(qtbot)
    dropped = []
    tree.folders_dropped.connect(lambda key, keys: dropped.append((key, keys)))

    mime = _drag(["k/a", "k/b"])

    event = _drop_at(tree, shelf, mime)

    assert dropped == [("__starred__", ["k/a", "k/b"])]
    assert event.isAccepted()
    # The tree's shape comes from the generations, so nothing was reparented.
    assert tree.topLevelItemCount() == 3
    assert shelf.childCount() == 0


def test_an_ordinary_folder_refuses_a_drop(qtbot):
    tree, _shelf, a, b = _collecting_tree(qtbot)
    dropped = []
    tree.folders_dropped.connect(lambda key, keys: dropped.append((key, keys)))

    mime = _drag(["k/a"])

    assert not _drag_move_at(tree, b, mime).isAccepted()
    _drop_at(tree, b, mime)

    assert dropped == []


def test_a_collecting_row_refuses_a_drop_of_only_itself(qtbot):
    tree, shelf, _a, _b = _collecting_tree(qtbot)
    dropped = []
    tree.folders_dropped.connect(lambda key, keys: dropped.append((key, keys)))

    mime = _drag(["__starred__"])

    assert not _drag_move_at(tree, shelf, mime).isAccepted()
    _drop_at(tree, shelf, mime)

    assert dropped == []


def test_a_drop_carrying_something_other_than_folders_is_ignored(qtbot):
    tree, shelf, _a, _b = _collecting_tree(qtbot)
    dropped = []
    tree.folders_dropped.connect(lambda key, keys: dropped.append((key, keys)))
    text = QMimeData()
    text.setText("k/a")  # a plain-text drag from anywhere else

    assert not _drag_move_at(tree, shelf, text).isAccepted()
    _drop_at(tree, shelf, text)

    assert dropped == []
