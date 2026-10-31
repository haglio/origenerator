from __future__ import annotations

import pytest
from PyQt6.QtCore import (
    QMimeData,
    QPoint,
    QPointF,
    Qt,
)
from PyQt6.QtGui import (
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
)
from PyQt6.QtWidgets import (
    QApplication,
)

from origenerator import (
    gallery,
)
from origenerator.gallery.collection import (
    FAVORITES_KEY,
)
from origenerator.gallery.sides import LANDSCAPE, PORTRAIT
from origenerator.gui import gallery_view as gallery_view_module
from origenerator.gui.drags import under_way
from origenerator.gui.drop_style import LIT
from origenerator.gui.folder_tile import FolderTile
from origenerator.gui.folder_tree import FOLDER_KEYS_MIME, TREE_KEY_ROLE, _action_rects
from origenerator.gui.gallery_view import _GROUP_ROLE, GalleryView
from origenerator.gui.generation_drag import generation_mime
from origenerator.gui.item_tile import ItemTile
from origenerator.gui.stylesheet import build_stylesheet
from origenerator.gui.thumbnail_widget import ThumbnailWidget
from origenerator.orientation import oriented_key
from tests import gestures
from tests.drop_style_seen import worn
from tests.gallery_view_support import (
    FakeActions,
    FakeDB,
    _alls,
    _answer_menu,
    _at,
    _click_beside_the_mark_of,
    _image,
    _image_workflow,
    _key,
    _make_folder,
    _menu_labels,
    _pick,
    _row,
    _side,
    _subs,
    _tall_on_screen,
    _tile_kinds_in_order,
    _top_level,
    _tree_menu,
    _two_leaf_view,
)
from tests.test_folder_tree import _shown

pytestmark = pytest.mark.usefixtures("_stub_preview_resolution")


# --- folders the user composes: multi-select, group, drop, remove -------------


def test_picking_several_folders_shows_them_together_as_one_folder(qtbot):
    view, cat, dog = _two_leaf_view(qtbot)

    _pick(view, cat, dog)

    assert view._gallery_pane._listed_folders == [cat, dog]  # both, as tiles
    assert "2 folders" in view._folder_path.display_text()
    assert not view._buttons.group.isHidden()  # offering to save the grouping


def test_the_slideshow_of_a_multi_selection_plays_every_picked_folder(qtbot):
    view, cat, dog = _two_leaf_view(qtbot)

    _pick(view, cat, dog)

    assert {r["prompt_id"] for r in view.rows_to_play()} == {"i1", "i2"}


def test_dropping_back_to_one_folder_returns_to_that_folder(qtbot):
    view, cat, dog = _two_leaf_view(qtbot)
    _pick(view, cat, dog)

    view._tree.setCurrentItem(view._tree_item_for(cat))  # a plain click on one row

    assert view._selection_group is None
    assert view.listed_prompt_ids() == ["i1"]  # its own thumbnails, not tiles
    assert view._buttons.group.isHidden()


def test_delete_takes_every_picked_folder_not_only_the_current_one(qtbot):
    actions = FakeActions()
    view, cat, dog = _two_leaf_view(qtbot, actions=actions)
    _pick(view, cat, dog)
    asked = []
    view._confirm = lambda text: asked.append(text) or True

    assert view._buttons.delete.toolTip() == "Delete 2 folders"
    view._buttons.delete.click()

    assert asked == ["Delete 2 folders and their 2 items?"]
    assert {r["prompt_id"] for r in actions.deleted[0]} == {"i1", "i2"}


def test_grouping_the_picked_folders_makes_a_named_folder_and_opens_it(qtbot, monkeypatch):
    view, cat, dog = _two_leaf_view(qtbot)
    _pick(view, cat, dog)
    monkeypatch.setattr(gallery_view_module.QInputDialog, "getText",
                        staticmethod(lambda *a, **kw: ("Favorites", True)))

    view._group_selection()

    (record,) = view._db.list_custom_collections()
    assert record["name"] == "Favorites"
    assert record["folders"] == [cat, dog]
    # ...and the view has landed on it, showing what it gathered.
    assert _top_level(view._tree)["Favorites"] is view._tree.currentItem()
    assert view._gallery_pane._listed_folders == [cat, dog]


def test_grouping_picked_folders_takes_a_custom_folder_among_them(qtbot, monkeypatch):
    view, cat, dog = _two_leaf_view(qtbot)
    mine = gallery.custom_collection_key(_make_folder(view, "Mine", [dog]))
    _pick(view, mine, cat)
    monkeypatch.setattr(gallery_view_module.QInputDialog, "getText",
                        staticmethod(lambda *a, **kw: ("Both", True)))

    view._group_selection()

    record = next(r for r in view._db.list_custom_collections() if r["name"] == "Both")
    assert sorted(record["folders"]) == sorted([mine, cat])


def test_declining_the_name_prompt_makes_no_folder(qtbot, monkeypatch):
    view, cat, dog = _two_leaf_view(qtbot)
    _pick(view, cat, dog)
    monkeypatch.setattr(gallery_view_module.QInputDialog, "getText",
                        staticmethod(lambda *a, **kw: ("", False)))

    view._group_selection()

    assert view._db.list_custom_collections() == []


def test_a_folder_of_your_own_is_drawn_only_on_the_side_it_was_made_on(qtbot):
    view, _cat, _dog = _two_leaf_view(qtbot)
    view._db.create_custom_folder("Keepers", side=PORTRAIT)

    view.refresh()

    assert "Keepers" in _top_level(view._tree, PORTRAIT)
    assert "Keepers" not in _top_level(view._tree, LANDSCAPE)


