"""The rows of the tree of contents: where each one wears its mark."""
from __future__ import annotations

import json

from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QStyle, QStyleOptionViewItem
from shared_ui.colors import TEXT_PRIMARY
from shared_ui.icons import glyph_pixmap

from origenerator import gallery
from origenerator.gallery.sides import LANDSCAPE, PORTRAIT, SIDE_LABELS
from origenerator.gui import icons
from origenerator.gui.folder_tree import DROP_KEY_ROLE, RECENT_ROLE, TREE_KEY_ROLE
from origenerator.gui.gallery_tree import (
    GROUP_ROLE,
    PATH_SEPARATOR,
    GalleryTree,
    PathStep,
    SideModel,
)
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
                   show_latest=True),
         SideModel(PORTRAIT, [])],
        folder_meta=folder_meta, recently_worked=recently_worked)
    return pane, tree, model


def _table_of_contents(qtbot, rows, folders_of_your_own=(), folder_meta=None):
    """The Landscape half, built from ``rows`` and opened all the way down."""
    pane, _tree = _gallery_tree(qtbot, rows, folders_of_your_own, folder_meta)
    pane.resize(500, 1600)
    with qtbot.waitExposed(pane):
        pane.show()
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


_COLLECTIONS = ["Latest", "Favorites", "Enhanced", "Experiments", "Trash"]
_COLLECTIONS_OF_VIDEOS = [name for name in _COLLECTIONS if name != "Enhanced"]


def _leads_with(folder, collections) -> bool:
    *rows, _first_folder = _children(folder)[:len(collections) + 1]
    return ([row.text(0) for row in rows] == collections
            and all(row.data(0, GROUP_ROLE) is None for row in rows))


def test_all_leads_with_its_five_collections_then_images_then_videos(qtbot):
    half = _table_of_contents(qtbot, [_video("v1", "style_a"), _image("i1", "a cat")])
    (all_row,) = [half.topLevelItem(i) for i in range(half.topLevelItemCount())]

    assert [row.text(0) for row in _children(all_row)] == [*_COLLECTIONS, "Images", "Videos"]
    assert _leads_with(all_row, _COLLECTIONS)


def test_images_lead_with_the_five_and_videos_with_all_but_enhanced_then_their_workflows(qtbot):
    half = _table_of_contents(qtbot, [_video("v1", "style_a"), _image("i1", "a cat")])
    (all_row,) = [half.topLevelItem(i) for i in range(half.topLevelItemCount())]
    images, videos = _children(all_row)[len(_COLLECTIONS):]

    for kind, collections in ((images, _COLLECTIONS), (videos, _COLLECTIONS_OF_VIDEOS)):
        assert _leads_with(kind, collections)
        assert [isinstance(row.data(0, GROUP_ROLE), gallery.WorkflowGroup)
                for row in _children(kind)[len(collections):]] == [True]


def test_enhanced_wears_the_plus_an_enhanced_image_wears_and_says_what_it_holds(qtbot):
    half = _table_of_contents(qtbot, [_image("i1", "a cat")])
    (all_row,) = [half.topLevelItem(i) for i in range(half.topLevelItemCount())]
    (enhanced,) = [row for row in _children(all_row) if row.text(0) == "Enhanced"]
    size = QSize(48, 48)

    assert enhanced.icon(0).pixmap(size).toImage() == icons.enhance_icon().pixmap(size).toImage()
    assert enhanced.toolTip(0) == "Your enhanced images"


def test_every_folder_of_images_leads_with_an_enhanced_and_no_folder_of_videos_does(qtbot):
    half = _table_of_contents(qtbot, [_video("v1", "style_a"), _image("i1", "a cat")])
    folders = [item for _depth, item in _rows_by_depth(half)
               if item.data(0, GROUP_ROLE) is not None
               and not isinstance(item.data(0, GROUP_ROLE), gallery.SettingsGroup)]
    kinds_seen = set()

    for folder in folders:
        collections = [row.text(0) for row in _children(folder)
                       if row.data(0, GROUP_ROLE) is None]
        inside_videos = base_of(folder.data(0, TREE_KEY_ROLE)).startswith("video")
        assert ("Enhanced" in collections) is not inside_videos, folder.text(0)
        kinds_seen.add(inside_videos)
    assert kinds_seen == {True, False}


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


def _rows_down_to(row):
    held_by = []
    while row is not None:
        held_by.append(row)
        row = row.parent()
    return held_by[::-1]


def test_a_rows_path_steps_from_its_side_down_through_every_row_holding_it(qtbot):
    _pane, tree, _model = _gathered_tree(
        qtbot, [_image("i1", "a cat"), _video("v1", "style_a"), _first_frame("f1")],
        _keepers_holding_the_images)

    for key, row in tree.item_by_key.items():
        side, *steps = tree.path_steps(row)
        assert side == PathStep(SIDE_LABELS[side_of(key)], None)
        assert [step.key for step in steps] == [
            held.data(0, TREE_KEY_ROLE) for held in _rows_down_to(row)]
        assert tree.breadcrumb(row) == PATH_SEPARATOR.join(
            step.name for step in (side, *steps))


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
    return gallery.outermost([_folder_of_your_own(1, "Outer", [inner]), inner])


def test_a_folder_of_your_own_inside_another_shows_under_it_with_what_it_holds(qtbot):
    pane, _tree, model = _gathered_tree(qtbot, [_image("i1", "a cat")],
                                        _outer_holding_inner_holding_the_images)
    half = pane._trees[LANDSCAPE]
    outer, all_row = (half.topLevelItem(i) for i in range(half.topLevelItemCount()))
    (inner,) = _children(outer)
    images = next(row for row in _children(all_row) if row.data(0, GROUP_ROLE) is model[0])

    assert [_drawn_down(row) for row in _children(inner)] == [_drawn_down(images)]
    assert inner.data(0, DROP_KEY_ROLE) == gallery.custom_folder_key(2)


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
