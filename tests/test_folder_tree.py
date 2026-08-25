from PyQt6.QtCore import Qt, QMimeData, QPoint, QPointF, QRect
from PyQt6.QtGui import QDragMoveEvent, QDropEvent
from PyQt6.QtWidgets import QTreeWidgetItem

from origenerator.gui import folder_tree
from origenerator.gui.folder_tree import (
    DROP_KEY_ROLE, FOLDER_KEYS_MIME, TREE_KEY_ROLE, FolderTree, _action_rects,
)
from origenerator.gui.orientation import LANDSCAPE, oriented_key

_ROLE = Qt.ItemDataRole.UserRole


class _Group:
    def __init__(self, key, starred=False):
        self.key = key
        self.starred = starred


def _folder_row(label, key, starred=False):
    """A folder row as the tree draws one: the folder it holds, and its own key —
    that folder's, plus the side this copy of it is drawn on. The two differ
    because both sides draw the same folder (see origenerator.gui.orientation)."""
    item = QTreeWidgetItem([label])
    item.setData(0, _ROLE, _Group(key, starred))
    item.setData(0, TREE_KEY_ROLE, oriented_key(key, LANDSCAPE))
    return item


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
    media = _folder_row("Media", "m")
    wf = _folder_row("Workflow", "m/w")
    model = _folder_row("Model", "m/w/mo")
    leaf = _folder_row("A folder", "m/w/mo/key", starred=starred)
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


def _caret_pos(tree, item):
    """A point in ``item``'s own disclosure column, where its caret is drawn."""
    row = tree.visualRect(tree.indexFromItem(item))
    return QPoint(row.left() - tree.indentation() // 2, row.center().y())


def test_right_clicking_a_folder_leaves_its_caret_alone(qtbot):
    # QTreeView toggles the caret on a press of any button. A folder with
    # sub-folders wears no star of its own, so its right-click menu is the only
    # way to star it — and the menu covers the tree, so a collapse on the way in
    # is only seen once the menu closes, reading as something the star did.
    tree, leaf = _tree_with_leaf(qtbot)
    parent = leaf.parent()

    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.RightButton,
                     pos=_caret_pos(tree, parent))

    assert parent.isExpanded()
    assert tree.currentItem() is parent  # still picked, so the menu acts on it


def test_left_clicking_the_caret_still_collapses_the_folder(qtbot):
    tree, leaf = _tree_with_leaf(qtbot)
    parent = leaf.parent()

    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton,
                     pos=_caret_pos(tree, parent))

    assert not parent.isExpanded()


def test_hovering_tracks_the_leaf_under_the_mouse(qtbot):
    tree, leaf = _tree_with_leaf(qtbot)

    qtbot.mouseMove(tree.viewport(), pos=tree.visualRect(tree.indexFromItem(leaf)).center())
    # The hovered ROW, so its delete is drawn — and only that copy of the folder.
    assert tree._hover_key == oriented_key("m/w/mo/key", LANDSCAPE)

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
    a = _folder_row("A", "k/a")
    b = _folder_row("B", "k/b")
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

    assert tree.selected_folder_keys() == [oriented_key("k/a", LANDSCAPE),
                                           oriented_key("k/b", LANDSCAPE)]


def test_a_shelf_row_holding_no_folder_contributes_no_key(qtbot):
    tree, shelf, a, _b = _collecting_tree(qtbot)

    shelf.setSelected(True)
    a.setSelected(True)

    assert tree.selected_folder_keys() == [oriented_key("k/a", LANDSCAPE)]


def test_navigating_to_a_row_replaces_the_picked_set(qtbot):
    # setCurrentItem reads the live keyboard modifiers unless told otherwise, so
    # a programmatic move made while Ctrl is held would otherwise ADD the row.
    tree, _shelf, a, b = _collecting_tree(qtbot)
    a.setSelected(True)
    b.setSelected(True)

    tree.setCurrentItem(a)

    assert tree.selected_folder_keys() == [oriented_key("k/a", LANDSCAPE)]


def _started_drags(monkeypatch):
    """Capture the drags ``startDrag`` begins rather than entering the real drag
    loop, which waits on a mouse no test has. Each capture is the test's own list,
    so nothing carries from one test to the next."""
    started = []

    class _Drag:
        def __init__(self, _source):
            self.mime = None
            started.append(self)

        def setMimeData(self, mime):
            self.mime = mime

        def exec(self, action):
            return action

    monkeypatch.setattr(folder_tree, "QDrag", _Drag)
    return started


def test_a_drag_carries_the_picked_folders_in_the_words_the_drop_reads(qtbot, monkeypatch):
    # The payload's producer and its reader, in one pass. Every other drag test
    # here writes the mime itself, so the format could be anything at all and they
    # would all still pass.
    tree, shelf, a, b = _collecting_tree(qtbot)
    started = _started_drags(monkeypatch)
    dropped = []
    tree.folders_dropped.connect(lambda key, keys: dropped.append((key, keys)))
    tree.setCurrentItem(a)
    b.setSelected(True)

    tree.startDrag(Qt.DropAction.CopyAction)
    (drag,) = started
    _drop_at(tree, shelf, drag.mime)

    assert dropped == [("__starred__", [oriented_key("k/a", LANDSCAPE),
                                        oriented_key("k/b", LANDSCAPE)])]


def test_dragging_a_row_outside_the_pick_takes_that_row_alone(qtbot, monkeypatch):
    # The file-manager rule, and what keeps a multi-selection the user has since
    # forgotten about from riding along on the next drag.
    tree, shelf, a, b = _collecting_tree(qtbot)
    started = _started_drags(monkeypatch)
    dropped = []
    tree.folders_dropped.connect(lambda key, keys: dropped.append((key, keys)))
    tree.setCurrentItem(a)
    a.setSelected(False)
    b.setSelected(True)  # the pick is elsewhere; the pressed row is A

    tree.startDrag(Qt.DropAction.CopyAction)
    (drag,) = started
    _drop_at(tree, shelf, drag.mime)

    assert dropped == [("__starred__", [oriented_key("k/a", LANDSCAPE)])]


def test_a_row_holding_no_folder_starts_no_drag_at_all(qtbot, monkeypatch):
    # A shelf collects folders; it is not one, so there is nothing to pick it up by.
    tree, shelf, _a, _b = _collecting_tree(qtbot)
    started = _started_drags(monkeypatch)
    tree.setCurrentItem(shelf)

    tree.startDrag(Qt.DropAction.CopyAction)

    assert started == []


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
