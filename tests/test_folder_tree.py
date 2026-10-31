from __future__ import annotations

from PyQt6.QtCore import QMimeData, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PyQt6.QtWidgets import QStyle, QStyleOptionViewItem, QTreeWidgetItem
from shared_ui.colors import BLUE

from origenerator.gallery.collection import COLLECTION_LABELS, FAVORITES_KEY, LATEST_KEY
from origenerator.gallery.sides import LANDSCAPE
from origenerator.gui import folder_tree, icons
from origenerator.gui.drags import under_way
from origenerator.gui.drop_style import AIMED, LIT
from origenerator.gui.folder_tree import (
    COUNT_ROLE,
    DROP_KEY_ROLE,
    FOLDER_KEYS_MIME,
    RECENT_ROLE,
    TREE_KEY_ROLE,
    FolderTree,
    _action_rects,
)
from origenerator.gui.generation_drag import generation_mime
from origenerator.gui.stylesheet import build_stylesheet
from origenerator.orientation import oriented_key
from tests.drop_style_seen import worn
from tests.heard_drags import HeardDrags

_ROLE = Qt.ItemDataRole.UserRole


class _Group:
    def __init__(self, key, favorite=False):
        self.key = key
        self.favorite = favorite


def _folder_row(label, key, favorite=False):
    """A folder row as the tree draws one: the folder it holds, and its own key —
    that folder's, plus the side this copy of it is drawn on. The two differ
    because both sides draw the same folder (see origenerator.orientation)."""
    item = QTreeWidgetItem([label])
    item.setData(0, _ROLE, _Group(key, favorite))
    item.setData(0, TREE_KEY_ROLE, oriented_key(key, LANDSCAPE))
    return item


def test_action_rects_sit_left_of_the_label_star_nearest():
    content = QRect(60, 0, 140, 24)  # a label indented 60px, leaving room to its left
    star, delete = _action_rects(content)
    assert star.right() <= content.left()      # both sit left of the label...
    assert delete.right() <= star.left()       # ...delete beyond the star
    assert delete.left() >= 0                   # and within the indentation, not off-screen


def _tree_with_leaf(qtbot, *, favorite=False):
    tree = FolderTree(_ROLE)
    qtbot.addWidget(tree)
    # Nest the leaf a few levels deep, as real folders are, so its indentation has
    # room for the icons to its left.
    media = _folder_row("Media", "m")
    wf = _folder_row("Workflow", "m/w")
    model = _folder_row("Model", "m/w/mo")
    leaf = _folder_row("A folder", "m/w/mo/key", favorite=favorite)
    media.addChild(wf)
    wf.addChild(model)
    model.addChild(leaf)
    tree.addTopLevelItem(media)
    tree.expandAll()
    tree.resize(320, 200)
    with qtbot.waitExposed(tree):
        tree.show()
    return tree, leaf


def test_clicking_the_delete_icon_on_a_leaf_emits_delete_clicked(qtbot):
    tree, leaf = _tree_with_leaf(qtbot)
    fired = []
    tree.delete_clicked.connect(fired.append)

    _, delete_rect = _action_rects(tree.visualRect(tree.indexFromItem(leaf)))
    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=delete_rect.center())

    assert fired == ["m/w/mo/key"]


def test_clicking_the_favorite_icon_on_a_leaf_emits_favorite_clicked(qtbot):
    tree, leaf = _tree_with_leaf(qtbot)
    fired = []
    tree.favorite_clicked.connect(fired.append)

    star_rect, _ = _action_rects(tree.visualRect(tree.indexFromItem(leaf)))
    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=star_rect.center())

    assert fired == ["m/w/mo/key"]


def _is_red(color) -> bool:
    return color.red() > color.green() + 50 and color.red() > color.blue() + 50


def test_a_picked_row_can_be_told_to_offer_no_delete(qtbot):
    tree, leaf = _tree_with_leaf(qtbot)
    tree.setCurrentItem(leaf)
    fired = []
    tree.delete_clicked.connect(fired.append)
    _, delete_rect = _action_rects(tree.visualRect(tree.indexFromItem(leaf)))
    qtbot.mouseMove(tree.viewport(), delete_rect.center())
    assert _wears_within(tree, leaf, delete_rect, _is_red)

    tree.offer_delete_on_picked_rows(False)
    shown = _wears_within(tree, leaf, delete_rect, _is_red)
    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=delete_rect.center())

    assert (shown, fired) == (False, [])


