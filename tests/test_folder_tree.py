from __future__ import annotations

import pytest
from PyQt6.QtCore import QMimeData, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import (
    QContextMenuEvent,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QStyle,
    QStyleOptionViewItem,
    QTreeWidgetItem,
)
from shared_ui.colors import BLUE, BORDER_SUBTLE

from origenerator.gallery.collection import COLLECTION_LABELS, FAVORITES_KEY, LATEST_KEY
from origenerator.gallery.shapes import LANDSCAPE
from origenerator.gallery.tree import ALL_KEY
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
from origenerator.item_shape import shaped_key
from tests.drop_style_seen import worn
from tests.heard_drags import HeardDrags

_ROLE = Qt.ItemDataRole.UserRole


class _Group:
    def __init__(self, key, favorite=False):
        self.key = key
        self.favorite = favorite


def _folder_row(label, key, favorite=False):
    item = QTreeWidgetItem([label])
    item.setData(0, _ROLE, _Group(key, favorite))
    item.setData(0, TREE_KEY_ROLE, shaped_key(key, LANDSCAPE))
    return item


def test_action_rects_sit_left_of_the_label_star_nearest():
    content = QRect(60, 0, 140, 24)
    star, delete = _action_rects(content)
    assert star.right() <= content.left()
    assert delete.right() <= star.left()
    assert delete.left() >= 0


def _tree_with_leaf(qtbot, *, favorite=False):
    tree = FolderTree(_ROLE)
    qtbot.addWidget(tree)
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
    parent = leaf.parent()
    fired = []
    tree.favorite_clicked.connect(fired.append)
    tree.delete_clicked.connect(fired.append)

    star_rect, delete_rect = _action_rects(tree.visualRect(tree.indexFromItem(parent)))
    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=star_rect.center())
    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=delete_rect.center())

    assert fired == []
    assert tree.currentItem() is parent


def _caret_pos(tree, item):
    row = tree.visualRect(tree.indexFromItem(item))
    return QPoint(row.left() - tree.indentation() // 2, row.center().y())


def test_right_clicking_a_folder_leaves_its_caret_alone(qtbot):
    tree, leaf = _tree_with_leaf(qtbot)
    parent = leaf.parent()

    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.RightButton,
                     pos=_caret_pos(tree, parent))

    assert parent.isExpanded()
    assert tree.currentItem() is parent


def test_left_clicking_the_caret_still_collapses_the_folder(qtbot):
    tree, leaf = _tree_with_leaf(qtbot)
    parent = leaf.parent()

    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton,
                     pos=_caret_pos(tree, parent))

    assert not parent.isExpanded()


def test_hovering_tracks_the_leaf_under_the_mouse(qtbot):
    tree, leaf = _tree_with_leaf(qtbot)

    qtbot.mouseMove(tree.viewport(), pos=tree.visualRect(tree.indexFromItem(leaf)).center())
    assert tree._hover_key == shaped_key("m/w/mo/key", LANDSCAPE)

    parent = leaf.parent()
    qtbot.mouseMove(tree.viewport(), pos=tree.visualRect(tree.indexFromItem(parent)).center())
    assert tree._hover_key is None


def test_clicking_a_leafs_label_still_selects_without_firing_actions(qtbot):
    tree, leaf = _tree_with_leaf(qtbot)
    fired = []
    tree.favorite_clicked.connect(fired.append)
    tree.delete_clicked.connect(fired.append)

    row = tree.visualRect(tree.indexFromItem(leaf))
    label_pos = QPoint(row.center().x(), row.center().y())
    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=label_pos)

    assert fired == []
    assert tree.currentItem() is leaf


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


def _collecting_tree(qtbot, takes_item=lambda _row_key, _prompt_id: False,
                     takes_folder=lambda _row_key, _folder_key: True):
    tree = FolderTree(_ROLE, takes_item=takes_item, takes_folder=takes_folder)
    qtbot.addWidget(tree)
    collection = QTreeWidgetItem(["Favorites"])
    collection.setData(0, DROP_KEY_ROLE, "__starred__")
    collection.setData(0, TREE_KEY_ROLE, shaped_key("__starred__", LANDSCAPE))
    a = _folder_row("A", "k/a")
    b = _folder_row("B", "k/b")
    for item in (collection, a, b):
        tree.addTopLevelItem(item)
    tree.resize(320, 200)
    with qtbot.waitExposed(tree):
        tree.show()
    return tree, collection, a, b