def test_a_custom_folder_gets_its_own_row_and_shows_what_it_holds(qtbot):
    view, cat, _dog = _two_leaf_view(qtbot)
    _make_folder(view, "Favorites", [cat])

    row = _top_level(view._tree)["Favorites"]
    view._tree.setCurrentItem(row)

    assert [_key(child) for child in _subs(row)] == [cat]
    assert view._gallery_pane._listed_folders == [cat]
    assert {r["prompt_id"] for r in view.rows_to_play()} == {"i1"}


def test_a_custom_folder_shows_the_items_it_holds_ahead_of_its_folders(qtbot):
    view, cat, dog = _two_leaf_view(qtbot)
    folder_id = _make_folder(view, "Mine", [dog])
    view._db.add_items_to_custom_collection(folder_id, ["i1"])
    view.refresh()

    view._tree.setCurrentItem(_top_level(view._tree)["Mine"])

    assert _shown(_top_level(view._tree)["Mine"]) == "(2) Mine"
    assert _tile_kinds_in_order(view) == [ItemTile, FolderTile]
    assert view._gallery_pane.listed_prompt_ids() == ["i1"]
    assert view._gallery_pane._listed_folders == [dog]
    assert [r["prompt_id"] for r in view.rows_to_play()] == ["i1", "i2"]


def test_a_custom_folder_leads_with_how_many_items_it_gathers_counting_each_once(qtbot):
    view, leaf, _other = _two_leaf_view(qtbot, extra=[_image("i3", "a cat", 50, 2)])
    lora = _key(_at(_image_workflow(view._tree), 0, 0))
    _make_folder(view, "Kept", [lora, leaf])

    assert _shown(_top_level(view._tree)["Kept"]) == "(3) Kept"


def test_a_custom_folder_is_not_where_the_gallery_lands_by_default(qtbot):
    view, cat, _dog = _two_leaf_view(qtbot)
    _make_folder(view, "Favorites", [cat])

    assert view._tree_view.default_item() is _top_level(view._tree)["All"]


def test_dropping_a_folder_onto_a_custom_folder_adds_it(qtbot):
    view, cat, dog = _two_leaf_view(qtbot)
    folder_id = _make_folder(view, "Favorites", [cat])

    view._on_dropped(gallery.custom_collection_key(folder_id), [dog])

    (record,) = view._db.list_custom_collections()
    assert record["folders"] == [cat, dog]
    assert view._gallery_pane._listed_folders == [cat, dog]  # landed on it