def test_a_parent_row_offers_no_actions(qtbot):
    tree, leaf = _tree_with_leaf(qtbot)
    parent = leaf.parent()  # "Model" has a child, so it is a non-leaf
    fired = []
    tree.favorite_clicked.connect(fired.append)
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
    # way to favorite it — and the menu covers the tree, so a collapse on the way in
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
    tree.favorite_clicked.connect(fired.append)
    tree.delete_clicked.connect(fired.append)

    row = tree.visualRect(tree.indexFromItem(leaf))
    label_pos = QPoint(row.center().x(), row.center().y())  # on the label, right of the icons
    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=label_pos)

    assert fired == []
    assert tree.currentItem() is leaf  # a normal click still selects the row


def _shown(item):
    tree = item.treeWidget()
    option = QStyleOptionViewItem()
    tree.itemDelegate().initStyleOption(option, tree.indexFromItem(item))
    return option.text


def test_a_row_leads_with_how_many_items_it_holds(qtbot):
    _tree, leaf = _tree_with_leaf(qtbot)
    leaf.setData(0, COUNT_ROLE, 3)

    assert _shown(leaf) == "(3) A folder"


def test_a_row_holding_nothing_shows_its_name_alone(qtbot):
    _tree, leaf = _tree_with_leaf(qtbot)
    leaf.setData(0, COUNT_ROLE, 0)

    assert _shown(leaf) == "A folder"


# --- picking several folders, and dragging them onto a collecting row ---------

def _collecting_tree(qtbot, takes_item=lambda _row_key, _prompt_id: False,
                     takes_folder=lambda _row_key, _folder_key: True):
    """A tree with a collecting row, the Favorites collection, atop two ordinary folders."""
    tree = FolderTree(_ROLE, takes_item=takes_item, takes_folder=takes_folder)
    qtbot.addWidget(tree)
    collection = QTreeWidgetItem(["Favorites"])
    collection.setData(0, DROP_KEY_ROLE, "__starred__")
    collection.setData(0, TREE_KEY_ROLE, oriented_key("__starred__", LANDSCAPE))
    a = _folder_row("A", "k/a")
    b = _folder_row("B", "k/b")
    for item in (collection, a, b):
        tree.addTopLevelItem(item)
    tree.resize(320, 200)
    with qtbot.waitExposed(tree):
        tree.show()
    return tree, collection, a, b


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
    tree, _collection, a, b = _collecting_tree(qtbot)

    a.setSelected(True)
    b.setSelected(True)

    assert tree.selected_folder_keys() == [oriented_key("k/a", LANDSCAPE),
                                           oriented_key("k/b", LANDSCAPE)]


def test_a_collection_row_holding_no_folder_contributes_no_key(qtbot):
    tree, collection, a, _b = _collecting_tree(qtbot)

    collection.setSelected(True)
    a.setSelected(True)

    assert tree.selected_folder_keys() == [oriented_key("k/a", LANDSCAPE)]


def test_navigating_to_a_row_replaces_the_picked_set(qtbot):
    # setCurrentItem reads the live keyboard modifiers unless told otherwise, so
    # a programmatic move made while Ctrl is held would otherwise ADD the row.
    tree, _collection, a, b = _collecting_tree(qtbot)
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
    tree, collection, a, b = _collecting_tree(qtbot)
    started = _started_drags(monkeypatch)
    dropped = []
    tree.dropped.connect(lambda key, keys, _items: dropped.append((key, keys)))
    tree.setCurrentItem(a)
    b.setSelected(True)

    tree.startDrag(Qt.DropAction.CopyAction)
    (drag,) = started
    _drop_at(tree, collection, drag.mime)

    assert dropped == [("__starred__", [oriented_key("k/a", LANDSCAPE),
                                        oriented_key("k/b", LANDSCAPE)])]