def _drag(keys):
    # A synthetic drop event does not own its QMimeData, so keep it in a local of your own
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

    assert tree.selected_folder_keys() == [shaped_key("k/a", LANDSCAPE),
                                           shaped_key("k/b", LANDSCAPE)]


def test_a_collection_row_holding_no_folder_contributes_no_key(qtbot):
    tree, collection, a, _b = _collecting_tree(qtbot)

    collection.setSelected(True)
    a.setSelected(True)

    assert tree.selected_folder_keys() == [shaped_key("k/a", LANDSCAPE)]


def test_navigating_to_a_row_replaces_the_picked_set(qtbot):
    tree, _collection, a, b = _collecting_tree(qtbot)
    a.setSelected(True)
    b.setSelected(True)

    tree.setCurrentItem(a)

    assert tree.selected_folder_keys() == [shaped_key("k/a", LANDSCAPE)]


def _started_drags(monkeypatch):
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
    tree, collection, a, b = _collecting_tree(qtbot)
    started = _started_drags(monkeypatch)
    dropped = []
    tree.dropped.connect(lambda key, keys, _items: dropped.append((key, keys)))
    tree.setCurrentItem(a)
    b.setSelected(True)

    tree.startDrag(Qt.DropAction.CopyAction)
    (drag,) = started
    _drop_at(tree, collection, drag.mime)

    assert dropped == [("__starred__", [shaped_key("k/a", LANDSCAPE),
                                        shaped_key("k/b", LANDSCAPE)])]


def test_dragging_a_row_outside_the_pick_takes_that_row_alone(qtbot, monkeypatch):
    tree, collection, a, b = _collecting_tree(qtbot)
    started = _started_drags(monkeypatch)
    dropped = []
    tree.dropped.connect(lambda key, keys, _items: dropped.append((key, keys)))
    tree.setCurrentItem(a)
    a.setSelected(False)
    b.setSelected(True)

    tree.startDrag(Qt.DropAction.CopyAction)
    (drag,) = started
    _drop_at(tree, collection, drag.mime)

    assert dropped == [("__starred__", [shaped_key("k/a", LANDSCAPE)])]


def test_a_row_holding_no_folder_starts_no_drag_at_all(qtbot, monkeypatch):
    tree, collection, _a, _b = _collecting_tree(qtbot)
    started = _started_drags(monkeypatch)
    tree.setCurrentItem(collection)

    tree.startDrag(Qt.DropAction.CopyAction)

    assert started == []


def _folder_of_your_own(tree):
    own = _folder_row("Mine", "__custom__/1")
    own.setData(0, DROP_KEY_ROLE, "__custom__/1")
    tree.addTopLevelItem(own)
    return own


def test_a_folder_of_your_own_drags_like_any_folder(qtbot, monkeypatch):
    tree, collection, _a, _b = _collecting_tree(qtbot)
    own = _folder_of_your_own(tree)
    started = _started_drags(monkeypatch)
    dropped = []
    tree.dropped.connect(lambda _key, keys, _items: dropped.append(keys))
    tree.setCurrentItem(own)

    tree.startDrag(Qt.DropAction.CopyAction)
    (drag,) = started
    _drop_at(tree, collection, drag.mime)

    assert dropped == [[shaped_key("__custom__/1", LANDSCAPE)]]


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

    assert dropped == [[shaped_key("k/a", LANDSCAPE), shaped_key("__custom__/1", LANDSCAPE)]]


def test_a_collecting_row_refuses_a_folder_it_does_not_take(qtbot):
    asked = []

    def takes(row_key, folder_key):
        asked.append((row_key, folder_key))
        return folder_key != shaped_key("k/b", LANDSCAPE)

    tree, collection, _a, _b = _collecting_tree(qtbot, takes_folder=takes)
    dropped = []
    tree.dropped.connect(lambda _key, keys, _items: dropped.append(keys))
    refused, taken = _drag([shaped_key("k/b", LANDSCAPE)]), _drag(
        [shaped_key("k/a", LANDSCAPE), shaped_key("k/b", LANDSCAPE)])

    assert not _drag_move_at(tree, collection, refused).isAccepted()
    _drop_at(tree, collection, taken)

    assert dropped == [[shaped_key("k/a", LANDSCAPE)]]
    assert asked[-1] == (shaped_key("__starred__", LANDSCAPE), shaped_key("k/b", LANDSCAPE))


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
            for mime, source in heard.started] == [(shaped_key("k/a", LANDSCAPE), tree)]
    assert heard.ended == 1


