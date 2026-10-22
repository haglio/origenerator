"""The rows of the table of contents: where each one wears its mark."""
from __future__ import annotations

import json

from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QStyle, QStyleOptionViewItem
from shared_ui.colors import TEXT_PRIMARY
from shared_ui.icons import glyph_pixmap

from origenerator import gallery
from origenerator.gallery.sides import LANDSCAPE, PORTRAIT
from origenerator.gui.folder_tree import DROP_KEY_ROLE, RECENT_ROLE, TREE_KEY_ROLE
from origenerator.gui.gallery_tree import GROUP_ROLE, GalleryTree, SideModel
from origenerator.gui.split_folder_tree import SplitFolderTree
from origenerator.orientation import base_of, side_of


def _row(prompt_id, workflow_name, params, filename):
    return {
        "prompt_id": prompt_id,
        "workflow_name": workflow_name,
        "workflow_version": "v1",
        "status": "completed",
        "source": "generated",
        "created_at": "2026-01-01",
        "params_json": json.dumps(params),
        "output_files": json.dumps([{"filename": filename, "subfolder": ""}]),
    }


def _image(prompt_id, prompt):
    return _row(prompt_id, "sdxl_t2i", {"positive_prompt": prompt, "steps": 30, "seed": 1},
                f"sdxl_t2i_{prompt_id}.png")


def _video(prompt_id, lora):
    return _row(prompt_id, "wan22_i2v",
                {"positive_prompt": "a slow turn", "seed": 1,
                 "unet_high": "example_high.safetensors", "unet_low": "example_low.safetensors",
                 "lora_high": f"{lora}_high.safetensors", "lora_low": f"{lora}_low.safetensors"},
                f"wan22_i2v_{prompt_id}.mp4")


def _folder_of_your_own(folder_id, name, holding=()):
    return gallery.CustomGroup(gallery.custom_folder_key(folder_id), name, list(holding),
                               folder_id=folder_id)


def _gallery_tree(qtbot, rows, folders_of_your_own=(), folder_meta=None):
    pane, tree, _model = _gathered_tree(qtbot, rows, lambda _model: folders_of_your_own,
                                        folder_meta)
    return pane, tree


def _gathered_tree(qtbot, rows, folders_of_your_own, folder_meta=None, recently_worked=()):
    """The list built from ``rows``, with the folders of your own that
    ``folders_of_your_own`` makes out of the Landscape side's folders."""
    model = gallery.build_gallery_tree(rows, folder_meta)
    pane = SplitFolderTree(GROUP_ROLE)
    qtbot.addWidget(pane)
    tree = GalleryTree(pane)
    tree.populate(
        [SideModel(LANDSCAPE, model, custom_folders=list(folders_of_your_own(model)),
                   show_recents=True),
         SideModel(PORTRAIT, [])],
        folder_meta=folder_meta, recently_worked=recently_worked)
    return pane, tree, model


def _table_of_contents(qtbot, rows, folders_of_your_own=(), folder_meta=None):
    """The Landscape half, built from ``rows`` and opened all the way down."""
    pane, _tree = _gallery_tree(qtbot, rows, folders_of_your_own, folder_meta)
    pane.resize(500, 1600)
    pane.show()
    qtbot.waitExposed(pane)
    half = pane._trees[LANDSCAPE]
    half.expandAll()
    return half


def _rows_by_depth(half):
    def walk(item, depth):
        yield depth, item
        for i in range(item.childCount()):
            yield from walk(item.child(i), depth + 1)

    root = half.invisibleRootItem()
    return [pair for i in range(root.childCount()) for pair in walk(root.child(i), 0)]


def _laid_out(half, item, element):
    index = half.indexFromItem(item)
    option = QStyleOptionViewItem()
    half.initViewItemOption(option)
    option.rect = half.visualRect(index)
    half.itemDelegate().initStyleOption(option, index)
    return half.style().subElementRect(element, option, half)


def _mark_left(half, item) -> int:
    return _laid_out(half, item, QStyle.SubElement.SE_ItemViewItemDecoration).left()


def _name_left(half, item) -> int:
    return _laid_out(half, item, QStyle.SubElement.SE_ItemViewItemText).left()


def test_every_row_of_a_level_wears_its_mark_in_one_column_and_its_name_in_the_next(qtbot):
    half = _table_of_contents(qtbot, [_image("i1", "a cat"), _video("v1", "style_a")],
                              [_folder_of_your_own(1, "Keepers")])
    marks, names = {}, {}

    for depth, item in _rows_by_depth(half):
        assert not item.icon(0).isNull(), item.text(0)
        marks.setdefault(depth, set()).add(_mark_left(half, item))
        names.setdefault(depth, set()).add(_name_left(half, item))

    assert sorted(marks) == [0, 1, 2, 3, 4, 5, 6]
    assert all(len(lefts) == 1 for lefts in marks.values()), marks
    assert all(len(lefts) == 1 for lefts in names.values()), names