def test_dragging_a_row_outside_the_pick_takes_that_row_alone(qtbot, monkeypatch):
    # The file-manager rule, and what keeps a multi-selection the user has since
    # forgotten about from riding along on the next drag.
    tree, collection, a, b = _collecting_tree(qtbot)
    started = _started_drags(monkeypatch)
    dropped = []
    tree.dropped.connect(lambda key, keys, _items: dropped.append((key, keys)))
    tree.setCurrentItem(a)
    a.setSelected(False)
    b.setSelected(True)  # the pick is elsewhere; the pressed row is A

    tree.startDrag(Qt.DropAction.CopyAction)
    (drag,) = started
    _drop_at(tree, collection, drag.mime)

    assert dropped == [("__starred__", [oriented_key("k/a", LANDSCAPE)])]


def test_a_row_holding_no_folder_starts_no_drag_at_all(qtbot, monkeypatch):
    # A collection gathers folders; it is not one, so there is nothing to pick it up by.
    tree, collection, _a, _b = _collecting_tree(qtbot)
    started = _started_drags(monkeypatch)
    tree.setCurrentItem(collection)

    tree.startDrag(Qt.DropAction.CopyAction)

    assert started == []


def _folder_of_your_own(tree):
    """A row that holds a folder and collects as well, as a custom folder's does."""
    own = _folder_row("Mine", "__custom__/1")
    own.setData(0, DROP_KEY_ROLE, "__custom__/1")
    tree.addTopLevelItem(own)
    return own


def test_a_folder_of_your_own_drags_like_any_folder(qtbot, monkeypatch):
    # Another folder of your own can take it, so its row is picked up as any row is.
    tree, collection, _a, _b = _collecting_tree(qtbot)
    own = _folder_of_your_own(tree)
    started = _started_drags(monkeypatch)
    dropped = []
    tree.dropped.connect(lambda _key, keys, _items: dropped.append(keys))
    tree.setCurrentItem(own)

    tree.startDrag(Qt.DropAction.CopyAction)
    (drag,) = started
    _drop_at(tree, collection, drag.mime)

    assert dropped == [[oriented_key("__custom__/1", LANDSCAPE)]]


def test_a_picked_folder_of_your_own_goes_along_in_a_drag(qtbot, monkeypatch):
    tree, collection, a, _b = _collecting_tree(qtbot)
    own = _folder_of_your_own(tree)
    started = _started_drags(monkeypatch)
    dropped = []
    tree.dropped.connect(lambda _key, keys, _items: dropped.append(keys))
    tree.setCurrentItem(a)
    own.setSelected(True)

    tree.startDrag(Qt.DropAction.CopyAction)
    (drag,) = started
    _drop_at(tree, collection, drag.mime)

    assert dropped == [[oriented_key("k/a", LANDSCAPE), oriented_key("__custom__/1", LANDSCAPE)]]


def test_a_collecting_row_refuses_a_folder_it_does_not_take(qtbot):
    asked = []

    def takes(row_key, folder_key):
        asked.append((row_key, folder_key))
        return folder_key != oriented_key("k/b", LANDSCAPE)

    tree, collection, _a, _b = _collecting_tree(qtbot, takes_folder=takes)
    dropped = []
    tree.dropped.connect(lambda _key, keys, _items: dropped.append(keys))
    refused, taken = _drag([oriented_key("k/b", LANDSCAPE)]), _drag(
        [oriented_key("k/a", LANDSCAPE), oriented_key("k/b", LANDSCAPE)])

    assert not _drag_move_at(tree, collection, refused).isAccepted()
    _drop_at(tree, collection, taken)

    assert dropped == [[oriented_key("k/a", LANDSCAPE)]]
    assert asked[-1] == (oriented_key("__starred__", LANDSCAPE), oriented_key("k/b", LANDSCAPE))


def test_a_folder_of_your_own_dropped_on_itself_is_refused(qtbot):
    tree, _collection, _a, _b = _collecting_tree(qtbot)
    own = _folder_of_your_own(tree)
    dropped = []
    tree.dropped.connect(lambda *landed: dropped.append(landed))
    itself = _drag([own.data(0, TREE_KEY_ROLE)])

    assert not _drag_move_at(tree, own, itself).isAccepted()
    _drop_at(tree, own, itself)

    assert dropped == []