def _style_of(tree, row):
    rect = tree.visualRect(tree.indexFromItem(row))
    return worn(tree.viewport().grab().toImage(),
                QRect(0, rect.top(), tree.viewport().width(), rect.height()))


def _lit_for_a_folder(qtbot):
    tree, favorites, _a, b = _collecting_tree(qtbot)
    tree.setStyleSheet(build_stylesheet())
    mime = _drag([shaped_key("k/a", LANDSCAPE)])
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
    tree, collection, _a, _b = _collecting_tree(qtbot)
    dropped = []
    tree.dropped.connect(lambda key, keys, _items: dropped.append((key, keys)))

    mime = _drag(["k/a", "k/b"])

    event = _drop_at(tree, collection, mime)

    assert dropped == [("__starred__", ["k/a", "k/b"])]
    assert event.isAccepted()
    assert tree.topLevelItemCount() == 3
    assert collection.childCount() == 0


def test_an_ordinary_folder_refuses_a_drop(qtbot):
    tree, _collection, _a, b = _collecting_tree(qtbot)
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
    text.setText("k/a")

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
    assert asked[-1] == (shaped_key("__starred__", LANDSCAPE), "p1")


def test_an_item_a_collecting_row_does_not_take_is_refused(qtbot):
    tree, collection, _a, _b = _collecting_tree(qtbot)
    dropped = []
    tree.dropped.connect(lambda *landed: dropped.append(landed))
    mime = generation_mime("p1")

    assert not _drag_move_at(tree, collection, mime).isAccepted()
    _drop_at(tree, collection, mime)

    assert dropped == []


def test_an_ordinary_folder_refuses_an_item(qtbot):
    tree, _collection, a, _b = _collecting_tree(qtbot, takes_item=lambda *_: True)
    dropped = []
    tree.dropped.connect(lambda *landed: dropped.append(landed))
    mime = generation_mime("p1")

    assert not _drag_move_at(tree, a, mime).isAccepted()
    _drop_at(tree, a, mime)

    assert dropped == []


def test_an_item_drag_is_let_into_the_tree(qtbot):
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
    return (color.blue() > color.red() + 50
            and color.blue() > color.green() + 30
            and color.blue() > 120)


def _row_pixels(tree, item) -> list:
    image = tree.viewport().grab().toImage()
    row = tree.visualRect(tree.indexFromItem(item))
    return [(x, image.pixelColor(x, y))
            for y in range(row.top(), row.top() + row.height())
            for x in range(tree.viewport().width())]


def _wears_within(tree, item, columns: QRect, ink) -> bool:
    return any(ink(color) for x, color in _row_pixels(tree, item)
               if columns.left() <= x <= columns.right())


def test_the_picked_folder_is_marked_by_its_blue_ground_alone(qtbot):
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
    assert marked
    assert max(marked) < delete.left()


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
    tree = FolderTree(_ROLE)
    qtbot.addWidget(tree)
    top = _folder_row("All", "all")
    folder = _folder_row("Workflow", "wf")
    folder.setIcon(0, icons.toc_initial_icon("workflow"))
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
    assert between
    assert set(between) == {BLUE.name()}


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
    own.setIcon(0, icons.custom_collection_icon())
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


def _long_tree(qtbot):
    tree = FolderTree(_ROLE)
    qtbot.addWidget(tree)
    every = _folder_row("All", ALL_KEY)
    tree.addTopLevelItem(every)
    rows = {}
    for name in ("a", "b"):
        folder = _folder_row(name.upper(), name)
        every.addChild(folder)
        rows[name] = folder
        inner = _folder_row(f"{name.upper()} inner", f"{name}/i")
        folder.addChild(inner)
        rows[f"{name}/i"] = inner
        for n in range(30):
            leaf = _folder_row(f"{name} leaf {n}", f"{name}/i/{n}")
            inner.addChild(leaf)
            rows[f"{name}/i/{n}"] = leaf
    tree.expandAll()
    tree.resize(320, 200)
    with qtbot.waitExposed(tree):
        tree.show()
    return tree, rows


def _scroll_to_the_top(tree, row):
    tree.scrollToItem(row, QAbstractItemView.ScrollHint.PositionAtTop)


def test_scrolled_into_a_folder_its_folders_stay_frozen_at_the_top_without_all(qtbot):
    tree, rows = _long_tree(qtbot)
    _scroll_to_the_top(tree, rows["a/i/3"])

    assert tree.frozen_rows() == [rows["a"], rows["a/i"]]