def _wears(item, mark: str) -> bool:
    drawn = item.icon(0).pixmap(QSize(48, 48)).toImage()
    return drawn == glyph_pixmap(mark, 48, TEXT_PRIMARY).toImage()


def test_all_wears_the_database_and_its_latest_the_calendar(qtbot):
    half = _table_of_contents(qtbot, [_image("i1", "a cat")])
    (all_row,) = [half.topLevelItem(i) for i in range(half.topLevelItemCount())]
    latest = all_row.child(0)

    assert (all_row.text(0), latest.text(0)) == ("All", "Latest")
    assert _wears(all_row, "database")
    assert _wears(latest, "latest")


def _children(item):
    return [item.child(i) for i in range(item.childCount())]


_COLLECTIONS = ["Latest", "Favorites", "Experiments", "Requests", "Trash"]


def _leads_with_the_collections(folder) -> bool:
    *collections, _first_folder = _children(folder)[:6]
    return ([row.text(0) for row in collections] == _COLLECTIONS
            and all(row.data(0, GROUP_ROLE) is None for row in collections))


def test_all_leads_with_its_five_collections_then_images_then_videos(qtbot):
    half = _table_of_contents(qtbot, [_video("v1", "style_a"), _image("i1", "a cat")])
    (all_row,) = [half.topLevelItem(i) for i in range(half.topLevelItemCount())]

    assert [row.text(0) for row in _children(all_row)] == [*_COLLECTIONS, "Images", "Videos"]
    assert _leads_with_the_collections(all_row)


def test_images_and_videos_each_lead_with_five_collections_then_their_workflows(qtbot):
    half = _table_of_contents(qtbot, [_video("v1", "style_a"), _image("i1", "a cat")])
    (all_row,) = [half.topLevelItem(i) for i in range(half.topLevelItemCount())]

    for kind in _children(all_row)[5:]:
        assert _leads_with_the_collections(kind)
        assert [isinstance(row.data(0, GROUP_ROLE), gallery.WorkflowGroup)
                for row in _children(kind)[5:]] == [True]


def test_images_wear_the_photo_and_videos_the_play_mark_and_say_which_they_are(qtbot):
    half = _table_of_contents(qtbot, [_video("v1", "style_a"), _image("i1", "a cat")])
    (all_row,) = [half.topLevelItem(i) for i in range(half.topLevelItemCount())]
    *_collections, images, videos = _children(all_row)

    assert _wears(images, "photo") and images.toolTip(0) == "Images"
    assert _wears(videos, "play") and videos.toolTip(0) == "Videos"


def test_a_kind_folder_given_a_name_still_says_which_kind_it_holds(qtbot):
    half = _table_of_contents(qtbot, [_image("i1", "a cat")],
                              folder_meta={"image": {"custom_name": "Stills"}})
    (all_row,) = [half.topLevelItem(i) for i in range(half.topLevelItemCount())]
    *_collections, images = _children(all_row)

    assert (images.text(0), images.toolTip(0)) == ("Stills", "Stills · Images")


def _folders_holding(half, workflow_name):
    return [item for _depth, item in _rows_by_depth(half)
            if isinstance(group := item.data(0, GROUP_ROLE), gallery.SettingsGroup)
            and group.rows[0]["workflow_name"] == workflow_name]


def test_a_folder_of_images_wears_the_photo_and_a_folder_of_videos_the_play_mark(qtbot):
    half = _table_of_contents(qtbot, [_image("i1", "a cat"), _video("v1", "style_a")])
    (images,) = _folders_holding(half, "sdxl_t2i")
    (videos,) = _folders_holding(half, "wan22_i2v")

    assert _wears(images, "photo")
    assert _wears(videos, "play")


def _first_frame(prompt_id):
    return _row(prompt_id, "wan22_i2v", {"positive_prompt": "a slow turn", "seed": 1},
                f"renamed_{prompt_id}.png")


def test_every_row_is_found_again_by_the_path_it_shows(qtbot):
    _pane, tree, _model = _gathered_tree(
        qtbot, [_image("i1", "a cat"), _video("v1", "style_a"), _first_frame("f1")],
        _keepers_holding_the_images)
    rows = tree.item_by_key

    assert len({tree.breadcrumb(row) for row in rows.values()}) == len(rows) > 30
    for key, row in rows.items():
        assert tree.key_at_path(tree.breadcrumb(row)) == key, tree.breadcrumb(row)


def test_a_path_is_found_whatever_its_spacing_or_capitals(qtbot):
    _pane, tree = _gallery_tree(qtbot, [_image("i1", "a cat")])
    latest = tree.key_at_path("Landscape  ›  All  ›  Latest")

    assert latest is not None
    assert tree.key_at_path(" landscape ›all›   LATEST ") == latest