def test_a_folder_dragged_out_tells_every_place_a_drop_can_land(qtbot, monkeypatch):
    tree, _collection, a, _b = _collecting_tree(qtbot)
    _started_drags(monkeypatch)
    heard = HeardDrags()
    tree.setCurrentItem(a)

    tree.startDrag(Qt.DropAction.CopyAction)

    assert [(bytes(mime.data(FOLDER_KEYS_MIME)).decode("utf-8"), source)
            for mime, source in heard.started] == [(oriented_key("k/a", LANDSCAPE), tree)]
    assert heard.ended == 1


# --- the drop style, on the rows a drag would land in ---------------------------

def _style_of(tree, row):
    """The drop style ``row`` wears across the whole width of the list."""
    rect = tree.visualRect(tree.indexFromItem(row))
    return worn(tree.viewport().grab().toImage(),
                QRect(0, rect.top(), tree.viewport().width(), rect.height()))


def _lit_for_a_folder(qtbot):
    """A list Favorites is lit in, for folder A, with B an ordinary folder beside it."""
    tree, favorites, _a, b = _collecting_tree(qtbot)
    tree.setStyleSheet(build_stylesheet())
    mime = _drag([oriented_key("k/a", LANDSCAPE)])
    under_way.started.emit(mime, tree)
    return tree, favorites, b, mime


def test_favorites_lights_up_while_a_folder_it_would_take_is_dragged(qtbot):
    tree, favorites, ordinary, _mime = _lit_for_a_folder(qtbot)

    assert _style_of(tree, favorites) == LIT
    assert _style_of(tree, ordinary) is None


def test_a_folder_of_your_own_lights_for_an_item_it_would_take_and_favorites_does_not(qtbot):
    tree, favorites, _a, _b = _collecting_tree(
        qtbot, takes_item=lambda row_key, _prompt_id: row_key.startswith("__custom__"))
    own = _folder_of_your_own(tree)
    tree.setStyleSheet(build_stylesheet())
    mime = generation_mime("p1")

    under_way.started.emit(mime, None)

    assert _style_of(tree, own) == LIT
    assert _style_of(tree, favorites) is None


def test_the_row_under_the_drag_lights_one_step_lighter(qtbot):
    tree, favorites, _ordinary, mime = _lit_for_a_folder(qtbot)

    _drag_move_at(tree, favorites, mime)

    assert _style_of(tree, favorites) == AIMED


def test_a_drag_leaving_the_list_leaves_the_row_it_was_over_only_lit(qtbot):
    tree, favorites, _ordinary, mime = _lit_for_a_folder(qtbot)
    _drag_move_at(tree, favorites, mime)

    tree.dragLeaveEvent(QDragLeaveEvent())

    assert _style_of(tree, favorites) == LIT


def test_a_drag_let_go_over_a_row_leaves_it_dark_and_not_under_the_next_drag(qtbot):
    tree, favorites, _ordinary, mime = _lit_for_a_folder(qtbot)
    _drag_move_at(tree, favorites, mime)
    _drop_at(tree, favorites, mime)
    under_way.ended.emit()
    assert _style_of(tree, favorites) is None

    under_way.started.emit(mime, tree)

    assert _style_of(tree, favorites) == LIT


def test_dropping_folders_on_a_collecting_row_reports_them(qtbot):
    tree, collection, a, b = _collecting_tree(qtbot)
    dropped = []
    tree.dropped.connect(lambda key, keys, _items: dropped.append((key, keys)))

    mime = _drag(["k/a", "k/b"])

    event = _drop_at(tree, collection, mime)

    assert dropped == [("__starred__", ["k/a", "k/b"])]
    assert event.isAccepted()
    # The tree's shape comes from the generations, so nothing was reparented.
    assert tree.topLevelItemCount() == 3
    assert collection.childCount() == 0


def test_an_ordinary_folder_refuses_a_drop(qtbot):
    tree, _collection, a, b = _collecting_tree(qtbot)
    dropped = []
    tree.dropped.connect(lambda key, keys, _items: dropped.append((key, keys)))

    mime = _drag(["k/a"])

    assert not _drag_move_at(tree, b, mime).isAccepted()
    _drop_at(tree, b, mime)

    assert dropped == []


