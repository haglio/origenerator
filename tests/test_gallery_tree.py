"""The rows of the table of contents: where each one wears its mark."""
from __future__ import annotations

import json

from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QStyle, QStyleOptionViewItem
from shared_ui.colors import TEXT_PRIMARY
from shared_ui.icons import glyph_pixmap

from origenerator import gallery
from origenerator.gallery.sides import LANDSCAPE, PORTRAIT
from origenerator.gui.gallery_tree import GROUP_ROLE, GalleryTree, SideModel
from origenerator.gui.split_folder_tree import SplitFolderTree


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


def _video(prompt_id, add_on):
    return _row(prompt_id, "wan22_i2v",
                {"positive_prompt": "a slow turn", "seed": 1,
                 "unet_high": "example_high.safetensors", "unet_low": "example_low.safetensors",
                 "lora_high": f"{add_on}_high.safetensors", "lora_low": f"{add_on}_low.safetensors"},
                f"wan22_i2v_{prompt_id}.mp4")


def _folder_of_your_own(folder_id, name):
    return gallery.CustomGroup(gallery.custom_folder_key(folder_id), name, [],
                               folder_id=folder_id)


def _table_of_contents(qtbot, rows, folders_of_your_own=()):
    """The Landscape half, built from ``rows`` and opened all the way down."""
    pane = SplitFolderTree(GROUP_ROLE)
    qtbot.addWidget(pane)
    GalleryTree(pane).populate(
        [SideModel(LANDSCAPE, gallery.build_gallery_tree(rows),
                   custom_folders=list(folders_of_your_own), show_recents=True),
         SideModel(PORTRAIT, [])],
        expanded_keys=())
    pane.resize(500, 1600)
    pane.show()
    qtbot.waitExposed(pane)
    half = pane._halves[LANDSCAPE]
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


def _holds_images_and_videos(item) -> bool:
    return isinstance(item.data(0, GROUP_ROLE), gallery.SettingsGroup)


def test_every_row_of_a_level_wears_its_mark_in_one_column_and_its_name_in_the_next(qtbot):
    half = _table_of_contents(qtbot, [_image("i1", "a cat"), _video("v1", "style_a")],
                              [_folder_of_your_own(1, "Keepers")])
    marks, names = {}, {}

    for depth, item in _rows_by_depth(half):
        if _holds_images_and_videos(item):
            continue
        assert not item.icon(0).isNull(), item.text(0)
        marks.setdefault(depth, set()).add(_mark_left(half, item))
        names.setdefault(depth, set()).add(_name_left(half, item))

    assert sorted(marks) == [0, 1, 2, 3, 4, 5]
    assert all(len(lefts) == 1 for lefts in marks.values()), marks
    assert all(len(lefts) == 1 for lefts in names.values()), names


def _wears(item, mark: str) -> bool:
    drawn = item.icon(0).pixmap(QSize(48, 48)).toImage()
    return drawn == glyph_pixmap(mark, 48, TEXT_PRIMARY).toImage()


def test_all_wears_the_database(qtbot):
    half = _table_of_contents(qtbot, [_image("i1", "a cat")])
    (all_row,) = [half.topLevelItem(i) for i in range(half.topLevelItemCount())]

    assert all_row.text(0) == "All"
    assert _wears(all_row, "database")