def test_a_path_no_row_has_finds_nothing(qtbot):
    _pane, tree = _gallery_tree(qtbot, [_image("i1", "a cat")])

    for path in ("", "Landscape", "Landscape  ›  All  ›  Nowhere",
                 "Sideways  ›  All", "All  ›  Latest", "Landscape  ›  Latest"):
        assert tree.key_at_path(path) is None, path


def _drawn_down(row):
    return [row.text(0), [_drawn_down(child) for child in _children(row)]]


def _keepers_holding_the_images(model):
    return [_folder_of_your_own(1, "Keepers", [model[0]])]


def test_a_folder_of_your_own_shows_the_folders_it_holds_as_they_show_in_their_own_place(qtbot):
    pane, tree, model = _gathered_tree(qtbot, [_image("i1", "a cat"), _image("i2", "a dog")],
                                       _keepers_holding_the_images)
    keepers = pane._trees[LANDSCAPE].topLevelItem(0)
    all_row = pane._trees[LANDSCAPE].topLevelItem(1)
    images = next(row for row in _children(all_row) if row.data(0, GROUP_ROLE) is model[0])

    assert [_drawn_down(row) for row in _children(keepers)] == [_drawn_down(images)]


def test_every_row_inside_a_folder_of_your_own_has_a_key_of_its_own_naming_its_folder(qtbot):
    pane, tree, _model = _gathered_tree(qtbot, [_image("i1", "a cat"), _image("i2", "a dog")],
                                        _keepers_holding_the_images)
    rows = [row for _depth, row in _rows_by_depth(pane._trees[LANDSCAPE])]
    keys = [row.data(0, TREE_KEY_ROLE) for row in rows]

    assert len(set(keys)) == len(keys)
    assert all(tree.item_by_key[key] is row for key, row in zip(keys, rows))
    assert all(side_of(key) == LANDSCAPE for key in keys)
    assert all(base_of(key) == row.data(0, GROUP_ROLE).key
               for key, row in zip(keys, rows) if row.data(0, GROUP_ROLE) is not None)


def test_an_item_belongs_to_its_folder_in_its_own_place_not_to_a_copy_of_it(qtbot):
    _pane, tree, _model = _gathered_tree(qtbot, [_image("i1", "a cat")],
                                         _keepers_holding_the_images)

    assert tree.breadcrumb(tree.leaf_by_id["i1"]).startswith("Landscape  ›  All  ›  ")


def _outer_holding_inner_holding_the_images(model):
    inner = _folder_of_your_own(2, "Inner", [model[0]])
    return [_folder_of_your_own(1, "Outer", [inner]), inner]


def test_a_folder_of_your_own_inside_another_shows_under_it_as_it_shows_on_its_own(qtbot):
    pane, _tree, _model = _gathered_tree(qtbot, [_image("i1", "a cat")],
                                         _outer_holding_inner_holding_the_images)
    half = pane._trees[LANDSCAPE]
    outer, inner = half.topLevelItem(0), half.topLevelItem(1)
    (inner_inside_outer,) = _children(outer)

    assert _drawn_down(inner_inside_outer) == _drawn_down(inner)
    assert inner_inside_outer.data(0, DROP_KEY_ROLE) == inner.data(0, DROP_KEY_ROLE)
    assert inner_inside_outer.toolTip(0) == inner.toolTip(0)


def test_a_folder_drawn_again_inside_a_folder_of_your_own_is_found_first_in_its_own_place(qtbot):
    _pane, tree, model = _gathered_tree(qtbot, [_image("i1", "a cat")],
                                        _keepers_holding_the_images)
    own, again = tree.keys_for_folder(model[0].key)

    assert tree.breadcrumb(tree.item_by_key[own]) == "Landscape  ›  All  ›  Images"
    assert tree.breadcrumb(tree.item_by_key[again]) == "Landscape  ›  Keepers  ›  Images"


def test_a_folder_worked_in_lately_wears_its_mark_inside_a_folder_of_your_own_too(qtbot):
    rows = [_image("i1", "a cat")]
    leaf_key = gallery.settings_folder_key(rows[0], {})
    _pane, tree, _model = _gathered_tree(qtbot, rows, _keepers_holding_the_images,
                                         recently_worked=[(LANDSCAPE, leaf_key)])

    marked = [tree.breadcrumb(row) for row in tree.item_by_key.values()
              if row.data(0, RECENT_ROLE)]
    assert [path.split("  ›  ")[1] for path in marked] == ["All", "Keepers"]


def test_a_folder_left_open_inside_a_folder_of_your_own_is_open_again_after_a_rebuild(qtbot):
    pane, tree, model = _gathered_tree(qtbot, [_image("i1", "a cat")],
                                       _keepers_holding_the_images)
    own, again = tree.keys_for_folder(model[0].key)
    tree.item_by_key[again].setExpanded(True)

    tree.populate([SideModel(LANDSCAPE, model, custom_folders=_keepers_holding_the_images(model)),
                   SideModel(PORTRAIT, [])])

    assert tree.item_by_key[again].isExpanded()
    assert not tree.item_by_key[own].isExpanded()