def test_a_collecting_row_refuses_a_drop_of_only_itself(qtbot):
    tree, collection, _a, _b = _collecting_tree(qtbot)
    dropped = []
    tree.dropped.connect(lambda key, keys, _items: dropped.append((key, keys)))

    mime = _drag(["__starred__"])

    assert not _drag_move_at(tree, collection, mime).isAccepted()
    _drop_at(tree, collection, mime)

    assert dropped == []


def test_a_drop_carrying_something_other_than_folders_is_ignored(qtbot):
    tree, collection, _a, _b = _collecting_tree(qtbot)
    dropped = []
    tree.dropped.connect(lambda key, keys, _items: dropped.append((key, keys)))
    text = QMimeData()
    text.setText("k/a")  # a plain-text drag from anywhere else

    assert not _drag_move_at(tree, collection, text).isAccepted()
    _drop_at(tree, collection, text)

    assert dropped == []


def test_an_item_dropped_on_a_collecting_row_that_takes_it_is_reported(qtbot):
    asked = []

    def takes(row_key, prompt_id):
        asked.append((row_key, prompt_id))
        return True

    tree, collection, _a, _b = _collecting_tree(qtbot, takes_item=takes)
    dropped = []
    tree.dropped.connect(lambda key, keys, items: dropped.append((key, keys, items)))
    mime = generation_mime("p1")

    assert _drag_move_at(tree, collection, mime).isAccepted()
    _drop_at(tree, collection, mime)

    assert dropped == [("__starred__", [], ["p1"])]
    assert asked[-1] == (oriented_key("__starred__", LANDSCAPE), "p1")


def test_an_item_a_collecting_row_does_not_take_is_refused(qtbot):
    tree, collection, _a, _b = _collecting_tree(qtbot)  # takes no item
    dropped = []
    tree.dropped.connect(lambda *landed: dropped.append(landed))
    mime = generation_mime("p1")

    assert not _drag_move_at(tree, collection, mime).isAccepted()
    _drop_at(tree, collection, mime)

    assert dropped == []


def test_an_ordinary_folder_refuses_an_item(qtbot):
    # Only a collecting row is asked; a derived folder's contents are its settings'.
    tree, _collection, a, _b = _collecting_tree(qtbot, takes_item=lambda *_: True)
    dropped = []
    tree.dropped.connect(lambda *landed: dropped.append(landed))
    mime = generation_mime("p1")

    assert not _drag_move_at(tree, a, mime).isAccepted()
    _drop_at(tree, a, mime)

    assert dropped == []


def test_an_item_drag_is_let_into_the_tree(qtbot):
    # Refused at the door, it would never be offered a row to land on.
    tree, collection, _a, _b = _collecting_tree(qtbot)
    mime = generation_mime("p1")
    pos = tree.visualRect(tree.indexFromItem(collection)).center()
    enter = QDragEnterEvent(pos, Qt.DropAction.CopyAction, mime,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)

    tree.dragEnterEvent(enter)

    assert enter.isAccepted()


def _too_long_for_its_height(qtbot):
    tree = FolderTree(_ROLE)
    qtbot.addWidget(tree)
    for n in range(100):
        tree.addTopLevelItem(_folder_row(f"Folder {n}", f"k/{n}"))
    tree.resize(200, 150)
    with qtbot.waitExposed(tree):
        tree.show()
    return tree, tree.verticalScrollBar()