def test_a_folder_whose_rows_have_scrolled_past_stays_frozen_no_longer(qtbot):
    tree, rows = _long_tree(qtbot)
    _scroll_to_the_top(tree, rows["a/i/29"])

    assert tree.frozen_rows() == []


def test_at_the_top_nothing_is_frozen(qtbot):
    tree, _rows = _long_tree(qtbot)

    assert tree.frozen_rows() == []


def _strip(tree, top, height):
    image = tree.viewport().grab().toImage()
    return [image.pixelColor(x, y).name() for y in range(top, top + height)
            for x in range(tree.viewport().width())]


@pytest.mark.parametrize("picked", [False, True])
def test_a_frozen_folder_looks_as_it_does_in_its_own_place(qtbot, picked):
    tree, rows = _long_tree(qtbot)
    tree.setStyleSheet(build_stylesheet())
    if picked:
        tree.setCurrentItem(rows["a/i"])
    _scroll_to_the_top(tree, rows["a"])
    place = tree.visualItemRect(rows["a/i"])
    in_place = _strip(tree, place.top(), place.height())

    _scroll_to_the_top(tree, rows["a/i/3"])
    frozen_top = tree.visualItemRect(rows["a"]).height()

    assert _strip(tree, frozen_top, place.height()) == in_place


def test_clicking_a_frozen_folder_picks_it_and_scrolls_up_to_where_it_sits(qtbot):
    tree, rows = _long_tree(qtbot)
    _scroll_to_the_top(tree, rows["a/i/3"])
    first_height = tree.visualItemRect(rows["a"]).height()

    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton,
                     pos=QPoint(100, first_height + 2))

    shown = tree.visualItemRect(rows["a/i"]).top()
    assert (tree.currentItem(), rows["a/i"] in tree.frozen_rows(), shown >= 0) == (
        rows["a/i"], False, True)


def test_a_click_on_a_frozen_folder_that_moves_a_little_picks_that_folder_alone(qtbot):
    tree, rows = _long_tree(qtbot)
    tree.setCurrentItem(rows["a/i/1"])
    qtbot.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton,
                     pos=tree.visualItemRect(rows["a/i/1"]).center())
    _scroll_to_the_top(tree, rows["a/i/8"])
    at = QPoint(100, 2)

    qtbot.mousePress(tree.viewport(), Qt.MouseButton.LeftButton, pos=at)
    qtbot.mouseMove(tree.viewport(), at + QPoint(3, 1))
    qtbot.mouseRelease(tree.viewport(), Qt.MouseButton.LeftButton, pos=at + QPoint(3, 1))

    assert tree.selectedItems() == [rows["a"]]


def test_right_clicking_a_frozen_folder_offers_no_menu_for_the_row_under_it(qtbot):
    tree, rows = _long_tree(qtbot)
    tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    asked = []
    tree.customContextMenuRequested.connect(asked.append)
    _scroll_to_the_top(tree, rows["a/i/3"])

    at = QPoint(100, 2)
    QApplication.sendEvent(tree.viewport(), QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, at, tree.viewport().mapToGlobal(at)))

    assert asked == []


def test_a_gray_line_runs_under_the_frozen_folders(qtbot):
    tree, rows = _long_tree(qtbot)
    tree.setStyleSheet(build_stylesheet())
    _scroll_to_the_top(tree, rows["a/i/3"])
    under = sum(tree.visualItemRect(row).height() for row in tree.frozen_rows())

    assert set(_strip(tree, under, 1)) == {BORDER_SUBTLE.name()}


def test_the_picked_folder_and_its_folders_stay_frozen_once_scrolled_past_in_list_order(qtbot):
    tree, rows = _long_tree(qtbot)
    tree.setCurrentItem(rows["a/i/2"])
    _scroll_to_the_top(tree, rows["b/i/3"])

    assert tree.frozen_rows() == [rows["a"], rows["a/i"], rows["a/i/2"], rows["b"], rows["b/i"]]


def test_the_picked_folder_still_ahead_in_the_list_is_not_frozen(qtbot):
    tree, rows = _long_tree(qtbot)
    tree.setCurrentItem(rows["b/i/20"])
    _scroll_to_the_top(tree, rows["a/i/3"])

    assert tree.frozen_rows() == [rows["a"], rows["a/i"]]