def _drop_on(row, mime) -> bool:
    """Drag ``mime`` over a TOC row and let it go there, as a drag from anywhere
    in the window ends; whether the row took it. The caller holds ``mime``: a
    synthetic drop event does not own it."""
    tree = row.treeWidget()
    spot = QPointF(tree.visualRect(tree.indexFromItem(row)).center())
    move = QDragMoveEvent(spot.toPoint(), Qt.DropAction.CopyAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    tree.dragMoveEvent(move)
    tree.dropEvent(QDropEvent(spot, Qt.DropAction.CopyAction, mime,
                              Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    return move.isAccepted()


def test_an_item_dropped_on_a_custom_folders_row_goes_in_and_the_folder_opens(qtbot):
    view, _cat, dog = _two_leaf_view(qtbot)
    folder_id = _make_folder(view, "Mine", [dog])
    with qtbot.waitExposed(view):
        view.show()
    mime = generation_mime("i1")

    assert _drop_on(_top_level(view._tree)["Mine"], mime)

    (record,) = view._db.list_custom_collections()
    assert record["items"] == ["i1"]
    assert view.current_group().key == gallery.custom_collection_key(folder_id)


def test_a_folder_of_your_own_refuses_an_item_of_the_other_shape(qtbot):
    # The same rule a folder dragged out of the other half meets.
    view, _cat, _dog = _two_leaf_view(qtbot, extra=[_tall("t1", "a fish")])
    _make_folder(view, "Mine", [])
    with qtbot.waitExposed(view):
        view.show()
    mime = generation_mime("t1")

    assert not _drop_on(_top_level(view._tree)["Mine"], mime)
    assert view._db.list_custom_collections()[0]["items"] == []


def test_a_folder_of_your_own_refuses_an_item_no_folder_shows(qtbot):
    # One in the Trash, or still being made: it would land and never be seen.
    view, _cat, _dog = _two_leaf_view(qtbot)
    _make_folder(view, "Mine", [])
    with qtbot.waitExposed(view):
        view.show()
    mime = generation_mime("not-in-any-folder")

    assert not _drop_on(_top_level(view._tree)["Mine"], mime)
    assert view._db.list_custom_collections()[0]["items"] == []


def _drop_in_the_middle_pane(view, mime, source=None) -> bool:
    """Drag ``mime`` over the middle pane and let it go there; whether the pane
    took it. ``source`` stands in for where the drag started, as a real one
    names it."""
    pane = view._scroll.viewport()
    spot = QPointF(pane.rect().center())
    held = (spot.toPoint(), Qt.DropAction.CopyAction, mime,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    enter, move = QDragEnterEvent(*held), QDragMoveEvent(*held)
    drop = QDropEvent(spot, *held[1:])
    for event in (enter, move, drop):
        event.source = lambda: source
    QApplication.sendEvent(pane, enter)
    QApplication.sendEvent(pane, move)
    QApplication.sendEvent(pane, drop if move.isAccepted() else QDragLeaveEvent())
    return move.isAccepted()


def test_an_item_dropped_into_an_open_custom_folder_goes_in(qtbot):
    view, _cat, dog = _two_leaf_view(qtbot)
    _make_folder(view, "Mine", [dog])
    view._tree.setCurrentItem(_top_level(view._tree)["Mine"])
    mime = generation_mime("i1")

    assert _drop_in_the_middle_pane(view, mime)

    assert view._db.list_custom_collections()[0]["items"] == ["i1"]
    assert view._gallery_pane.listed_prompt_ids() == ["i1"]  # drawn again with it


def _folder_drag(view, key):
    """The payload a drag of ``key``'s row out of the TOC carries."""
    mime = QMimeData()
    mime.setData(FOLDER_KEYS_MIME, view._tree_item_for(key).data(0, TREE_KEY_ROLE).encode())
    return mime


def test_a_folder_dragged_from_the_toc_into_an_open_custom_folder_goes_in(qtbot):
    view, cat, dog = _two_leaf_view(qtbot)
    _make_folder(view, "Mine", [dog])
    view._tree.setCurrentItem(_top_level(view._tree)["Mine"])
    mime = _folder_drag(view, cat)

    assert _drop_in_the_middle_pane(view, mime, source=_side(view._tree))

    assert view._db.list_custom_collections()[0]["folders"] == [dog, cat]


def test_an_open_custom_folder_refuses_a_folder_from_the_other_shapes_list(qtbot):
    view, cat, dog = _two_leaf_view(qtbot)
    _make_folder(view, "Mine", [dog])
    view._tree.setCurrentItem(_top_level(view._tree)["Mine"])
    mime = _folder_drag(view, cat)

    assert not _drop_in_the_middle_pane(view, mime, source=_side(view._tree, PORTRAIT))

    assert view._db.list_custom_collections()[0]["folders"] == [dog]


def test_a_custom_folder_dropped_on_another_goes_inside_it(qtbot):
    view, cat, dog = _two_leaf_view(qtbot)
    inner = gallery.custom_collection_key(_make_folder(view, "Inner", [dog]))
    _make_folder(view, "Outer", [cat])
    with qtbot.waitExposed(view):
        view.show()
    mime = _folder_drag(view, inner)

    assert _drop_on(_top_level(view._tree)["Outer"], mime)

    outer = next(r for r in view._db.list_custom_collections() if r["name"] == "Outer")
    assert outer["folders"] == [cat, inner]
    assert _shown(_top_level(view._tree)["Outer"]) == "(2) Outer"
    assert view._gallery_pane._listed_folders == [cat, inner]  # landed on it
    assert "Inner" not in _top_level(view._tree)


def test_a_custom_folder_cannot_go_inside_one_it_holds(qtbot):
    view, cat, _dog = _two_leaf_view(qtbot)
    inner = gallery.custom_collection_key(_make_folder(view, "Inner", [cat]))
    outer = gallery.custom_collection_key(_make_folder(view, "Outer", [inner]))
    with qtbot.waitExposed(view):
        view.show()
    mime = _folder_drag(view, outer)
    outer_row = _top_level(view._tree)["Outer"]
    outer_row.setExpanded(True)
    (inner_row,) = _subs(outer_row)

    assert not _drop_on(inner_row, mime)

    inner_record = next(r for r in view._db.list_custom_collections() if r["name"] == "Inner")
    assert inner_record["folders"] == [cat]


def test_a_custom_folder_dragged_onto_favorites_is_refused(qtbot):
    # Favorites stars what lands on it, and a custom collection takes no star.
    view, cat, _dog = _two_leaf_view(qtbot)
    mine = gallery.custom_collection_key(_make_folder(view, "Mine", [cat]))
    with qtbot.waitExposed(view):
        view.show()
    mime = _folder_drag(view, mine)

    assert not _drop_on(_alls(view._tree)["Favorites"], mime)


def test_open_favorites_takes_no_drop_though_its_row_does(qtbot):
    view, cat, _dog = _two_leaf_view(qtbot)
    view._tree.setCurrentItem(_alls(view._tree)["Favorites"])
    mime = _folder_drag(view, cat)

    assert not _drop_in_the_middle_pane(view, mime, source=_side(view._tree))


def _middle_pane_style(view, qtbot):
    """The drop style the middle pane wears, read where nothing in it is drawn."""
    view.setStyleSheet(build_stylesheet())
    view.resize(1100, 1200)
    with qtbot.waitExposed(view):
        view.show()
    pane = view._scroll.rect()
    return worn(view._scroll.grab().toImage(), pane,
                QPoint(pane.right() - 3, pane.bottom() - 3))


def test_an_open_custom_folder_lights_while_an_item_it_would_take_is_dragged(qtbot):
    view, _cat, dog = _two_leaf_view(qtbot)
    _make_folder(view, "Mine", [dog])
    view._tree.setCurrentItem(_top_level(view._tree)["Mine"])
    mime = generation_mime("i1")

    under_way.started.emit(mime, None)

    assert _middle_pane_style(view, qtbot) == LIT
    under_way.ended.emit()


def test_open_favorites_stays_as_it_is_while_a_folder_is_dragged(qtbot):
    view, cat, _dog = _two_leaf_view(qtbot)
    view._tree.setCurrentItem(_alls(view._tree)["Favorites"])
    mime = _folder_drag(view, cat)

    under_way.started.emit(mime, _side(view._tree))

    assert _middle_pane_style(view, qtbot) is None
    under_way.ended.emit()

    assert not view.group_for_key(cat).favorite


def test_dropping_a_folder_onto_favorite_favorites_it(qtbot):
    view, cat, _dog = _two_leaf_view(qtbot)

    view._on_dropped(FAVORITES_KEY, [cat])

    assert view._db.folder_meta_map()[cat]["starred"] is True


def test_dropping_a_favorite_folder_onto_favorites_leaves_it_a_favorite(qtbot):
    view, cat, _dog = _two_leaf_view(qtbot)
    view._toggle_favorite(cat)

    view._on_dropped(FAVORITES_KEY, [cat])

    assert view._db.folder_meta_map()[cat]["starred"] is True


def test_a_folder_the_user_made_dropped_onto_favorites_takes_no_favorite(qtbot):
    view, cat, _dog = _two_leaf_view(qtbot)
    made = gallery.custom_collection_key(_make_folder(view, "Mine", [cat]))

    view._on_dropped(FAVORITES_KEY, [made])

    assert made not in view._db.folder_meta_map()


def test_dropping_a_folder_onto_favorite_stars_it_where_it_stands(qtbot):
    # The other way of starring from the list, and it must cost the list no more
    # than the star itself does: no redraw, so no jump under the dragging hand.
    view, cat, _dog = _two_leaf_view(qtbot)
    row = view._tree_item_for(cat)

    view._on_dropped(FAVORITES_KEY, [cat])

    assert view._tree_item_for(cat) is row
    assert row.data(0, _GROUP_ROLE).favorite


def test_dropped_folders_carry_the_identity_the_reconcile_needs(qtbot):
    # Without (level, ref) a gathered folder cannot be re-derived when a key
    # formula moves, and the grouping silently loses it.
    view, cat, _dog = _two_leaf_view(qtbot)
    folder_id = _make_folder(view, "Favorites", [])

    view._on_dropped(gallery.custom_collection_key(folder_id), [cat])

    (held,) = view._db.folders_in_custom_collections()
    assert (held["level"], held["ref_prompt_id"]) == ("settings", "i1")


def test_removing_a_gathered_folder_leaves_its_items_alone(qtbot):
    view, cat, dog = _two_leaf_view(qtbot)
    folder_id = _make_folder(view, "Favorites", [cat, dog])
    group = view.group_for_key(gallery.custom_collection_key(folder_id))

    view._remove_from_custom_collection(group, [dog])

    (record,) = view._db.list_custom_collections()
    assert record["folders"] == [cat]
    assert view._db.get_generation("i2") is not None  # the folder itself survives


def test_removing_a_custom_folder_keeps_every_generation_it_gathered(qtbot):
    view, cat, dog = _two_leaf_view(qtbot)
    folder_id = _make_folder(view, "Keepers", [cat, dog])
    view._confirm = lambda text: True

    view._remove_custom_collection(view.group_for_key(gallery.custom_collection_key(folder_id)))

    assert view._db.list_custom_collections() == []
    assert {r["prompt_id"] for r in view._db.list_generations()} == {"i1", "i2"}
    assert "Keepers" not in _top_level(view._tree)


def test_removing_a_folder_of_your_own_says_the_items_it_holds_are_kept(qtbot):
    view, cat, _dog = _two_leaf_view(qtbot)
    folder_id = _make_folder(view, "Keepers", [cat])
    view._db.add_items_to_custom_collection(folder_id, ["i2"])
    view.refresh()
    asked = []
    view._confirm = lambda text: asked.append(text) and False

    view._remove_custom_collection(view.group_for_key(gallery.custom_collection_key(folder_id)))

    assert asked == ["Remove the folder “Keepers”?\n\n"
                     "The 1 folder and 1 item it holds are kept."]


def test_a_folder_of_your_own_says_folders_and_items_can_be_dropped_on_it(qtbot):
    view, cat, _dog = _two_leaf_view(qtbot)
    _make_folder(view, "Keepers", [cat])

    assert _top_level(view._tree)["Keepers"].toolTip(0).endswith(
        "drop folders or items here to add them")


def test_an_empty_folder_of_your_own_says_items_can_be_dragged_onto_it(qtbot):
    view, _cat, _dog = _two_leaf_view(qtbot)
    _make_folder(view, "Keepers", [])

    view._tree.setCurrentItem(_top_level(view._tree)["Keepers"])

    assert view._scroll.widget().text() == (
        "“Keepers” is empty.\n\nDrag folders from the list, or items, onto it, "
        "or pick several folders with Shift/Ctrl and group them.")


def test_a_custom_folder_cannot_be_deleted_by_the_folder_delete_path(qtbot):
    # Delete trashes a folder's generations; a custom collection holds none of its own,
    # so that path must never accept one.
    view, cat, _dog = _two_leaf_view(qtbot)
    folder_id = _make_folder(view, "Favorites", [cat])
    view._tree.setCurrentItem(_top_level(view._tree)["Favorites"])
    view._confirm = lambda text: True

    view._delete_selection()

    assert view._db.get_generation("i1") is not None
    assert view._db.list_custom_collections()[0]["id"] == folder_id


def test_a_custom_folder_survives_a_rebuild_and_follows_its_items(qtbot):
    view, cat, _dog = _two_leaf_view(qtbot)
    _make_folder(view, "Favorites", [cat])
    view._tree.setCurrentItem(_top_level(view._tree)["Favorites"])

    view._db.add(_image("i3", "a cat", 50, 9))  # a new seed joins the gathered folder
    view.refresh()

    assert view._tree.currentItem() is _top_level(view._tree)["Favorites"]
    assert {r["prompt_id"] for r in view.rows_to_play()} == {"i1", "i3"}


def test_a_rebuild_keeps_a_live_multi_selection(qtbot):
    # A poll or a finished generation rebuilds the tree; collapsing the selection
    # would throw away the folder the user is in the middle of composing.
    view, cat, dog = _two_leaf_view(qtbot)
    _pick(view, cat, dog)

    view._db.add(_image("i3", "a fish", 50, 3))
    view.refresh()

    assert view._selection_group is not None
    assert len(view._gallery_pane._listed_folders) == 2


# --- the tree's right-click menus: the only route to several of these actions --


def _square_menu(view, key):
    """Right-click the square a folder is drawn as in the pane beside the list."""
    _tall_on_screen(view)
    (square,) = [tile for tile in view._scroll.widget().findChildren(FolderTile)
                 if tile.key == key]
    view._scroll.ensureWidgetVisible(square)
    gestures.right_click(square, square.rect().center())


def _open_square(view, key):
    """Click the square a folder is drawn as in the pane beside the list."""
    _tall_on_screen(view)
    (square,) = [tile for tile in view._scroll.widget().findChildren(FolderTile)
                 if tile.key == key]
    view._scroll.ensureWidgetVisible(square)
    gestures.click(square, square.rect().center())


def test_a_folder_opened_from_inside_a_folder_of_your_own_opens_under_it_in_the_list(qtbot):
    view, cat, _dog = _two_leaf_view(qtbot)
    _make_folder(view, "Mine", [cat])
    view._tree.setCurrentItem(_top_level(view._tree)["Mine"])

    _open_square(view, cat)

    here = view._tree.currentItem()
    assert (_key(here), here.parent()) == (cat, _top_level(view._tree)["Mine"])


def test_a_folder_under_a_folder_of_your_own_in_the_list_can_be_taken_out_of_it(
        qtbot, monkeypatch):
    view, cat, _dog = _two_leaf_view(qtbot)
    _make_folder(view, "Mine", [cat])
    (under_mine,) = _subs(_top_level(view._tree)["Mine"])
    _answer_menu(monkeypatch, "Remove from “Mine”")

    _tree_menu(view, under_mine.data(0, TREE_KEY_ROLE))

    assert view._db.list_custom_collections()[0]["folders"] == []


def test_a_folder_of_your_own_put_inside_another_leaves_the_top_of_the_list(qtbot):
    view, cat, _dog = _two_leaf_view(qtbot)
    inner = gallery.custom_collection_key(_make_folder(view, "Inner", [cat]))

    _make_folder(view, "Outer", [inner])

    assert "Inner" not in _top_level(view._tree)
    assert [_key(row) for row in _subs(_top_level(view._tree)["Outer"])] == [inner]


def test_standing_on_a_folder_of_your_own_as_it_goes_inside_another_stays_on_it(qtbot):
    view, cat, _dog = _two_leaf_view(qtbot)
    inner_id = _make_folder(view, "Inner", [cat])
    view._tree.setCurrentItem(_top_level(view._tree)["Inner"])

    _make_folder(view, "Outer", [gallery.custom_collection_key(inner_id)])

    here = view._tree.currentItem()
    assert (_key(here), here.parent()) == (gallery.custom_collection_key(inner_id),
                                           _top_level(view._tree)["Outer"])


def test_an_item_dropped_on_a_folder_of_your_own_inside_another_opens_it_there(qtbot):
    view, cat, _dog = _two_leaf_view(qtbot)
    inner = gallery.custom_collection_key(_make_folder(view, "Inner", [cat]))
    _make_folder(view, "Outer", [inner])
    with qtbot.waitExposed(view):
        view.show()
    outer_row = _top_level(view._tree)["Outer"]
    outer_row.setExpanded(True)
    (inner_row,) = _subs(outer_row)
    mime = generation_mime("i2")

    assert _drop_on(inner_row, mime)

    here = view._tree.currentItem()
    assert (_key(here), here.parent()) == (inner, _top_level(view._tree)["Outer"])


def test_a_custom_folder_inside_another_can_be_taken_back_out_of_it(qtbot, monkeypatch):
    view, cat, _dog = _two_leaf_view(qtbot)
    inner = gallery.custom_collection_key(_make_folder(view, "Inner", [cat]))
    _make_folder(view, "Outer", [inner])
    view._tree.setCurrentItem(_top_level(view._tree)["Outer"])  # standing inside it
    _answer_menu(monkeypatch, "Remove from “Outer”")

    _square_menu(view, inner)

    outer = next(r for r in view._db.list_custom_collections() if r["name"] == "Outer")
    assert outer["folders"] == []
    assert "Inner" in _top_level(view._tree)  # taken out of it, not removed


def test_a_folders_menu_offers_its_name_favorite_and_a_delete_kept_apart(qtbot, monkeypatch):
    view, cat, _dog = _two_leaf_view(qtbot)
    labels = []
    _menu_labels(monkeypatch, labels)

    _tree_menu(view, cat)

    # The separator is the point: the one entry that destroys anything sits below
    # it, away from the one that costs nothing.
    assert labels == ["Copy name", "", "Favorite", "", "Delete folder…"]


def test_copy_name_on_a_folder_copies_its_code(qtbot, monkeypatch):
    view, cat, _dog = _two_leaf_view(qtbot)
    QApplication.clipboard().clear()
    _answer_menu(monkeypatch, "Copy name")

    _tree_menu(view, cat)

    code = gallery.folder_id(gallery.settings_folder_key(_image("i1", "a cat", 50, 1)))
    assert QApplication.clipboard().text() == code


def test_copy_name_on_a_folder_given_a_name_copies_that_name(qtbot, monkeypatch):
    view, cat, _dog = _two_leaf_view(qtbot)
    view._db.upsert_folder_meta(cat, custom_name="Moonlit set", favorite=False,
                                level=None, ref_prompt_id=None)
    view.refresh()
    QApplication.clipboard().clear()
    _answer_menu(monkeypatch, "Copy name")

    _tree_menu(view, cat)

    assert QApplication.clipboard().text() == "Moonlit set"


def test_a_folder_squares_menu_copies_its_name_too(qtbot, monkeypatch):
    view, cat, dog = _two_leaf_view(qtbot)
    view._tree.setCurrentItem(view._tree_item_for(dog).parent())  # both, as squares
    QApplication.clipboard().clear()
    _answer_menu(monkeypatch, "Copy name")

    _square_menu(view, dog)

    assert QApplication.clipboard().text() == view._tree_item_for(dog).text(0)


def test_a_workflows_menu_offers_no_delete(qtbot, monkeypatch):
    # A whole workflow's history must never go in one action.
    view, _cat, _dog = _two_leaf_view(qtbot)
    labels = []
    _menu_labels(monkeypatch, labels)

    _tree_menu(view, _key(_image_workflow(view._tree)))

    assert "Delete folder…" not in labels


def test_deleting_a_folder_from_its_menu_trashes_what_that_folder_holds(
        qtbot, monkeypatch):
    actions = FakeActions()
    view, cat, _dog = _two_leaf_view(qtbot, actions=actions)
    view._confirm = lambda text: True
    _answer_menu(monkeypatch, "Delete folder…")

    _tree_menu(view, cat)

    assert {r["prompt_id"] for r in actions.deleted[0]} == {"i1"}  # its own row only


def test_a_folders_menu_lists_the_folders_of_your_own_it_could_join(qtbot, monkeypatch):
    view, cat, dog = _two_leaf_view(qtbot)
    _make_folder(view, "Keepers", [cat])
    _answer_menu(monkeypatch, "Keepers")  # under "Add to collection"

    _tree_menu(view, dog)

    (record,) = view._db.list_custom_collections()
    assert record["folders"] == [cat, dog]


def test_a_folders_menu_offers_only_the_folders_of_your_own_on_its_side(qtbot, monkeypatch):
    view, _cat, dog = _two_leaf_view(qtbot)
    view._db.create_custom_folder("Tall ones", side=PORTRAIT)
    view.refresh()
    labels = []
    _menu_labels(monkeypatch, labels)

    _tree_menu(view, dog)

    assert "Add to collection" not in labels


def test_a_folder_squares_menu_offers_the_folders_of_your_own_on_the_side_browsed(
        qtbot, monkeypatch):
    view, cat, dog = _two_leaf_view(qtbot)
    _make_folder(view, "Keepers", [cat])
    view._tree.setCurrentItem(view._tree_item_for(dog).parent())  # both, as squares
    labels = []
    _menu_labels(monkeypatch, labels)

    _square_menu(view, dog)

    assert "Add to collection" in labels


def test_a_folder_already_in_a_folder_of_your_own_is_not_offered_it_again(
        qtbot, monkeypatch):
    view, cat, _dog = _two_leaf_view(qtbot)
    _make_folder(view, "Keepers", [cat])
    labels = []
    _menu_labels(monkeypatch, labels)

    _tree_menu(view, cat)

    assert "Add to collection" not in labels


def test_a_gathered_folder_can_be_dropped_from_the_folder_showing_it(qtbot, monkeypatch):
    view, cat, dog = _two_leaf_view(qtbot)
    folder_id = _make_folder(view, "Keepers", [cat, dog])
    view._tree.setCurrentItem(_top_level(view._tree)["Keepers"])  # standing inside it
    _answer_menu(monkeypatch, "Remove from “Keepers”")

    _square_menu(view, dog)

    (record,) = view._db.list_custom_collections()
    assert record["id"] == folder_id
    assert record["folders"] == [cat]
    assert view._db.get_generation("i2") is not None  # dropped from it, not deleted


def test_an_item_can_be_taken_out_of_the_folder_of_your_own_showing_it(qtbot, monkeypatch):
    view, cat, _dog = _two_leaf_view(qtbot)
    folder_id = _make_folder(view, "Keepers", [cat])
    view._db.add_items_to_custom_collection(folder_id, ["i2"])
    view.refresh()
    view._tree.setCurrentItem(_top_level(view._tree)["Keepers"])  # standing inside it
    _answer_menu(monkeypatch, "Remove from “Keepers”")

    view.generation_menu(["i2"], QPoint(0, 0))

    (record,) = view._db.list_custom_collections()
    assert record["items"] == []
    assert record["folders"] == [cat]
    assert view._db.get_generation("i2") is not None  # taken out of it, not deleted


def test_an_item_there_only_by_its_folder_offers_no_way_out_of_the_folder_of_your_own(
        qtbot, monkeypatch):
    # It is in there because its folder is, so only that folder can be taken out.
    view, cat, _dog = _two_leaf_view(qtbot)
    _make_folder(view, "Keepers", [cat])
    view._tree.setCurrentItem(_top_level(view._tree)["Keepers"])
    labels = []
    _menu_labels(monkeypatch, labels)

    view.generation_menu(["i1"], QPoint(0, 0))

    assert labels
    assert "Remove from “Keepers”" not in labels


def test_the_menu_over_a_folder_of_your_own_offers_its_name_and_its_removal(
        qtbot, monkeypatch):
    view, cat, _dog = _two_leaf_view(qtbot)
    folder_id = _make_folder(view, "Keepers", [cat])
    labels = []
    _menu_labels(monkeypatch, labels)

    _tree_menu(view, gallery.custom_collection_key(folder_id))

    # No star (a favorite of a favorite collection gathers nothing) and no delete —
    # removing one of these must never reach the generations it gathers.
    assert labels == ["Copy name", "", "Remove collection…", "", "Collapse all", "Expand all"]


def test_copy_name_on_a_folder_of_your_own_copies_the_name_you_gave_it(
        qtbot, monkeypatch):
    view, cat, _dog = _two_leaf_view(qtbot)
    folder_id = _make_folder(view, "Keepers", [cat])
    QApplication.clipboard().clear()
    _answer_menu(monkeypatch, "Copy name")

    _tree_menu(view, gallery.custom_collection_key(folder_id))

    assert QApplication.clipboard().text() == "Keepers"


def test_removing_a_folder_of_your_own_from_its_menu_keeps_what_it_gathered(
        qtbot, monkeypatch):
    view, cat, dog = _two_leaf_view(qtbot)
    folder_id = _make_folder(view, "Keepers", [cat, dog])
    view._confirm = lambda text: True
    _answer_menu(monkeypatch, "Remove collection…")

    _tree_menu(view, gallery.custom_collection_key(folder_id))

    assert view._db.list_custom_collections() == []
    assert {r["prompt_id"] for r in view._db.list_generations()} == {"i1", "i2"}


def test_right_clicking_below_the_last_row_starts_a_folder_of_your_own(
        qtbot, monkeypatch):
    view, _cat, _dog = _two_leaf_view(qtbot)
    _answer_menu(monkeypatch, "New collection…")
    monkeypatch.setattr(gallery_view_module.QInputDialog, "getText",
                        staticmethod(lambda *a, **kw: ("Keepers", True)))

    _tree_menu(view)  # no row under the cursor

    (record,) = view._db.list_custom_collections()
    assert record["name"] == "Keepers"
    assert record["folders"] == []
    assert _top_level(view._tree)["Keepers"] is view._tree.currentItem()


def _tall(prompt_id, prompt):
    return _row(prompt_id, "sdxl_t2i", {"positive_prompt": prompt, "steps": 50, "seed": 1,
                                        "width": 100, "height": 200},
                f"sdxl_t2i_{prompt_id}.png")


def test_grouping_picked_folders_makes_a_folder_on_their_side(qtbot, monkeypatch):
    rows = [_tall("t1", "a cat"), _tall("t2", "a dog")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    _pick(view, *(oriented_key(gallery.settings_folder_key(row), PORTRAIT) for row in rows))
    monkeypatch.setattr(gallery_view_module.QInputDialog, "getText",
                        staticmethod(lambda *a, **kw: ("Keepers", True)))

    view._group_selection()

    (record,) = view._db.list_custom_collections()
    assert record["side"] == PORTRAIT


def test_a_folder_started_below_the_last_row_belongs_to_that_half(qtbot, monkeypatch):
    view, _cat, _dog = _two_leaf_view(qtbot)
    _answer_menu(monkeypatch, "New collection…")
    monkeypatch.setattr(gallery_view_module.QInputDialog, "getText",
                        staticmethod(lambda *a, **kw: ("Keepers", True)))

    _tree_menu(view, side=PORTRAIT)

    (record,) = view._db.list_custom_collections()
    assert record["side"] == PORTRAIT
    assert _top_level(view._tree, PORTRAIT)["Keepers"] is view._tree.currentItem()


def test_right_clicking_a_picked_folder_offers_the_whole_selection(qtbot, monkeypatch):
    view, cat, dog = _two_leaf_view(qtbot)
    _pick(view, cat, dog)
    _answer_menu(monkeypatch, "Group 2 folders into a new collection…")
    monkeypatch.setattr(gallery_view_module.QInputDialog, "getText",
                        staticmethod(lambda *a, **kw: ("Keepers", True)))

    _tree_menu(view, cat)

    (record,) = view._db.list_custom_collections()
    assert record["folders"] == [cat, dog]  # both, not the one under the cursor


def test_copying_the_names_of_picked_folders_puts_them_one_to_a_line(qtbot, monkeypatch):
    view, cat, dog = _two_leaf_view(qtbot)
    _pick(view, cat, dog)
    QApplication.clipboard().clear()
    _answer_menu(monkeypatch, "Copy 2 names")

    _tree_menu(view, dog)

    codes = [gallery.folder_id(gallery.settings_folder_key(_image(pid, prompt, 50, 1)))
             for pid, prompt in (("i1", "a cat"), ("i2", "a dog"))]
    assert QApplication.clipboard().text() == "\n".join(codes)


def test_right_clicking_outside_a_selection_is_about_the_row_under_the_cursor(
        qtbot, monkeypatch):
    # Otherwise a right-click on a folder the user did not pick would act on the
    # ones they did, which is the same click meaning two different things.
    view, cat, dog = _two_leaf_view(qtbot, extra=[_image("i3", "a fish", 50, 1)])
    fish = _key(_at(_image_workflow(view._tree), 0, 0, 2))
    _pick(view, cat, dog)
    labels = []
    _menu_labels(monkeypatch, labels)

    _tree_menu(view, fish)

    assert labels == ["Copy name", "", "Favorite", "", "Delete folder…"]


def test_expand_all_opens_the_folder_and_every_folder_inside_it(qtbot, monkeypatch):
    view, _cat, _dog = _two_leaf_view(qtbot)
    _answer_menu(monkeypatch, "Expand all")

    _tree_menu(view, _key(_image_workflow(view._tree)))

    workflow = _image_workflow(view._tree)
    model = _at(workflow, 0)
    assert [workflow.isExpanded(), model.isExpanded(), _at(model, 0).isExpanded()] == [
        True, True, True]


def test_collapse_all_shuts_the_folder_and_every_folder_inside_it(qtbot, monkeypatch):
    view, _cat, _dog = _two_leaf_view(qtbot)
    model = _at(_image_workflow(view._tree), 0)
    for row in (_image_workflow(view._tree), model, _at(model, 0)):
        row.setExpanded(True)
    _answer_menu(monkeypatch, "Collapse all")

    _tree_menu(view, _key(_image_workflow(view._tree)))

    workflow = _image_workflow(view._tree)
    model = _at(workflow, 0)
    assert [workflow.isExpanded(), model.isExpanded(), _at(model, 0).isExpanded()] == [
        False, False, False]


def test_collapse_all_and_expand_all_come_last_on_a_folders_menu(qtbot, monkeypatch):
    view, _cat, _dog = _two_leaf_view(qtbot)
    labels = []
    _menu_labels(monkeypatch, labels)

    _tree_menu(view, _key(_at(_image_workflow(view._tree), 0)))

    assert labels == ["Copy name", "", "Favorite", "", "Delete folder…", "",
                      "Collapse all", "Expand all"]


def test_a_folder_squares_menu_offers_no_collapse_all_or_expand_all(qtbot, monkeypatch):
    view, _cat, _dog = _two_leaf_view(qtbot)
    model = _key(_at(_image_workflow(view._tree), 0))
    view._tree.setCurrentItem(_image_workflow(view._tree))
    labels = []
    _menu_labels(monkeypatch, labels)

    _square_menu(view, model)

    assert labels == ["Copy name", "", "Favorite", "", "Delete folder…"]


def _two_model_view(qtbot):
    """A view whose image workflow holds two model folders, each with a folder
    inside it, returned by key."""
    rows = [_row(prompt_id, "sdxl_t2i",
                 {"positive_prompt": "a cat", "steps": 50, "seed": 1, "checkpoint": checkpoint},
                 f"sdxl_t2i_{prompt_id}.png")
            for prompt_id, checkpoint in (("i1", "first.safetensors"),
                                          ("i2", "second.safetensors"))]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    return view, *(_key(_at(_image_workflow(view._tree), n)) for n in (0, 1))


def test_expand_all_opens_every_picked_folder_and_every_folder_inside_each(
        qtbot, monkeypatch):
    view, first, second = _two_model_view(qtbot)
    _pick(view, first, second)
    _answer_menu(monkeypatch, "Expand all")

    _tree_menu(view, first)

    models = [view._tree_item_for(key) for key in (first, second)]
    assert [row.isExpanded() for model in models for row in (model, _at(model, 0))] == [
        True] * 4


def test_the_picked_folders_menu_offers_collapse_all_and_expand_all_last(
        qtbot, monkeypatch):
    view, first, second = _two_model_view(qtbot)
    _pick(view, first, second)
    labels = []
    _menu_labels(monkeypatch, labels)

    _tree_menu(view, second)

    assert labels == ["Copy 2 names", "", "Group 2 folders into a new collection…", "",
                      "Delete 2 folders…", "", "Collapse all", "Expand all"]


def test_the_picked_folders_menu_offers_to_delete_them(qtbot, monkeypatch):
    view, cat, dog = _two_leaf_view(qtbot)
    _pick(view, cat, dog)
    labels = []
    _menu_labels(monkeypatch, labels)

    _tree_menu(view, dog)

    assert labels == ["Copy 2 names", "", "Group 2 folders into a new collection…", "",
                      "Delete 2 folders…"]


def test_deleting_the_picked_folders_asks_first_then_takes_them_all(qtbot, monkeypatch):
    actions = FakeActions()
    view, cat, dog = _two_leaf_view(qtbot, actions=actions)
    _pick(view, cat, dog)
    asked = []
    view._confirm = lambda text: asked.append(text) or True
    _answer_menu(monkeypatch, "Delete 2 folders…")

    _tree_menu(view, dog)

    assert asked == ["Delete 2 folders and their 2 items?"]
    assert {r["prompt_id"] for r in actions.deleted[0]} == {"i1", "i2"}


def _pick_by_clicks(view, first, *others):
    """Pick folder rows as a mouse does: a click on the first, a Ctrl-click on
    each of the others."""
    _tall_on_screen(view)
    for key, modifiers in ((first, Qt.KeyboardModifier.NoModifier),
                           *((key, Qt.KeyboardModifier.ControlModifier) for key in others)):
        row = view._tree_item_for(key)
        tree = row.treeWidget()
        tree.scrollToItem(row)
        gestures.click(tree.viewport(), tree.visualItemRect(row).center(), modifiers)


def test_the_trash_can_takes_every_folder_picked_by_clicks_after_a_right_click(
        qtbot, monkeypatch):
    actions = FakeActions()
    view, cat, dog = _two_leaf_view(qtbot, actions=actions)
    _pick_by_clicks(view, cat, dog)
    asked = []
    view._confirm = lambda text: asked.append(text) or False
    _answer_menu(monkeypatch, "Delete 2 folders…")
    _tree_menu(view, dog)

    tip = view._buttons.delete.toolTip()
    view._buttons.delete.click()

    assert (tip, asked) == ("Delete 2 folders", ["Delete 2 folders and their 2 items?"] * 2)


def test_the_trash_can_on_a_picked_row_deletes_every_picked_folder(qtbot):
    actions = FakeActions()
    view, cat, dog = _two_leaf_view(qtbot, actions=actions)
    _pick_by_clicks(view, cat, dog)
    asked = []
    view._confirm = lambda text: asked.append(text) or True

    _click_beside_the_mark_of(qtbot, view, dog, which=1)

    assert asked == ["Delete 2 folders and their 2 items?"]
    assert {r["prompt_id"] for r in actions.deleted[0]} == {"i1", "i2"}


def test_the_trash_can_on_a_row_outside_the_picked_folders_deletes_only_its_own(qtbot):
    actions = FakeActions()
    view, cat, dog = _two_leaf_view(qtbot, actions=actions,
                                    extra=[_image("i3", "a fish", 50, 1)])
    fish = _key(_at(_image_workflow(view._tree), 0, 0, 2))
    _pick_by_clicks(view, cat, dog)
    view._confirm = lambda text: True

    _click_beside_the_mark_of(qtbot, view, fish, which=1)

    assert {r["prompt_id"] for r in actions.deleted[0]} == {"i3"}


def _trash_can_drawn_on(view, key) -> bool:
    row = view._tree_item_for(key)
    tree = row.treeWidget()
    trash = _action_rects(tree.visualItemRect(row))[1]
    gestures.move(tree.viewport(), trash.center())
    image = tree.viewport().grab(trash).toImage()
    return any((color := image.pixelColor(x, y)).red() > color.green() + 50
               and color.red() > color.blue() + 50
               for x in range(image.width()) for y in range(image.height()))


def test_a_picked_row_drops_its_trash_can_once_a_folder_that_cannot_go_is_picked(qtbot):
    view, cat, dog = _two_leaf_view(qtbot)
    _pick_by_clicks(view, cat, dog)
    assert _trash_can_drawn_on(view, cat)

    _pick_by_clicks(view, cat, dog, _key(_image_workflow(view._tree)))

    assert not _trash_can_drawn_on(view, cat)


def test_picked_folders_offer_no_delete_when_one_of_them_cannot_be_deleted(
        qtbot, monkeypatch):
    view, cat, _dog = _two_leaf_view(qtbot)
    _pick(view, cat, _key(_image_workflow(view._tree)))
    labels = []
    _menu_labels(monkeypatch, labels)

    _tree_menu(view, cat)

    assert "Delete 2 folders…" not in labels
    assert not view._buttons.delete.isEnabled()