def _held_at(spot, mime):
    return QDragMoveEvent(spot, Qt.DropAction.CopyAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


def test_a_drag_held_at_the_top_edge_jumps_the_tree_to_its_top(qtbot):
    # Where the folders of your own are, and almost always where the drag is going.
    tree, bar = _too_long_for_its_height(qtbot)
    bar.setValue(bar.maximum())
    mime = generation_mime("p1")

    tree.dragMoveEvent(_held_at(QPoint(40, 2), mime))

    assert bar.value() == 0


def test_a_drag_held_at_the_bottom_edge_scrolls_the_tree_down(qtbot):
    tree, bar = _too_long_for_its_height(qtbot)
    mime = generation_mime("p1")

    tree.dragMoveEvent(_held_at(QPoint(40, tree.viewport().height() - 2), mime))

    qtbot.waitUntil(lambda: bar.value() > 0, timeout=3000)


def test_letting_a_drag_go_at_the_edge_stops_the_scrolling(qtbot):
    tree, bar = _too_long_for_its_height(qtbot)
    foot = QPoint(40, tree.viewport().height() - 2)
    mime = generation_mime("p1")
    tree.dragMoveEvent(_held_at(foot, mime))
    qtbot.waitUntil(lambda: bar.value() > 0, timeout=3000)

    tree.dropEvent(QDropEvent(QPointF(foot), Qt.DropAction.CopyAction, mime,
                              Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    settled = bar.value()
    qtbot.wait(500)

    assert bar.value() == settled


def _is_blue(color) -> bool:
    """Whether a pixel carries the family's blue, rather than a gray or the
    colored edge a letter picks up where it is drawn against one."""
    return (color.blue() > color.red() + 50
            and color.blue() > color.green() + 30
            and color.blue() > 120)


def _row_pixels(tree, item) -> list:
    """Every pixel of the row ``item`` is drawn on, as ``(x, color)`` pairs."""
    image = tree.viewport().grab().toImage()
    row = tree.visualRect(tree.indexFromItem(item))
    return [(x, image.pixelColor(x, y))
            for y in range(row.top(), row.top() + row.height())
            for x in range(tree.viewport().width())]


def _wears_within(tree, item, columns: QRect, ink) -> bool:
    return any(ink(color) for x, color in _row_pixels(tree, item)
               if columns.left() <= x <= columns.right())


def test_the_picked_folder_is_marked_by_its_blue_ground_alone(qtbot):
    # The platform draws a picked row an accent bar down its left edge on top of
    # that ground -- straight through the mark the row leads with, and saying
    # nothing the ground has not already said.
    tree, leaf = _tree_with_leaf(qtbot)
    tree.setStyleSheet(build_stylesheet())
    leaf.setText(0, "")
    tree.setCurrentItem(leaf)

    assert all(color == BLUE for _x, color in _row_pixels(tree, leaf))


def test_a_folder_lately_worked_in_wears_a_mark_at_the_start_of_its_row(qtbot):
    tree, leaf = _tree_with_leaf(qtbot)
    assert not any(_is_blue(color) for _x, color in _row_pixels(tree, leaf))

    leaf.setData(0, RECENT_ROLE, True)

    marked = {x for x, color in _row_pixels(tree, leaf) if _is_blue(color)}
    _star, delete = _action_rects(tree.visualRect(tree.indexFromItem(leaf)))
    assert marked                        # the mark is drawn...
    assert max(marked) < delete.left()   # ...at the pane's own edge, clear of the
                                         # row's actions however deep it sits


def _is_white(color) -> bool:
    return min(color.red(), color.green(), color.blue()) > 200


def test_a_picked_folder_lately_worked_in_keeps_its_mark_drawn_white(qtbot):
    tree, leaf = _tree_with_leaf(qtbot)
    tree.setStyleSheet(build_stylesheet())
    leaf.setData(0, RECENT_ROLE, True)
    tree.setCurrentItem(leaf)

    _star, delete = _action_rects(tree.visualRect(tree.indexFromItem(leaf)))
    assert any(_is_white(color) for x, color in _row_pixels(tree, leaf) if x < delete.left())


def _is_green(color) -> bool:
    return (color.green() > color.red() + 50
            and color.green() > color.blue() + 50)


def test_a_favorited_folder_wears_a_green_star_with_the_mouse_elsewhere(qtbot):
    tree, leaf = _tree_with_leaf(qtbot, favorite=True)
    star, _delete = _action_rects(tree.visualRect(tree.indexFromItem(leaf)))

    assert _wears_within(tree, leaf, star, _is_green)


def test_a_picked_favorited_folders_star_is_ringed_in_white(qtbot):
    tree, leaf = _tree_with_leaf(qtbot, favorite=True)
    tree.setStyleSheet(build_stylesheet())
    star, _delete = _action_rects(tree.visualRect(tree.indexFromItem(leaf)))
    assert not _wears_within(tree, leaf, star, _is_white)

    tree.setCurrentItem(leaf)

    assert _wears_within(tree, leaf, star, _is_white)
    assert _wears_within(tree, leaf, star, _is_green)


def _laid_out(tree, item, element) -> QRect:
    index = tree.indexFromItem(item)
    option = QStyleOptionViewItem()
    tree.initViewItemOption(option)
    option.rect = tree.visualRect(index)
    tree.itemDelegate().initStyleOption(option, index)
    return tree.style().subElementRect(element, option, tree)


def _tree_with_a_collection(qtbot, which=LATEST_KEY):
    """A collection row under a workflow folder, under All, the way a side lays them out."""
    tree = FolderTree(_ROLE)
    qtbot.addWidget(tree)
    top = _folder_row("All", "all")
    folder = _folder_row("Workflow", "wf")
    folder.setIcon(0, icons.level_badge_icon("workflow"))
    collection = QTreeWidgetItem([COLLECTION_LABELS[which]])
    collection.setIcon(0, icons.collection_icon(which))
    folder.addChild(collection)
    top.addChild(folder)
    tree.addTopLevelItem(top)
    tree.expandAll()
    with qtbot.waitExposed(tree):
        tree.show()
    return tree, collection


def test_a_picked_collection_row_is_blue_from_its_mark_to_its_name(qtbot):
    tree, collection = _tree_with_a_collection(qtbot)
    tree.setStyleSheet(build_stylesheet())
    tree.setCurrentItem(collection)

    mark = _laid_out(tree, collection, QStyle.SubElement.SE_ItemViewItemDecoration)
    name = _laid_out(tree, collection, QStyle.SubElement.SE_ItemViewItemText)
    middle = tree.visualRect(tree.indexFromItem(collection)).center().y()
    image = tree.viewport().grab().toImage()
    between = [image.pixelColor(x, middle).name() for x in range(mark.right() + 1, name.left())]
    assert between and set(between) == {BLUE.name()}


def test_a_picked_favorites_rows_star_is_ringed_in_white(qtbot):
    tree, favorites = _tree_with_a_collection(qtbot, FAVORITES_KEY)
    tree.setStyleSheet(build_stylesheet())
    mark = _laid_out(tree, favorites, QStyle.SubElement.SE_ItemViewItemDecoration)
    assert not _wears_within(tree, favorites, mark, _is_white)

    tree.setCurrentItem(favorites)

    assert _wears_within(tree, favorites, mark, _is_white)
    assert _wears_within(tree, favorites, mark, _is_green)


def test_a_folder_of_your_own_offers_no_star_or_delete_beside_its_mark(qtbot):
    tree = FolderTree(_ROLE)
    qtbot.addWidget(tree)
    own = _folder_row("Keepers", "__custom__/1")
    own.setIcon(0, icons.custom_folder_icon())
    own.setData(0, DROP_KEY_ROLE, "__custom__/1")
    tree.addTopLevelItem(own)
    tree.show()
    clicked = []
    tree.favorite_clicked.connect(clicked.append)
    tree.delete_clicked.connect(clicked.append)
    star, delete = _action_rects(tree.visualRect(tree.indexFromItem(own)))

    for spot in (star.center(), delete.center()):
        qtbot.mouseMove(tree.viewport(), spot)
        qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=spot)

    assert clicked == []
    assert tree._hover_key is None


def test_folders_dragged_from_the_other_half_land_nowhere(qtbot):
    tree, collection, a, _b = _collecting_tree(qtbot)
    other_half = FolderTree(_ROLE)
    qtbot.addWidget(other_half)
    mime = QMimeData()
    mime.setData(FOLDER_KEYS_MIME, a.data(0, TREE_KEY_ROLE).encode("utf-8"))
    dropped = []
    tree.dropped.connect(lambda _target, keys, _items: dropped.append(keys))
    pos = QPointF(tree.visualRect(tree.indexFromItem(collection)).center())
    move = QDragMoveEvent(pos.toPoint(), Qt.DropAction.CopyAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    drop = QDropEvent(pos, Qt.DropAction.CopyAction, mime,
                      Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    for event in (move, drop):
        event.source = lambda: other_half

    tree.dragMoveEvent(move)
    tree.dropEvent(drop)

    assert not move.isAccepted()
    assert dropped == []
