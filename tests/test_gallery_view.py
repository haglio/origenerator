from __future__ import annotations

import json
import re
import threading
from itertools import pairwise
from unittest.mock import MagicMock

import pytest
from PyQt6 import sip
from PyQt6.QtCore import (
    QEvent,
    QMargins,
    QPoint,
    Qt,
    QTimer,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QLabel,
    QScrollArea,
    QSplitter,
    QWidget,
)
from shared_ui import folder_path as shared_folder_path
from shared_ui.colors import TEXT_PRIMARY
from shared_ui.icons import icon_then_text
from shared_ui.spacing import MARGIN_STANDARD

from origenerator import (
    gallery,
    outside_videos,
)
from origenerator.branch_session import ENV_FLAG
from origenerator.comfyui_client import ComfyUIClient, ForeignQueue
from origenerator.db import Database
from origenerator.gallery import tree as gallery_tree_module
from origenerator.gallery.collection import (
    ENHANCED_KEY,
    EXPERIMENTS_KEY,
    FAVORITES_KEY,
)
from origenerator.gallery.labels import workflow_label
from origenerator.gallery.sides import LANDSCAPE, PORTRAIT, SIDE_LABELS
from origenerator.gallery_actions import GalleryActions
from origenerator.generation_state import GenerationSource
from origenerator.gui import (
    corner_buttons,
    icons,
    off_thread,
)
from origenerator.gui import gallery_view as gallery_view_module
from origenerator.gui.folder_tile import FolderTile
from origenerator.gui.folder_tree import RECENT_ROLE
from origenerator.gui.gallery_view import _GROUP_ROLE, GalleryView
from origenerator.orientation import oriented_key
from origenerator.output_places import OutputPlaces
from origenerator.trash import Trash
from tests import gestures
from tests.comfyui_folders import SUITE_FOLDERS
from tests.gallery_view_support import (
    FakeActions,
    FakeDB,
    _alls,
    _answer_menu,
    _at,
    _children_by_prompt,
    _click_beside_the_mark_of,
    _click_off,
    _click_tile,
    _collection,
    _collection_row,
    _drawn,
    _enhanceable_db,
    _enhanced_image,
    _experiment_row,
    _FakeRerollJob,
    _i2v_video,
    _image,
    _image_workflow,
    _in_view,
    _key,
    _make_folder,
    _menu_labels,
    _of_both_kinds,
    _on_screen,
    _pane_holding,
    _pick,
    _reroll_client,
    _resolve_by_id,
    _right_click,
    _row,
    _running_row,
    _scroll_bar,
    _search_for,
    _select_first_leaf,
    _selected_folder,
    _side,
    _SignalMotion,
    _single_i2v_db,
    _subs,
    _top_level,
    _trash_db,
    _tree_menu,
    _two_leaf_view,
    _video_workflow,
    _workflow_rows,
)
from tests.test_folder_tree import _shown

pytestmark = pytest.mark.usefixtures("_stub_preview_resolution")


_COLLECTION_NAMES = ["Latest", "Favorites", "Enhanced", "Experiments", "Trash"]


_COLLECTION_NAMES_OF_VIDEOS = [name for name in _COLLECTION_NAMES if name != "Enhanced"]


def _collection_names(item):
    """The collections a folder leads with, in order — none of them a folder."""
    names = []
    for i in range(item.childCount()):
        if item.child(i).data(0, _GROUP_ROLE) is not None:
            break
        names.append(item.child(i).text(0))
    return names


def test_refresh_builds_workflow_model_settings_tree(qtbot):
    rows = [
        _image("i1", "a cat", 50, 1),
        _image("i2", "a cat", 50, 2),  # same settings, different seed
        _row("v1", "wan22_i2v", {"positive_prompt": "dance", "seed": 5},
             "wan22_i2v_00001_.mp4"),
    ]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    top = _top_level(view._tree)
    assert set(top) == {"All"}
    assert _collection_names(top["All"]) == _COLLECTION_NAMES
    assert set(_workflow_rows(view._tree)) == {"SDXL T2I", "WAN 2.2 I2V"}

    workflow_node = _image_workflow(view._tree)
    assert workflow_node.text(0) == "SDXL T2I"
    # workflow -> one model -> its "(no LoRA)" level -> one settings folder, into
    # which the two seed variants collapse.
    assert len(_subs(workflow_node)) == 1           # one model
    assert len(_subs(_at(workflow_node, 0))) == 1   # its single "(no LoRA)" level
    assert len(_subs(_at(workflow_node, 0, 0))) == 1  # the two seeds collapse


def test_every_folder_of_folders_leads_with_collections_of_its_own(qtbot):
    view = GalleryView(FakeDB([_i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()
    workflow = _video_workflow(view._tree)
    model, lora, source = (_at(workflow, *[0] * depth) for depth in (1, 2, 3))

    for folder in (_alls(view._tree)["Videos"], workflow, model, lora, source):
        assert _collection_names(folder) == _COLLECTION_NAMES_OF_VIDEOS
    assert _at(source, 0).childCount() == 0


def test_the_tree_marks_the_folders_the_model_says_were_worked_in_lately(qtbot, monkeypatch):
    # Folders no longer float up when a generation lands in one, so the mark is
    # what is left to say where the work has lately been. Which folders those
    # are is the gallery model's answer; the tree's job is to wear it.
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    asked = []

    def fake(trees, rows, *args, **kwargs):
        asked.append((sorted(trees), [row["prompt_id"] for row in rows]))
        return {(LANDSCAPE, "image/sdxl_t2i")}

    monkeypatch.setattr(gallery, "recently_worked_folders", fake)
    view.refresh()

    # The sides drawn, and the listed rows. The marks belong to the one list of
    # both shapes as much as to each shape's own, so choosing Together asks for
    # them again -- for that list, which is the only one on screen then.
    assert asked == [([LANDSCAPE, "portrait"], ["i1"])]

    view._tree.together_button.click()

    assert asked[-1] == (["both"], ["i1"])
    view._tree.separate_button.click()
    workflow = _image_workflow(view._tree)
    assert workflow.data(0, RECENT_ROLE)
    assert "worked in recently" in workflow.toolTip(0)   # so the mark says what it means
    assert not _at(workflow, 0).data(0, RECENT_ROLE)    # and nothing the model left out


def test_tree_rows_carry_a_toc_initial(qtbot):
    view = GalleryView(FakeDB([_i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()

    workflow = _video_workflow(view._tree)
    model = _at(workflow, 0)
    lora = _at(model, 0)
    source = _at(lora, 0)
    settings = _at(source, 0)

    # Each level carries a ground as its row icon — right of the caret, reading as
    # the first character of the folder's name — and names itself in the tooltip.
    assert not workflow.icon(0).isNull()
    assert "Workflow" in workflow.toolTip(0)
    assert not model.icon(0).isNull()
    assert "Model" in model.toolTip(0)
    assert not lora.icon(0).isNull()
    assert lora.toolTip(0).endswith("· LoRA")
    assert not source.icon(0).isNull()
    assert "Source Image" in source.toolTip(0)
    # ...and the settings leaf, where the generations live, names no level at
    # all, so its hover says its own name and nothing more.
    assert settings.toolTip(0).startswith(settings.text(0))
    assert "dance" not in settings.toolTip(0)


def test_every_folder_leads_with_how_many_items_are_under_it(qtbot):
    view = GalleryView(FakeDB([
        _image("i1", "a cat", 50, 1),
        _image("i2", "a cat", 50, 2),
        _image("i3", "a dog", 50, 1),
        _i2v_video("v1", "styleA"),
    ]))
    qtbot.addWidget(view)
    view.refresh()

    workflow = _image_workflow(view._tree)
    lora = _at(workflow, 0, 0)
    by_prompt = _children_by_prompt(lora)
    cat, dog = by_prompt["a cat"], by_prompt["a dog"]
    source = _at(_video_workflow(view._tree), 0, 0, 0)

    assert _shown(_top_level(view._tree)["All"]) == "(4) All"
    assert _shown(workflow) == f"(3) {workflow.text(0)}"
    assert _shown(lora) == f"(3) {lora.text(0)}"
    assert _shown(cat) == f"(2) {cat.text(0)}"
    assert _shown(dog) == f"(1) {dog.text(0)}"
    assert _shown(source) == f"(1) {source.text(0)}"


def test_a_videos_source_folder_in_the_toc_wears_its_images_name(qtbot):
    image = _image("i1", "a cat", 50, 1)
    video = _row("v1", "wan22_i2v", {"positive_prompt": "dance", "seed": 5,
                                     "input_image": "sdxl_t2i_i1.png"},
                 "wan22_i2v_00001_.mp4")
    view = GalleryView(FakeDB([video, image]))
    qtbot.addWidget(view)
    view.refresh()

    source = _at(_video_workflow(view._tree), 0, 0, 0)

    assert source.text(0) == f"{gallery.folder_id(gallery.settings_folder_key(image))} 000"


def test_every_tree_level_steps_by_one_caret_width(qtbot):
    # The tree is six levels deep by the time it reaches a settings folder and it
    # lives in the window's narrowest column, so every wasted pixel per level is
    # six wasted at the foot. Each step is one indentation and no more.
    #
    # Measured at the left edge of each row's *name block* — its ground when it has
    # one, its text when it does not — because the ground reads as the first
    # character of the name. Qt lays the text out after the icon, so the text
    # alone would step unevenly wherever a initialed row meets an uninitialed one.
    rows = [_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]
    view = GalleryView(FakeDB(rows))
    _on_screen(qtbot, view, 1200, 800)
    tree = _side(view._tree)  # one half; both are the same widget class
    step = tree.indentation()
    assert step <= 16   # a caret's width, not the platform's roomy default

    def name_x(item):
        return tree.visualRect(tree.indexFromItem(item)).left()

    def walk(item, depth):
        item.setExpanded(True)
        yield depth, item
        for i in range(item.childCount()):
            yield from walk(item.child(i), depth + 1)

    root = tree.invisibleRootItem()
    rows_by_depth = [pair for i in range(root.childCount())
                     for pair in walk(root.child(i), 0)]
    starts = {}
    for depth, item in rows_by_depth:
        starts.setdefault(depth, set()).add(name_x(item))
    # One name position per depth — every row of a level lines up with its
    # siblings, collections and folders alike...
    assert all(len(xs) == 1 for xs in starts.values()), starts
    # ...and each level sits exactly one indentation right of the one above.
    at = [next(iter(starts[d])) for d in sorted(starts)]
    assert [b - a for a, b in pairwise(at)] == [step] * (len(at) - 1)


def test_selecting_a_folder_shows_its_full_name_as_a_title(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    workflow = _image_workflow(view._tree)
    view._tree.setCurrentItem(workflow)
    # The title carries the full folder path, which the narrow tree truncates.
    assert "SDXL T2I" in view._folder_path.display_text()
    assert "All" in view._folder_path.display_text()


def test_a_folder_of_images_wears_the_photo_mark_on_its_square_as_on_its_row(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    lora = _at(_image_workflow(view._tree), 0, 0)

    view._tree.setCurrentItem(lora)

    (square,) = [tile for tile in view._scroll.widget().findChildren(FolderTile)
                 if tile.key == _key(_at(lora, 0))]
    assert any(label.toolTip() == "Images" for label in square.findChildren(QLabel))


def test_the_latest_square_wears_the_calendar_its_row_wears(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_top_level(view._tree)["All"])

    (square,) = [tile for tile in view._scroll.widget().findChildren(FolderTile)
                 if tile._text == "Latest"]
    (mark,) = [label for label in square.findChildren(QLabel)
               if label.toolTip() == "Latest" and not label.pixmap().isNull()]
    size = mark.pixmap().size()
    assert mark.pixmap().toImage() == icons.latest_icon().pixmap(size).toImage()


def test_branch_shows_folder_tiles_and_leaf_shows_thumbnails(qtbot):
    rows = [
        _image("i1", "a cat", 50, 1),
        _image("i2", "a cat", 50, 2),
        _image("i3", "a dog", 50, 1),
    ]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    lora = _at(_image_workflow(view._tree), 0, 0)  # "(no LoRA)"
    # A branch folder shows its sub-folders as tiles, not loose thumbnails.
    view._tree.setCurrentItem(lora)
    assert len(view._gallery_pane._listed_folders) == 2
    assert view.listed_prompt_ids() == []

    # A leaf (settings) folder shows the actual item thumbnails.
    cat_leaf = _at(lora, 0)
    view._tree.setCurrentItem(cat_leaf)
    assert set(view.listed_prompt_ids()) == {"i1", "i2"}
    assert view._gallery_pane._listed_folders == []


def _square_names(view):
    return [tile._text for tile in view._scroll.widget().findChildren(FolderTile)]


def test_a_folder_of_folders_shows_its_collections_as_squares_before_its_folders(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    lora = _at(_image_workflow(view._tree), 0, 0)

    view._tree.setCurrentItem(lora)

    assert _square_names(view) == [*_COLLECTION_NAMES, *(row.text(0) for row in _subs(lora))]


def test_clicking_a_collection_square_opens_that_folders_collection(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    workflow = _image_workflow(view._tree)
    view._tree.setCurrentItem(workflow)
    (trash,) = [tile for tile in view._scroll.widget().findChildren(FolderTile)
                if tile._text == "Trash"]

    trash.clicked.emit(trash.key)

    assert view._tree.currentItem() is _collection_row(workflow, "Trash")


def test_clicking_a_folder_tile_drills_into_it(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    lora = _at(_image_workflow(view._tree), 0, 0)  # "(no LoRA)"
    view._tree.setCurrentItem(lora)
    a_tile_key = view._gallery_pane._listed_folders[0]  # a settings tile under the LoRA folder

    view._gallery_pane._drill_into(a_tile_key)  # same path the tile's clicked signal triggers
    assert view.listed_prompt_ids()  # now showing that folder's thumbnails


def test_opening_a_folder_lands_on_its_first_item(qtbot):
    # Picking a folder is picking what is in it: the first tile lands selected
    # and on the form, so a folder opens ready to work in rather than beside
    # whatever the tab in front happened to be holding.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._leaf_by_id["i1"])

    assert view.listed_prompt_ids()[0] == "i1"
    assert view.selected_generation() == "i1"
    assert view.selected_prompt_ids() == ["i1"]   # the tile itself, highlighted
    panel = view._info_tabs.current_config_panel()
    assert panel.displayed_row()["prompt_id"] == "i1"
    # Italic, so the next thing opened takes it over rather than piling up
    # a tab per folder walked through.
    assert view._info_tabs._preview_panel is panel


def _first_leaf(view):
    """The first settings folder in the tree — the one tier a name of your own
    can go on, since its own name is a generic code."""
    return _at(_image_workflow(view._tree), 0, 0, 0)


def test_the_all_row_holds_images_and_videos_and_is_where_the_gallery_lands(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    all_row = _top_level(view._tree)["All"]
    assert [row.text(0) for row in _subs(all_row)] == ["Images", "Videos"]
    assert all_row.isExpanded()   # shut, it would be a tree with nothing in it
    assert view._tree.currentItem() is all_row


def test_each_side_grows_a_folder_for_a_kind_only_where_it_holds_that_kind(qtbot):
    tall_image = _row("i1", "sdxl_t2i", {"positive_prompt": "a cat", "seed": 1,
                                         "width": 100, "height": 200}, "sdxl_t2i_i1.png")
    wide_video = _row("v1", "wan22_i2v", {"positive_prompt": "a cat", "seed": 5},
                      "wan22_i2v_00001_.mp4")
    view = GalleryView(FakeDB([tall_image, wide_video]))
    qtbot.addWidget(view)
    view.refresh()

    assert [row.text(0) for row in _subs(_top_level(view._tree, PORTRAIT)["All"])] == ["Images"]
    assert [row.text(0) for row in _subs(_top_level(view._tree, LANDSCAPE)["All"])] == ["Videos"]


def test_clicking_videos_in_the_path_goes_to_the_videos(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_video_workflow(view._tree))

    _click_path_step(view, "Videos")

    assert view._tree.currentItem() is _alls(view._tree)["Videos"]


def test_a_slideshow_started_on_videos_plays_the_videos_alone(qtbot):
    view = _of_both_kinds(qtbot)
    view._tree.setCurrentItem(_alls(view._tree)["Videos"])

    assert [row["prompt_id"] for row in view.rows_to_play()] == ["v1"]
    assert [row["prompt_id"]
            for row in view._slideshows.rows_at(view.slideshow_location())] == ["v1"]


def test_all_shows_its_collections_then_images_and_videos_as_squares(qtbot):
    view = _of_both_kinds(qtbot)

    view._tree.setCurrentItem(_top_level(view._tree)["All"])

    assert _square_names(view) == [*_COLLECTION_NAMES, "Images", "Videos"]
    (square,) = [tile for tile in view._scroll.widget().findChildren(FolderTile)
                 if tile.key == "image"]
    (mark,) = [label for label in square.findChildren(QLabel)
               if label.toolTip() == "Images" and not label.pixmap().isNull()]
    size = mark.pixmap().size()
    assert mark.pixmap().toImage() == icons.media_type_icon("image").pixmap(size).toImage()


def _both_kinds_in_every_collection():
    """An image and a video in each collection both kinds have: both favorited, an
    experiment of each kind, and one of each deleted."""
    image, video = _image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")
    image["starred"] = video["starred"] = 1
    return _trash_db(rows=[image, video,
                         {**_image("ie", "a dog", 50, 2), "source": "experiment"},
                         {**_i2v_video("ve", "styleB"), "source": "experiment"}],
                   held=[("di", _image("di", "a bird", 50, 3)),
                         ("dv", _i2v_video("dv", "styleC"))])


@pytest.mark.parametrize("collection", _COLLECTION_NAMES_OF_VIDEOS)
def test_each_kinds_collection_lists_that_kind_alone(qtbot, collection):
    view = GalleryView(_both_kinds_in_every_collection())
    qtbot.addWidget(view)
    view.refresh()

    listed = {}
    for kind in ("Images", "Videos"):
        view._tree.setCurrentItem(_collection_row(_alls(view._tree)[kind], collection))
        listed[kind] = {gallery.media_type_of_row(view.row_for(prompt_id))
                        for prompt_id in view.listed_prompt_ids()}

    assert listed == {"Images": {"image"}, "Videos": {"video"}}


def test_each_kinds_collections_count_that_kind_alone(qtbot):
    view = GalleryView(_both_kinds_in_every_collection())
    qtbot.addWidget(view)
    view.refresh()

    for kind in ("Images", "Videos"):
        assert [_shown(_collection_row(_alls(view._tree)[kind], name))
                for name in _COLLECTION_NAMES_OF_VIDEOS[1:]] == [
            "(1) Favorites", "(1) Experiments", "(1) Trash"]


def test_images_shows_its_collections_then_its_workflow_folders_as_squares(qtbot):
    view = _of_both_kinds(qtbot)

    view._tree.setCurrentItem(_alls(view._tree)["Images"])

    assert _square_names(view) == [*_COLLECTION_NAMES, "SDXL T2I"]


def test_videos_once_favorited_is_a_square_in_alls_favorites(qtbot, monkeypatch):
    view = _of_both_kinds(qtbot)
    _answer_menu(monkeypatch, "Favorite")

    _tree_menu(view, "video")
    view._tree.setCurrentItem(_alls(view._tree)["Favorites"])

    assert _square_names(view) == ["Videos"]


def test_a_folder_of_your_own_can_gather_the_videos_whole(qtbot):
    view = _of_both_kinds(qtbot)

    _make_folder(view, "Clips", ["video"])
    view._tree.setCurrentItem(_top_level(view._tree)["Clips"])

    assert _square_names(view) == ["Videos"]
    assert [row["prompt_id"] for row in view.rows_to_play()] == ["v1"]


def test_images_and_videos_offer_on_their_menus_what_all_offers(qtbot, monkeypatch):
    view = _of_both_kinds(qtbot)
    menus = []
    for key in (gallery.ALL_KEY, "image", "video"):
        labels = []
        _menu_labels(monkeypatch, labels)
        _tree_menu(view, key)
        menus.append(labels)

    assert menus == [["Copy name", "", "Favorite", "", "Collapse all", "Expand all"]] * 3


def test_the_delete_key_on_images_deletes_nothing(qtbot):
    actions = FakeActions()
    view = _of_both_kinds(qtbot, actions)
    view._tree.setCurrentItem(_alls(view._tree)["Images"])
    view._confirm = lambda text: True

    view._delete_selection()

    assert actions.deleted == []


def test_images_lend_no_one_workflows_time_when_nothing_in_them_was_timed(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.recent_durations = lambda workflow_name, limit=10: [600.0]
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_alls(view._tree)["Images"])

    assert view._avg_label.text() == ""


def test_a_folders_collection_row_counts_what_that_folder_holds(qtbot):
    view = GalleryView(_trash_db(rows=[_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")],
                               held=[("d1", _image("d1", "a cat", 50, 2))]))
    qtbot.addWidget(view)
    view.refresh()

    assert _shown(_collection_row(_image_workflow(view._tree), "Trash")) == "(1) Trash"
    assert _shown(_collection_row(_video_workflow(view._tree), "Trash")) == "Trash"


def test_an_enhanced_image_counts_on_the_enhanced_of_every_folder_above_it(qtbot):
    view = GalleryView(FakeDB([_enhanced_image("i1", "a cat", 50, 1),
                               _image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()

    for folder in (_top_level(view._tree)["All"], _alls(view._tree)["Images"],
                   _image_workflow(view._tree)):
        assert _shown(_collection_row(folder, "Enhanced")) == "(1) Enhanced"


def test_starring_an_image_counts_it_on_the_favorites_of_every_folder_above_it(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()

    view.set_items_favorite(["i1"], True)

    assert _shown(_collection_row(_at(_image_workflow(view._tree), 0), "Favorites")) == "(1) Favorites"
    assert _shown(_collection_row(_video_workflow(view._tree), "Favorites")) == "Favorites"


def test_starring_another_sources_video_tells_fun_time_through_the_journal(qtbot, tmp_path,
                                                                          monkeypatch):
    video = {"prompt_id": "o1", "source": GenerationSource.OUTSIDE,
             "workflow_name": "outside:a-site", "workflow_version": "outside",
             "status": "completed", "params_json": "{}", "starred": 0,
             "output_files": json.dumps([{"filename": "c1_topaz.mp4",
                                          "library_path": str(tmp_path / "outbox" / "c1_topaz.mp4")}])}
    journal = tmp_path / "journals" / "origenerator.jsonl"
    monkeypatch.setattr(outside_videos, "places_here", lambda: outside_videos.Places(
        upscaled_dir=tmp_path / "outbox", records_folder=tmp_path / "records",
        frames_dir=tmp_path / "frames", thumb_dir=tmp_path / "thumbs",
        skip_sources=frozenset(), library_root=tmp_path, journal=journal))
    view = GalleryView(FakeDB([video]))
    qtbot.addWidget(view)
    view.refresh()

    view.set_items_favorite(["o1"], True)

    [line] = journal.read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["event"] == "favorite"


def _square_texts(view, key) -> list[str]:
    """The words on the middle pane's square for the folder ``key`` — its name
    (led by a star once the folder is favorited) and how many items it holds."""
    (square,) = [tile for tile in view._scroll.widget().findChildren(FolderTile)
                 if tile.key == key]
    return [label.text() for label in square.findChildren(QLabel)]


def test_clicking_the_star_beside_a_folder_stars_its_square_in_the_pane_beside_it(qtbot):
    view, cat, dog = _two_leaf_view(qtbot)
    view._tree.setCurrentItem(view._tree_item_for(cat).parent())  # both, as squares

    _click_beside_the_mark_of(qtbot, view, dog, which=0)

    assert any(text.startswith("<img") and text.endswith(view.group_for_key(dog).label)
               for text in _square_texts(view, dog))
    assert not any(text.startswith("<img") for text in _square_texts(view, cat))  # and only that one


def test_a_folder_the_user_made_takes_no_favorite(qtbot):
    # A favorite of a favorite collection gathers nothing, so its menu offers no
    # Favorite — and the star its row shows on hover must not leave one either.
    view, cat, _dog = _two_leaf_view(qtbot)
    made = gallery.custom_folder_key(_make_folder(view, "Mine", [cat]))

    view._toggle_favorite(made)

    assert not view.group_for_key(made).favorite


def test_the_favorite_button_offers_to_take_back_the_favorite_it_just_made(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    _click_off(view)  # nothing picked inside it, so the button aims at the folder

    view._buttons.favorite.click()

    assert view._buttons.favorite.toolTip().startswith("Unfavorite folder")


def test_unfavoriting_a_folder_takes_it_off_the_open_favorites_collection(qtbot):
    view, _cat, dog = _two_leaf_view(qtbot)
    view._toggle_favorite(dog)
    view._tree.setCurrentItem(_collection(view, FAVORITES_KEY))
    assert view._gallery_pane._listed_folders == [dog]

    view._toggle_favorite(dog)

    assert view._gallery_pane._listed_folders == []
    assert _shown(_collection(view, FAVORITES_KEY)) == "Favorites"  # and its count with it


def _long_list_view(qtbot):
    """A view holding more folders than its list can show at once, on screen so
    the list really scrolls. Returns it with that side's folder rows, top-down."""
    view = GalleryView(FakeDB([_image(f"i{n}", f"prompt {n}", 50, n) for n in range(30)]))
    _on_screen(qtbot, view, 700, 500)
    lora = _at(_image_workflow(view._tree), 0, 0)
    for item in (lora.parent().parent(), lora.parent(), lora):
        item.setExpanded(True)
    return view, _subs(lora)


def test_starring_a_folder_marks_its_row_where_it_stands(qtbot):
    # The gallery was read back and redrawn whole for one star — seconds of it on a
    # real library — and the redraw scrolled the list to the folder that was open,
    # taking the row just favorited out from under the mouse.
    view, folders = _long_list_view(qtbot)
    half = _side(view._tree)
    view._tree.setCurrentItem(folders[0])   # the folder that is open, up at the top
    half.scrollToItem(folders[-1])          # ...with the list scrolled away from it
    target, key = folders[-1], _key(folders[-1])
    scrolled_to = half.verticalScrollBar().value()
    assert scrolled_to > 0

    view._toggle_favorite(key)

    assert view._tree_item_for(key) is target  # the row itself, not a redrawn one
    assert target.data(0, _GROUP_ROLE).favorite
    assert half.verticalScrollBar().value() == scrolled_to


def test_starring_a_folder_marks_it_on_both_sides_of_the_list(qtbot):
    # Each side draws the folder from a copy of its own, so a star set through
    # one row has to reach the other side's row too.
    shapes = {"i1": (1280, 720), "i2": (720, 1280)}
    view = GalleryView(FakeDB([
        _row(pid, "sdxl_t2i", {"positive_prompt": f"prompt {pid}", "steps": 50,
                               "width": width, "height": height}, f"sdxl_t2i_{pid}.png")
        for pid, (width, height) in shapes.items()]))
    qtbot.addWidget(view)
    view.refresh()
    key = _key(_image_workflow(view._tree))
    rows = [view._tree_item_for(tree_key)
            for tree_key in view._tree_view.keys_for_folder(key)]
    assert len(rows) == 2

    view._toggle_favorite(key)

    assert [row.data(0, _GROUP_ROLE).favorite for row in rows] == [True, True]


def test_a_star_made_after_the_pane_moved_on_marks_what_is_on_screen(qtbot):
    # The squares a star marks are the ones on screen now: every pane drawn since
    # deleted the squares of the one before it.
    view, cat, dog = _two_leaf_view(qtbot)
    view._tree.setCurrentItem(view._tree_item_for(cat).parent())  # both, as squares
    view._tree.setCurrentItem(view._tree_item_for(cat))           # ...then into one

    view._toggle_favorite(dog)

    assert view.group_for_key(dog).favorite


def test_the_tick_after_a_star_finds_nothing_to_redraw(qtbot):
    # The star is on screen and in the database, so the tick that follows a second
    # later must not read it as somebody else's change and redraw the list — which
    # is the scroll the star itself no longer causes, arriving late.
    view, _cat, dog = _two_leaf_view(qtbot)
    view._toggle_favorite(dog)
    row = view._tree_item_for(dog)

    view._poll()

    assert view._tree_item_for(dog) is row


def test_each_tick_puts_what_a_slideshow_is_locked_on_first(qtbot, monkeypatch):
    # However the lock came about: an image locked from the map, a slideshow put
    # back the way it was left, a Funestra locking itself.
    view, _cat, _dog = _two_leaf_view(qtbot)
    ticks = []
    monkeypatch.setattr(view._enhance, "put_what_is_locked_first", lambda: ticks.append(1))

    view._poll()

    assert ticks == [1]


def test_a_reading_of_the_library_taken_before_a_star_does_not_take_it_back(qtbot,
                                                                            monkeypatch):
    # Each tick reads the library on a thread of its own, so a read taken a moment
    # before a star lands a moment after it. Drawing that read would put the star
    # back out and jump the list, and put both right again a tick later.
    view, _cat, dog = _two_leaf_view(qtbot)
    held = []
    monkeypatch.setattr(view, "off_thread", lambda work, done: held.append((work(), done)))
    view._finish_poll([], None)   # the tick's reading, taken first

    view._toggle_favorite(dog)    # the star, made while that reading was out
    row = view._tree_item_for(dog)
    (reading, deliver), = held
    deliver(reading)              # ...and the reading landing after it

    assert view._tree_item_for(dog) is row
    assert row.data(0, _GROUP_ROLE).favorite


def test_favoriting_a_folder_persists_without_reordering(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    db = FakeDB(rows)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    lora = _at(_image_workflow(view._tree), 0, 0)  # "(no LoRA)"
    cat_key = _key(_at(lora, 0))
    dog_key = _key(_at(lora, 1))  # cat is first, dog second
    view._toggle_favorite(dog_key)

    assert db.folder_meta_map()[dog_key]["starred"] is True
    lora = _at(_image_workflow(view._tree), 0, 0)
    # The star marks the folder in place; it does not jump above the cat.
    assert [_key(row) for row in _subs(lora)] == [cat_key, dog_key]
    # Favorites state rides on the group (the row's star icon reads it), not a ★ text
    # prefix, so the labels stay the plain folder names.
    assert _at(lora, 1).data(0, _GROUP_ROLE).favorite is True
    assert _at(lora, 0).data(0, _GROUP_ROLE).favorite is False
    assert not _at(lora, 1).text(0).startswith("★")


def test_favoriting_a_folder_from_its_menu_leaves_it_open(qtbot, monkeypatch):
    # A folder with sub-folders wears no star of its own (the row's actions are a
    # leaf's), so its right-click menu is the only way to favorite it — and the menu
    # covers the tree, so a right-click that shut the folder on the way in is only
    # seen once the menu closes, and reads as something the star did.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    db = FakeDB(rows)
    view = GalleryView(db)
    _on_screen(qtbot, view, 600, 600)

    tree = view._tree
    _top_level(tree)["All"].setExpanded(True)
    images = _image_workflow(tree)
    images.setExpanded(True)
    key = _key(images)
    # The half that holds the row: the tree is two of them now, and the pixel
    # geometry belongs to whichever one the row is in.
    half = _side(tree, LANDSCAPE)
    row = half.visualRect(half.indexFromItem(images))
    caret = QPoint(row.left() - half.indentation() // 2, row.center().y())

    qtbot.mouseClick(half.viewport(), Qt.MouseButton.RightButton, pos=caret)
    monkeypatch.setattr(
        "origenerator.gui.gallery_view.QMenu.exec",
        lambda menu, *a: next(act for act in menu.actions() if act.text() == "Favorite"),
    )
    view._on_tree_context_menu(images, caret, LANDSCAPE)

    assert db.folder_meta_map()[key]["starred"] is True
    assert _image_workflow(view._tree).isExpanded()


def test_favorite_collection_is_pinned_first_and_collects_favorite_folders(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    db = FakeDB(rows)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    lora = _at(_image_workflow(view._tree), 0, 0)  # "(no LoRA)"
    dog_key = _key(_at(lora, 1))
    view._toggle_favorite(dog_key)

    # The Favorites collection sits just below Latest, above the media folders.
    assert list(_alls(view._tree))[:2] == ["Latest", "Favorites"]
    # Selecting it lists a tile for each favorited folder, wherever it lives.
    collection = _alls(view._tree)["Favorites"]
    view._tree.setCurrentItem(collection)
    assert view._gallery_pane._listed_folders == [dog_key]
    assert view.listed_prompt_ids() == []


def test_favorites_leads_with_its_count_and_latest_leaves_its_count_to_all(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2),
                 _image("i3", "a dog", 50, 1)])
    db.set_generation_favorite("i1", True)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    lora = _at(_image_workflow(view._tree), 0, 0)
    cat = _children_by_prompt(lora)["a cat"]

    view._toggle_favorite(_key(cat))  # the favorited item is in the favorited folder

    alls = _alls(view._tree)
    assert _shown(alls["Favorites"]) == "(2) Favorites"
    assert _shown(_top_level(view._tree)["All"]) == "(3) All"
    assert _shown(alls["Latest"]) == "Latest"


def test_experiments_collection_is_always_reachable(qtbot):
    # The collection hosts the feature's on/off switch, so it must exist before any
    # experiment does — an empty gallery included.
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    view.refresh()

    collection = _alls(view._tree)["Experiments"]
    assert collection.text(0) == "Experiments"


def test_experiments_collection_label_counts_the_unreviewed(qtbot):
    rows = [
        _image("i1", "a cat", 50, 1),
        _experiment_row("e1"),
        _experiment_row("e2", seed=10),
        _experiment_row("e3", verdict="up", seed=11),
    ]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    assert _shown(_alls(view._tree)["Experiments"]) == "(2) Experiments"


def test_experiments_collection_offers_keep_and_reject_on_each_tile(qtbot):
    view = GalleryView(FakeDB([_experiment_row("e1")]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_collection(view, EXPERIMENTS_KEY))
    assert view.listed_prompt_ids() == ["e1"]
    tile = view._gallery_pane._thumb_widgets["e1"]
    tooltips = [b.toolTip() for b in tile._corner_buttons]
    assert any("Keep" in t for t in tooltips)
    assert any("Reject" in t for t in tooltips)


def test_double_clicking_an_experiment_opens_it_selected_in_its_own_folder(qtbot):
    # An experiment has a folder like anything else, so the collection's double-click
    # is the same jump Latest and Favorites make — no verdict needed first.
    experiment = _experiment_row("e1", steps=30)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), experiment]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_collection(view, EXPERIMENTS_KEY))
    view._gallery_pane._thumb_widgets["e1"].double_clicked.emit("e1")

    assert _selected_folder(view) == gallery.settings_folder_key(experiment)
    assert view.listed_prompt_ids() == ["e1"]  # its own settings folder, not i1's
    assert view.selected_prompt_ids() == ["e1"]  # landed selected
    assert view._gallery_pane._thumb_widgets["e1"]._selected


def test_keeping_an_experiment_clears_it_from_the_review_queue(qtbot):
    db = FakeDB([_experiment_row("e1")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    # Unreviewed, but already filed in the tree — the collection is a queue over it,
    # not a holding pen outside it.
    assert "SDXL T2I" in _workflow_rows(view._tree)

    view._on_experiment_verdict("e1", "keep")

    assert db.get_generation("e1")["experiment_verdict"] == "up"
    view._tree.setCurrentItem(_collection(view, EXPERIMENTS_KEY))
    assert view.listed_prompt_ids() == []          # reviewed: out of the collection...
    assert "SDXL T2I" in _workflow_rows(view._tree)       # ...and still in its folder


def test_rejecting_an_experiment_goes_through_the_undoable_action(qtbot):
    db = FakeDB([_experiment_row("e1")])
    actions = FakeActions()
    view = GalleryView(db, actions=actions)
    qtbot.addWidget(view)
    view.refresh()

    view._on_experiment_verdict("e1", "reject")

    assert [r["prompt_id"] for r in actions.rejected] == ["e1"]
    assert view._buttons.undo.isEnabled()


def test_an_experiment_completion_never_hijacks_the_front_tab(qtbot, monkeypatch):
    db = FakeDB([_experiment_row("e1"), _image("i1", "a cat", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    shown = []
    monkeypatch.setattr(view, "_show_reroll_result_in_tab",
                        lambda row, launcher: shown.append(row))

    view._on_reroll_finished("some-key", "e1")   # a background experiment landing
    assert shown == []                           # the user's tab is left alone

    view._on_reroll_finished("some-key", "i1")   # the user's own re-roll landing
    assert [r["prompt_id"] for r in shown] == ["i1"]  # handed the finished row itself


def test_the_experiments_switch_reports_what_each_position_means(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    view.refresh()
    assert view.experiments_enabled() is False
    assert "Off" in view._experiments_status.text()

    view.set_experiments_enabled(True)           # a restored session turns it on
    assert view.experiments_enabled() is True
    assert view._experiments_cb.isChecked()      # the collection's switch reflects it
    # The switch is a promise about the closed app, and says so.
    assert "close the app" in view._experiments_status.text()

    view._experiments_cb.setChecked(False)       # the user clicks it off
    assert view.experiments_enabled() is False
    assert "Off" in view._experiments_status.text()


def test_an_open_app_queues_no_experiments_however_the_switch_is_set(qtbot):
    # The whole point of the switch's new meaning: turning it on mid-session
    # must not put anything on the GPU while the user is sitting right there.
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db, client=ComfyUIClient(folders=SUITE_FOLDERS))
    qtbot.addWidget(view)
    view.refresh()

    view.set_experiments_enabled(True)

    assert [r for r in db.list_generations() if r.get("source") == "experiment"] == []


def test_a_branch_session_schedules_no_experiments_at_all(qtbot, monkeypatch):
    # Scheduling an absence is the production app's alone. A preview instance
    # shares the same ComfyUI, so a batch queued as it closes outlives it as
    # work the production app can neither see nor cancel — and the user's next
    # Generate waits on jobs "from another app" that were his own preview's.
    monkeypatch.setenv(ENV_FLAG, "1")
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db, client=ComfyUIClient(folders=SUITE_FOLDERS))
    qtbot.addWidget(view)
    view.refresh()

    view.set_experiments_enabled(True)  # the switch a seeded session restores

    assert view.experiments_enabled() is False   # forced off, however it was saved
    assert not view._experiments_cb.isEnabled()  # grayed, with the reason beneath
    assert "production app" in view._experiments_status.text()

    view._experiments_cb.setChecked(True)  # and the gate holds even forced on

    assert [r for r in db.list_generations() if r.get("source") == "experiment"] == []


def test_a_branch_session_reviews_experiments_like_the_live_app(qtbot, monkeypatch):
    # The collection reads the production app's own rows, so a verdict given in a
    # preview is the verdict: the same items come up for review, and its count
    # shows on the tree.
    monkeypatch.setenv(ENV_FLAG, "1")
    view = GalleryView(FakeDB([_experiment_row("e1"), _experiment_row("e2", seed=10)]))
    qtbot.addWidget(view)
    view.refresh()

    assert _shown(_alls(view._tree)["Experiments"]) == "(2) Experiments"
    view._tree.setCurrentItem(_collection(view, EXPERIMENTS_KEY))
    assert sorted(view.listed_prompt_ids()) == ["e1", "e2"]
    assert "production app" not in view._gallery_pane._experiments_empty_hint()


def test_clicking_a_favorite_tile_drills_into_the_real_folder(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    db = FakeDB(rows)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    lora = _at(_image_workflow(view._tree), 0, 0)  # "(no LoRA)"
    dog_key = _key(_at(lora, 1))
    view._toggle_favorite(dog_key)

    collection = _alls(view._tree)["Favorites"]
    view._tree.setCurrentItem(collection)
    view._gallery_pane._drill_into(view._gallery_pane._listed_folders[0])  # click the favorited tile
    assert set(view.listed_prompt_ids()) == {"i2"}  # now inside the dog folder


def test_favorite_collection_shows_empty_state_when_nothing_is_favorite(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    collection = _alls(view._tree)["Favorites"]
    view._tree.setCurrentItem(collection)
    assert view._gallery_pane._listed_folders == []   # no tiles, just the hint
    assert view.listed_prompt_ids() == []


def test_enhanced_with_nothing_enhanced_in_it_says_how_to_enhance_one(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_alls(view._tree)["Enhanced"])

    assert view.listed_prompt_ids() == []
    assert view._scroll.widget().text() == (
        "No enhanced images yet.\n\nEnhance one from its right-click menu or the plus "
        "in its corner to see it here.")


def test_enhanced_shows_every_enhanced_image_under_its_folder(qtbot):
    view = GalleryView(FakeDB([_enhanced_image("i1", "a cat", 50, 1),
                               _image("i2", "a dog", 50, 2),
                               _enhanced_image("i3", "a bird", 50, 3)]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_alls(view._tree)["Enhanced"])

    assert sorted(view.listed_prompt_ids()) == ["i1", "i3"]


def test_favorite_collection_gathers_favorite_items_as_thumbnails(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    db = FakeDB(rows)
    db.set_generation_favorite("i2", True)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    collection = _alls(view._tree)["Favorites"]
    view._tree.setCurrentItem(collection)
    assert view.listed_prompt_ids() == ["i2"]  # the favorited item, in the collection
    assert view._gallery_pane._thumb_widgets["i2"]._favorite is True


def test_favorite_collection_shows_both_favorite_items_and_folders(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    db = FakeDB(rows)
    db.set_generation_favorite("i1", True)  # a favorited item
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    lora = _at(_image_workflow(view._tree), 0, 0)  # "(no LoRA)"
    dog_key = _key(_at(lora, 1))
    view._toggle_favorite(dog_key)  # and a favorited folder

    collection = _alls(view._tree)["Favorites"]
    view._tree.setCurrentItem(collection)
    assert view.listed_prompt_ids() == ["i1"]      # the item
    assert view._gallery_pane._listed_folders == [dog_key]  # the folder


def test_unfavoriting_an_item_from_the_collection_removes_it(qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1)]
    db = FakeDB(rows)
    db.set_generation_favorite("i1", True)
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()

    collection = _alls(view._tree)["Favorites"]
    view._tree.setCurrentItem(collection)
    assert view.listed_prompt_ids() == ["i1"]
    _answer_menu(monkeypatch, "Unfavorite 1 item")
    _right_click(view, "i1")

    assert not db.get_generation("i1")["starred"]
    assert view.listed_prompt_ids() == []  # gone from the collection at once


def test_favorite_collection_stays_selected_across_a_refresh(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Favorites"])

    view.refresh()  # a poll-driven rebuild must not knock us out of the collection

    assert view._tree.currentItem().text(0) == "Favorites"


def test_favorite_collection_is_absent_until_a_folder_exists(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    view.refresh()
    alls = _alls(view._tree)
    assert "Latest" not in alls
    assert "Favorites" not in alls


def test_a_folders_latest_lists_what_that_folder_made_under_its_path(qtbot):
    rows = [_image("i2", "a dog", 50, 2), _i2v_video("v1", "styleA"), _image("i1", "a cat", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    workflow = _image_workflow(view._tree)

    view._tree.setCurrentItem(workflow.child(0))

    assert view.listed_prompt_ids() == ["i2", "i1"]
    assert view._folder_path.display_text() == (
        f"{SIDE_LABELS[LANDSCAPE]}  ›  All  ›  Images  ›  {workflow.text(0)}  ›  Latest")


def test_a_folders_collection_names_itself_by_its_path_to_the_slideshow_button(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    workflow = _image_workflow(view._tree)

    view._tree.setCurrentItem(workflow.child(0))

    assert view.slideshow_subject() == (
        f"{SIDE_LABELS[LANDSCAPE]}  ›  All  ›  Images  ›  {workflow.text(0)}  ›  Latest")


def test_latest_collection_is_pinned_first_and_lists_recent_items(qtbot):
    rows = [_image("i2", "a dog", 50, 2), _image("i1", "a cat", 50, 1)]  # newest first
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    # Latest leads its side, above Favorites and the media folders.
    assert list(_alls(view._tree))[0] == "Latest"
    # Selecting it lists every recently generated item, newest first — not folders.
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    assert view.listed_prompt_ids() == ["i2", "i1"]
    assert view._gallery_pane._listed_folders == []


def test_latest_collection_lists_imported_files_too(qtbot):
    # A file ComfyUI wrote on its own arrives at the launch that finds it, and
    # Latest is where it is looked for then -- it used to sit in its workflow's
    # folder alone, with nothing to say why it was not the newest thing here.
    generated = _image("gen", "a cat", 50, 1)
    imported = _row("imp", "sdxl_t2i", {"seed": 9}, "imp.png", source="imported")
    view = GalleryView(FakeDB([imported, generated]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    assert sorted(view.listed_prompt_ids()) == ["gen", "imp"]


def test_clicking_a_recent_item_previews_it_without_leaving_the_collection(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    _click_tile(view, "i2")  # click the recent tile for the dog
    # Its details fill the info pane, but the collection stays put — no navigation, so
    # every recent item is still listed.
    assert view.selected_generation() == "i2"
    assert view._gallery_pane.showing_latest()
    assert set(view.listed_prompt_ids()) == {"i1", "i2"}


def test_double_clicking_a_recent_item_opens_it_selected_in_its_folder(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    # Double-clicking a recent tile is the whole jump — no button stands in for it.
    view._gallery_pane._thumb_widgets["i2"].double_clicked.emit("i2")
    assert view.selected_generation() == "i2"
    assert view._gallery_pane.showing_latest() is False             # out of the collection...
    assert set(view.listed_prompt_ids()) == {"i2"}     # ...into the dog's own folder
    # The item lands selected — its tile picked and highlighted, not merely
    # previewed — as if we'd navigated in and clicked it.
    assert view.selected_prompt_ids() == ["i2"]         # landed selected
    assert view._gallery_pane._thumb_widgets["i2"]._selected


def test_double_clicking_a_recent_item_also_keeps_its_tab(qtbot):
    # Double-click means the same thing everywhere in the pane — this is a tab I'm
    # staying on — whether it opens a folder on the way or not.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    _click_tile(view, "i2")  # a plain click borrows the italic tab
    assert view._info_tabs._preview_panel is not None

    view._gallery_pane._thumb_widgets["i2"].double_clicked.emit("i2")

    assert view._info_tabs._preview_panel is None


def test_latest_collection_shows_empty_state_when_nothing_has_a_result(qtbot):
    pending = _row("wip", "sdxl_t2i", {"seed": 9}, "wip.png", status="running", output_files=None)
    view = GalleryView(FakeDB([pending]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    assert view.listed_prompt_ids() == []  # nothing to show: just the hint


def test_latest_collection_stays_selected_across_a_refresh(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])

    view.refresh()  # a poll-driven rebuild must not knock us out of the collection

    assert view._tree.currentItem().text(0) == "Latest"


def _many_latest(count):
    """``count`` generated images, newest first, so the collection runs past one page."""
    return [_image(f"i{n}", "a cat", 50, n) for n in reversed(range(count))]


def test_latest_opens_on_one_page_however_far_back_it_goes(qtbot):
    # The collection lists every generation ever made, so it draws a page of tiles at a
    # time rather than all 120 at once.
    view = GalleryView(FakeDB(_many_latest(120)))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    assert len(_drawn(view)) == 50
    # And it's the newest page — the collection still reads newest-first.
    assert _drawn(view)[0] == "i119"


def _scroll_to_the_end(view):
    QApplication.processEvents()   # the pane laid out as far as it is drawn
    bar = _scroll_bar(view)
    bar.setValue(bar.maximum())


def test_scrolling_to_the_end_of_latest_draws_the_next_page(qtbot):
    view = GalleryView(FakeDB(_many_latest(120)))
    _on_screen(qtbot, view, 1800, 1300)
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    opened_on = len(_drawn(view))
    assert opened_on < 120

    _scroll_to_the_end(view)
    assert len(_drawn(view)) > opened_on
    for _ in range(120 // opened_on):
        _scroll_to_the_end(view)

    assert _drawn(view) == [f"i{n}" for n in reversed(range(120))]


def test_a_rebuild_keeps_the_pages_latest_had_been_scrolled_into(qtbot):
    # A generation landing rebuilds the gallery under the open collection. That must not
    # collapse it back to one page and throw away everything the user scrolled
    # down through — the new item just joins the top of what's already drawn.
    db = FakeDB(_many_latest(120))
    view = GalleryView(db)
    _on_screen(qtbot, view, 1800, 1300)
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    _scroll_to_the_end(view)
    scrolled_into = _drawn(view)

    db._rows.insert(0, _image("fresh", "a dog", 50, 999))  # a generation lands
    view.refresh()

    assert _drawn(view) == ["fresh", *scrolled_into]


def test_a_double_click_on_an_image_in_latest_plays_everything_latest_lists(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB(_many_latest(120)))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])

    slideshow = view._slideshows.open_on_preview(("i119.png", "image"), "i119")
    qtbot.addWidget(slideshow.shown)

    assert len(slideshow._set.playlist.in_play_order()) == 120
    slideshow.close()


def test_alls_latest_lists_both_kinds(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_alls(view._tree)["Latest"])

    assert set(view.listed_prompt_ids()) == {"i1", "v1"}


def test_the_shapes_radio_wears_the_waiting_cursor_while_it_redraws(qtbot, monkeypatch):
    # A redraw holds the window thread, so without this the window reads as dead
    # for as long as it takes rather than as working.
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()
    while_drawing = []
    real = view.refresh
    monkeypatch.setattr(view, "refresh", lambda *a: (
        while_drawing.append(QApplication.overrideCursor()), real(*a))[1])

    view._tree.together_button.click()

    assert [cursor and cursor.shape() for cursor in while_drawing] == [Qt.CursorShape.WaitCursor]
    assert QApplication.overrideCursor() is None


def test_opening_one_kinds_latest_lists_it_without_building_the_list_again(qtbot, monkeypatch):
    # Opening a collection cannot change a single folder, so the table of
    # contents is not built again for it -- a build takes seconds on a full library.
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()
    built = []
    monkeypatch.setattr(gallery, "build_gallery_tree",
                        lambda *a, **k: built.append(1) or [])

    view._tree.setCurrentItem(_collection_row(_alls(view._tree)["Videos"], "Latest"))

    assert view.listed_prompt_ids() == ["v1"]
    assert built == []


def test_another_latest_opens_on_its_first_page(qtbot):
    # Another Latest is a new listing, not a redraw of the one on screen, so it
    # starts at its newest item instead of holding the pages already scrolled.
    view = GalleryView(FakeDB(_many_latest(120)))
    _on_screen(qtbot, view, 1800, 1300)
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    opened_on = _drawn(view)
    _scroll_to_the_end(view)
    assert len(_drawn(view)) > len(opened_on)

    view._tree.setCurrentItem(_collection_row(_alls(view._tree)["Images"], "Latest"))

    assert _drawn(view) == opened_on


def test_one_kinds_latest_leaves_out_the_other_kinds_work_in_flight(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.add(_running_row("rr1", workflow="wan22_i2v"))  # a running video
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    assert "rr1" in view._gallery_pane._inflight_tiles

    view._tree.setCurrentItem(_collection_row(_alls(view._tree)["Images"], "Latest"))

    assert "rr1" not in view._gallery_pane._inflight_tiles


def test_a_new_generation_appears_at_the_top_of_latest(qtbot):
    db = FakeDB([_image("old", "a cat", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    assert view.listed_prompt_ids() == ["old"]

    # A fresh generation lands; a poll reflects it at the top of the running list.
    db.add(_image("new", "a dog", 50, 2))
    view._poll()
    assert view.listed_prompt_ids() == ["new", "old"]


def test_new_generations_appear_without_manual_refresh(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    assert set(_top_level(view._tree)) == {"All"}
    assert set(_workflow_rows(view._tree)) == {"SDXL T2I"}

    # A new video lands in the DB; a poll tick reflects it with no Refresh button.
    db.add(_row("v1", "wan22_i2v", {"positive_prompt": "dance", "seed": 5},
                "wan22_i2v_00001_.mp4"))
    view._poll()
    assert set(_workflow_rows(view._tree)) == {"SDXL T2I", "WAN 2.2 I2V"}


def test_the_gallery_polls_on_a_timer_of_its_own(qtbot):
    """Every other poll test calls ``_poll`` by hand, which leaves the timer that
    makes this screen live — how a finished ComfyUI job arrives without a click —
    covered by nothing at all."""
    db = FakeDB([_image("old", "a cat", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])

    assert view._poll_timer.isActive()
    # The number itself, not _POLL_INTERVAL_MS: read back through the constant
    # that set it, a gallery slowed to one tick a minute still passes.
    assert view._poll_timer.interval() == 1500

    db.add(_image("new", "a dog", 50, 2))
    view._poll_timer.timeout.emit()  # the tick, delivered the way the timer does

    assert view.listed_prompt_ids() == ["new", "old"]


def test_a_hidden_gallery_stops_polling_and_takes_it_up_again_when_shown(qtbot):
    """Polling costs a pair of DB reads a second, so it is worth paying only while
    the screen is up — and must resume the moment it is back."""
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    with qtbot.waitExposed(view):
        view.show()

    view.hide()

    assert not view._poll_timer.isActive()

    with qtbot.waitExposed(view):
        view.show()

    assert view._poll_timer.isActive()


class _MinimizedCore:
    def isMinimized(self) -> bool:
        return True


def _a_minimized_gallery(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]))
    qtbot.addWidget(view)
    with qtbot.waitExposed(view):
        view.show()
    view.refresh()
    monkeypatch.setattr(view, "window", _MinimizedCore)
    return view


def test_a_gallery_hidden_by_core_minimizing_keeps_its_poll(qtbot, monkeypatch):
    view = _a_minimized_gallery(qtbot, monkeypatch)

    view.hide()

    assert view._poll_timer.isActive()


def test_a_minimized_gallery_with_no_slideshow_up_reads_nothing_on_its_tick(
        qtbot, monkeypatch):
    view = _a_minimized_gallery(qtbot, monkeypatch)
    reads = []
    monkeypatch.setattr(view, "off_thread", lambda *hop: reads.append(hop))

    view._poll_timer.timeout.emit()

    assert reads == []


def test_a_minimized_gallery_under_an_open_slideshow_reads_on_its_tick(qtbot, monkeypatch):
    """The slideshow shows what is in flight while Core cannot be seen -- the
    Job Queue at its foot, and the pictures still being made -- so the poll that
    feeds both goes on."""
    view = _a_minimized_gallery(qtbot, monkeypatch)
    _select_first_leaf(view)
    view._slideshows.start()
    qtbot.addWidget(view._slideshows.showing.shown)
    reads = []
    monkeypatch.setattr(view, "off_thread", lambda *hop: reads.append(hop))

    view._poll_timer.timeout.emit()

    assert len(reads) == 1


@pytest.mark.real_thread_hop
def test_a_poll_answer_that_lands_after_its_gallery_is_gone_is_dropped(qtbot, monkeypatch):
    release = threading.Event()

    def facts_once_released(_client, _targets):
        release.wait(5)
        return gallery_view_module._PollFacts({}, {}, None)

    monkeypatch.setattr(gallery_view_module, "_fetch_poll_facts", facts_once_released)
    db = FakeDB([_image("old", "a cat", 50, 1)])
    view = GalleryView(db)
    view.refresh()
    before = set(off_thread._in_flight)
    view._poll()
    db.add(_image("new", "a dog", 50, 2))
    view.close()
    sip.delete(view)
    library_reads, list_generations = [], db.list_generations
    monkeypatch.setattr(db, "list_generations",
                        lambda: library_reads.append(1) or list_generations())

    release.set()
    qtbot.waitUntil(lambda: not off_thread._in_flight - before, timeout=5000)

    assert library_reads == []


def _counted(monkeypatch, owner, name, calls):
    original = getattr(owner, name)
    monkeypatch.setattr(owner, name,
                        lambda *args, **kwargs: calls.append(name) or original(*args, **kwargs))


def test_a_rebuild_reads_the_library_and_the_requests_once(qtbot, monkeypatch):
    # The in-flight tiles were built three times over per rebuild, and each
    # build read both tables again, with the listing already in hand.
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    reads = []
    _counted(monkeypatch, db, "list_generations", reads)
    _counted(monkeypatch, db, "list_requests", reads)

    view.refresh()

    assert sorted(reads) == ["list_generations", "list_requests"]


def test_a_rebuild_works_out_when_each_image_was_last_enhanced_once(qtbot, monkeypatch):
    worked_out = []
    _counted(monkeypatch, gallery, "enhancement_recency", worked_out)
    _counted(monkeypatch, gallery_tree_module, "enhancement_recency", worked_out)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)

    view.refresh()

    assert len(worked_out) == 1


def test_folder_keys_are_derived_against_the_index_the_rebuild_already_built(
        qtbot, monkeypatch):
    # The tree keyed its folders against one index of the images, and the
    # folder keys asked of the view were derived against a second, built from
    # scratch on the first ask after every rebuild.
    built = []
    _counted(monkeypatch, gallery, "build_image_config_index", built)
    _counted(monkeypatch, gallery_tree_module, "build_image_config_index", built)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)

    view.refresh()
    indexed = len(built)

    view.image_config_index()
    view.folder_key_of(view.row_for("v1"))

    assert len(built) == indexed


def test_a_rebuild_builds_one_folder_tree_per_side_and_no_third(qtbot, monkeypatch):
    # A third tree of the whole library was built only to read folder names
    # off it for the search index, which the two sides' trees already carry.
    built = []
    _counted(monkeypatch, gallery, "build_gallery_tree", built)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)

    view.refresh()

    assert len(built) == len((LANDSCAPE, PORTRAIT))


def test_folders_start_collapsed(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    workflow = _image_workflow(view._tree)
    assert workflow.isExpanded() is False
    assert _at(workflow, 0).isExpanded() is False


def _double_click_the_name_of(qtbot, row):
    tree = row.treeWidget()
    tree.scrollToItem(row)
    gestures.double_click(tree.viewport(), tree.visualItemRect(row).center())


def test_double_clicking_a_folder_of_folders_opens_it_and_expands_or_collapses_it(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    _on_screen(qtbot, view, 1200, 800)
    workflow = _image_workflow(view._tree)

    _double_click_the_name_of(qtbot, workflow)

    assert _selected_folder(view) == _key(workflow)
    assert workflow.isExpanded()

    _double_click_the_name_of(qtbot, workflow)

    assert _selected_folder(view) == _key(workflow)
    assert not workflow.isExpanded()


def _editing(row) -> bool:
    return row.treeWidget().state() == QAbstractItemView.State.EditingState


def test_double_clicking_all_collapses_it_like_the_folders_under_it(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    _on_screen(qtbot, view, 1200, 800)
    all_row = _top_level(view._tree)["All"]
    assert all_row.isExpanded()

    _double_click_the_name_of(qtbot, all_row)

    assert _selected_folder(view) == _key(all_row)
    assert not all_row.isExpanded()
    assert not _editing(all_row)


def test_double_clicking_a_settings_folder_opens_it_and_renames_nothing(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    _on_screen(qtbot, view, 1200, 800)
    leaf = _first_leaf(view)
    above = leaf.parent()
    while above is not None:
        above.setExpanded(True)
        above = above.parent()

    _double_click_the_name_of(qtbot, leaf)

    assert _selected_folder(view) == _key(leaf)
    assert not _editing(leaf)


def test_opening_a_folder_of_sub_folders_picks_nothing(qtbot):
    # A branch folder shows folders, not generations, so it has no first item to
    # land on the way a settings folder does
    # (test_opening_a_folder_lands_on_its_first_item).
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_image_workflow(view._tree))

    assert view._gallery_pane._listed_folders      # its child folders, as tiles
    assert view.listed_prompt_ids() == []
    assert view._selected is None


def _path_links(view) -> dict[str, str]:
    drawn = view._folder_path.findChild(shared_folder_path.FolderPath).text()
    return {name: href for href, name in re.findall(r'<a href="([^"]*)"[^>]*>([^<]*)</a>', drawn)}


def _click_path_step(view, name):
    view._folder_path.findChild(shared_folder_path.FolderPath).linkActivated.emit(_path_links(view)[name])


def test_clicking_a_step_of_the_path_goes_to_that_folder(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    workflow = _image_workflow(view._tree)
    view._tree.setCurrentItem(_first_leaf(view))

    _click_path_step(view, workflow.text(0))

    assert view._tree.currentItem() is workflow
    assert view._folder_path.display_text() == view._tree_view.folder_path(workflow)


def test_the_path_links_every_folder_above_the_one_open_and_not_its_side(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    here = _first_leaf(view)
    view._tree.setCurrentItem(here)

    side, *above, _here = view._tree_view.path_steps(here)

    assert list(_path_links(view)) == [step.name for step in above]


def test_a_collections_path_links_the_folders_above_it_and_wears_its_star(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_collection(view, FAVORITES_KEY))

    path = view._folder_path.findChild(shared_folder_path.FolderPath)
    assert list(_path_links(view)) == ["All"]
    assert icon_then_text("star", "Favorites", color=TEXT_PRIMARY,
                          size=path.fontMetrics().height()) in path.text()
    assert view._folder_path.display_text() == f"{SIDE_LABELS[LANDSCAPE]}  ›  All  ›  Favorites"


def test_enhanceds_path_wears_the_plus_where_favorites_wears_its_star(qtbot):
    view = GalleryView(FakeDB([_enhanced_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_collection(view, ENHANCED_KEY))

    path = view._folder_path.findChild(shared_folder_path.FolderPath)
    assert icon_then_text("plus", "Enhanced", color=TEXT_PRIMARY,
                          size=path.fontMetrics().height()) in path.text()


def test_clicking_a_step_during_a_search_puts_the_search_away_and_goes_there(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    folders = _children_by_prompt(_at(_image_workflow(view._tree), 0, 0))
    view._tree.setCurrentItem(folders["a dog"])
    _search_for(view, "cat")
    assert view._showing_search()

    _click_path_step(view, folders["a dog"].text(0))

    assert not view._showing_search()
    assert view._tree.currentItem() is folders["a dog"]
    assert view.listed_prompt_ids() == ["i2"]


def test_a_workflow_that_made_both_kinds_has_a_folder_of_each_kind(qtbot):
    still = _row("still", "wan22_flf2v_loop", {"seed": 1}, "flf2v_loop_00001_.png")
    video = _row("clip", "wan22_flf2v_loop", {"seed": 2}, "flf2v_loop_00002_.mp4")
    view = GalleryView(FakeDB([still, video]))
    qtbot.addWidget(view)
    view.refresh()
    looping = workflow_label("wan22_flf2v_loop")

    assert list(_workflow_rows(view._tree, "image")) == [looping]
    assert list(_workflow_rows(view._tree, "video")) == [looping]


def test_with_several_folders_picked_the_path_up_top_links_nothing(qtbot):
    view, cat, dog = _two_leaf_view(qtbot)

    _pick(view, cat, dog)

    assert _path_links(view) == {}


def test_a_tile_and_the_tab_it_opens_both_wear_the_items_name(qtbot):
    older, newer = _image("g1", "a cat", 50, 1), _image("g2", "a cat", 50, 2)
    view = GalleryView(FakeDB([newer, older]), client=ComfyUIClient(folders=SUITE_FOLDERS))
    qtbot.addWidget(view)
    view.refresh()
    for panel in view._info_tabs.config_panels():
        panel._preview.show_media = MagicMock()
    _select_first_leaf(view)

    view._on_thumbnail_clicked("g2")

    name = f"{gallery.folder_id(gallery.settings_folder_key(newer))} 001"
    assert view._gallery_pane._thumb_widgets["g2"]._text_label.text() == name
    assert view._info_tabs.tabText(view._info_tabs.currentIndex()) == name


def test_a_tab_put_back_before_the_gallery_first_loads_takes_its_items_name_then(qtbot):
    row = _image("g1", "a cat", 50, 1)
    view = GalleryView(FakeDB([row]), client=ComfyUIClient(folders=SUITE_FOLDERS))
    qtbot.addWidget(view)
    for panel in view._info_tabs.config_panels():
        panel._preview.show_media = MagicMock()
    view._info_tabs.load_selection(row, [row])

    view.refresh()

    name = f"{gallery.folder_id(gallery.settings_folder_key(row))} 000"
    assert view._info_tabs.tabText(view._info_tabs.currentIndex()) == name


def test_going_to_an_item_draws_its_folder_even_when_that_row_is_already_current(qtbot):
    """A move always ends with the item on screen, drawn from its own folder.

    The pane can be showing something other than the row the tree has current —
    a search's hits, a collection — and setting a row Qt already holds current fires
    no signal to draw anything. The move draws it itself in that case rather than
    trusting the signal, which is how a click came to fill the info pane while
    the middle pane under it stood still.
    """
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), client=ComfyUIClient(folders=SUITE_FOLDERS))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)                 # that folder's row is now the current one
    assert "i1" in view.listed_prompt_ids()
    view._gallery_pane.show_empty()               # the pane goes off it, the row stays current
    assert "i1" not in view.listed_prompt_ids()

    view._go_to_generation("i1")

    assert "i1" in view.listed_prompt_ids()          # the folder is drawn again
    assert view._selected["prompt_id"] == "i1"        # and the item is picked in it


def test_going_to_a_failed_generation_opens_the_folder_its_settings_name(qtbot):
    """A generation that failed with no file has no row of its own in the tree —
    a terminal file-less row is dropped from it — so the move falls back to the
    row its settings key names. Opening no folder at all is what left the middle
    pane where it was while the item filled the info pane beside it."""
    done = _image("i1", "a cat", 50, 1)
    failed = dict(done, prompt_id="x1", status="error", output_files="[]",
                  thumbnail_path=None)
    view = GalleryView(FakeDB([done, failed]), client=ComfyUIClient(folders=SUITE_FOLDERS))
    qtbot.addWidget(view)
    view.refresh()
    assert "x1" not in view._leaf_by_id       # no settings row of its own

    view._go_to_generation("x1")

    # Its folder is the one its finished sibling sits in, and that is what opened.
    assert "i1" in view.listed_prompt_ids()
    assert view._selected["prompt_id"] == "x1"


def test_following_a_link_lands_in_one_tab(qtbot):
    """A followed link fills the tab a click would, rather than forking one: going
    to look at something costs no more tabs than browsing to it."""
    image = _image("img1", "a cat", 50, 1)
    video = _row("vid1", "wan22_i2v",
                 {"positive_prompt": "dance", "seed": 5,
                  "input_image": "sdxl_t2i_img1.png"},
                 "wan22_i2v_00001_.mp4")
    view = GalleryView(FakeDB([video, image]), client=ComfyUIClient(folders=SUITE_FOLDERS))
    qtbot.addWidget(view)
    view.refresh()
    for panel in view._info_tabs.config_panels():
        panel._preview.show_media = MagicMock()  # don't start WMF playback
    view._tree.setCurrentItem(view._leaf_by_id["vid1"])
    _click_tile(view, "vid1")
    tabs = view._info_tabs.count()

    view.follow_link("img1")

    assert view._info_tabs.count() == tabs
    assert view._info_tabs.current_config_panel().displayed_row()["prompt_id"] == "img1"


def test_back_and_forward_walk_the_viewed_generations(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    _click_tile(view, "i1")
    _click_tile(view, "i2")
    assert view._selected["prompt_id"] == "i2"

    view._navigation.go_back()
    assert view._selected["prompt_id"] == "i1"
    view._navigation.go_forward()
    assert view._selected["prompt_id"] == "i2"


def test_back_returns_from_a_followed_input_image_link_to_the_video(qtbot):
    image = _image("img1", "a cat", 50, 1)
    video = _row("vid1", "wan22_i2v",
                 {"positive_prompt": "dance", "seed": 5,
                  "input_image": "sdxl_t2i_img1.png"},
                 "wan22_i2v_00001_.mp4")
    view = GalleryView(FakeDB([video, image]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["vid1"])
    _click_tile(view, "vid1")   # viewing the video
    view.follow_link("img1")      # follow its input-image link

    assert view._selected["prompt_id"] == "img1"
    view._navigation.go_back()
    assert view._selected["prompt_id"] == "vid1"


def test_nav_buttons_enable_only_when_there_is_somewhere_to_go(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    assert not view._buttons.back.isEnabled()
    assert not view._buttons.forward.isEnabled()

    _select_first_leaf(view)   # opening a folder is somewhere to come back from
    _click_tile(view, "i1")
    _click_tile(view, "i2")
    assert view._buttons.back.isEnabled()
    assert not view._buttons.forward.isEnabled()

    for _ in range(3):
        view._navigation.go_back()
    assert not view._buttons.back.isEnabled()
    assert view._buttons.forward.isEnabled()


def test_undo_of_a_folder_delete_returns_to_that_folder(qtbot, tmp_path):
    db = Database(tmp_path / "g.db")
    for pid, prompt, steps in (("a", "alpha", 10), ("b", "beta", 20)):  # two settings folders
        db.insert_generation(prompt_id=pid, workflow_name="sdxl_t2i", workflow_version="v002",
                             positive_prompt=prompt, seed=1,
                             params_json=json.dumps({"positive_prompt": prompt, "seed": 1, "steps": steps}),
                             workflow_json="{}")
        db.update_generation(pid, status="completed",
                             output_files=json.dumps([{"filename": f"{pid}.png", "subfolder": ""}]))
    actions = GalleryActions(db, OutputPlaces.in_one_folder(tmp_path / "out"), Trash(tmp_path / "trash"))
    view = GalleryView(db, actions=actions)
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._leaf_by_id["a"])  # the folder holding "a"
    _click_tile(view, "a")                       # viewing it
    assert view._selected["prompt_id"] == "a"
    view._confirm = lambda text: True
    view._delete_folders(view._current_deletable_folders())
    assert db.get_generation("a") is None
    assert view._selected is None                       # navigated off the emptied folder

    view._undo()
    assert db.get_generation("a") is not None            # restored
    assert view._selected["prompt_id"] == "a"            # and back where we deleted from


def test_back_after_following_a_link_returns_to_the_viewed_generation(qtbot):
    # Viewing a generation, then following its source link, records both as history
    # stops; Back returns to the one we were looking at before the link.
    image = _image("img1", "a cat", 50, 1)
    video = _row("vid1", "wan22_i2v",
                 {"positive_prompt": "dance", "seed": 5,
                  "input_image": "sdxl_t2i_img1.png"},
                 "wan22_i2v_00001_.mp4")
    view = GalleryView(FakeDB([video, image]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["vid1"])
    _click_tile(view, "vid1")               # viewing the video
    assert view._selected["prompt_id"] == "vid1"

    view.follow_link("img1")                  # follow its source-image link
    assert view._selected["prompt_id"] == "img1"
    view._navigation.go_back()
    assert view._selected["prompt_id"] == "vid1"  # Back to where we were


def _linked_view(qtbot, source="i7", count=12):
    """A view on a video whose start frame is one of ``count`` sibling images, laid
    out in a window too short to hold them all — the setup for following a source
    link into a folder big enough that landing on the right image matters."""
    images = [_image(f"i{n}", "a cat", 50, n) for n in range(1, count + 1)]
    video = _row("vid1", "wan22_i2v",
                 {"positive_prompt": "dance", "seed": 5,
                  "input_image": f"sdxl_t2i_{source}.png"},
                 "wan22_i2v_00001_.mp4")
    view = GalleryView(FakeDB([video] + images))
    _on_screen(qtbot, view, 1100, 1200)
    view._tree.setCurrentItem(view._leaf_by_id["vid1"])
    _click_tile(view, "vid1")               # viewing the video
    return view


def test_following_a_source_link_lands_on_the_image_itself(qtbot):
    # Opening the folder the source image lives in isn't enough: with a dozen
    # siblings in it, which one the link meant has to be picked out — highlighted,
    # and scrolled to rather than left off the foot of the pane.
    view = _linked_view(qtbot)

    view.follow_link("i7")                    # follow its source-image link

    assert view.selected_prompt_ids() == ["i7"]
    assert view._gallery_pane._thumb_widgets["i7"]._selected
    assert _in_view(view, "i7")


def test_following_a_link_to_a_word_made_videos_hidden_frame_lands_on_that_video(qtbot, tmp_path):
    frame_file = tmp_path / "frames" / "f1.jpg"
    frame = {"prompt_id": "f1", "source": GenerationSource.STARTING_FRAME,
             "workflow_name": "outside picture:a-site", "workflow_version": "outside",
             "status": "completed", "params_json": "{}",
             "output_files": json.dumps([{"filename": "f1.jpg", "path": str(frame_file)}])}
    video = {"prompt_id": "o1", "source": GenerationSource.OUTSIDE,
             "workflow_name": "outside:a-site", "workflow_version": "outside",
             "status": "completed", "params_json": json.dumps({"input_image": str(frame_file)}),
             "output_files": json.dumps([{"filename": "c1_topaz.mp4",
                                          "library_path": str(tmp_path / "outbox" / "c1_topaz.mp4")}])}
    view = GalleryView(FakeDB([video, frame]))
    qtbot.addWidget(view)
    view.refresh()

    view.follow_link("f1")

    assert view.selected_prompt_ids() == ["o1"]
    assert view._selected["prompt_id"] == "o1"


def test_a_followed_link_puts_the_image_on_screen_in_the_same_turn(qtbot):
    # The folder's images are created but not yet positioned when the link lands,
    # so a scroll that aimed at them straight away would aim at nothing. The pane
    # lays itself out first, which is what puts the image on screen without
    # waiting for the turn to end.
    view = _linked_view(qtbot)

    view.follow_link("i7")

    assert _in_view(view, "i7")


def test_moving_on_after_a_followed_link_leaves_the_folder_chosen_instead(qtbot):
    # The link's landing is the folder it opened; choosing another folder after it
    # is the user overruling that, and what they chose is what stays on screen.
    view = _linked_view(qtbot)

    view.follow_link("i7")
    view._tree.setCurrentItem(view._leaf_by_id["vid1"])
    qtbot.wait(1)

    assert view.listed_prompt_ids() == ["vid1"]
    assert _scroll_bar(view).value() == 0


def test_history_spans_folder_navigation(qtbot):
    # Every place the user went is a stop: the folder they opened, on the item it
    # landed them on, so Back retraces the walk rather than skipping the folders.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2),
            _i2v_video("v1", "styleA")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["v1"])  # the video folder, landing on v1
    view._tree.setCurrentItem(view._leaf_by_id["i1"])  # then the image folder, on i1
    _click_tile(view, "i2")    # then its other item
    assert view._selected["prompt_id"] == "i2"

    view._navigation.go_back()                    # the image folder, on what it opened on
    assert view._tree.currentItem() is view._leaf_by_id["i1"]
    assert view._selected["prompt_id"] == "i1"

    view._navigation.go_back()                    # and out to the video folder, on its item
    assert view._tree.currentItem() is view._leaf_by_id["v1"]
    assert view._selected["prompt_id"] == "v1"  # Back walks generations across folders


def test_back_returns_to_the_latest_collection_then_forward_reopens_the_folder(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    view._gallery_pane._thumb_widgets["i2"].double_clicked.emit("i2")  # open i2 in its folder
    assert view._gallery_pane.showing_latest() is False
    assert view._buttons.back.isEnabled()                    # the collection is somewhere to go back to

    view._navigation.go_back()
    assert view._gallery_pane.showing_latest()                       # Back returns to the Latest collection

    view._navigation.go_forward()
    assert view._gallery_pane.showing_latest() is False              # Forward re-opens the folder
    assert view.selected_generation() == "i2"


def test_back_returns_to_a_collection_left_by_opening_a_folder(qtbot):
    # The reported bug: a folder was no history stop at all, so leaving Latest by
    # clicking one in the tree recorded nothing and Back had nowhere to go from —
    # the collection was on the stack, but the cursor was still sitting on it.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])

    view._tree.setCurrentItem(
        _at(_image_workflow(view._tree), 0, 0, 0)
    )
    assert view._gallery_pane.showing_latest() is False
    assert view._buttons.back.isEnabled()

    view._navigation.go_back()

    assert view._gallery_pane.showing_latest()


def test_back_walks_folders_the_way_it_walks_generations(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    lora = _at(_image_workflow(view._tree), 0, 0)
    cat, dog = _at(lora, 0), _at(lora, 1)
    view._tree.setCurrentItem(cat)
    view._tree.setCurrentItem(dog)

    view._navigation.go_back()

    assert view._tree.currentItem() is cat

    view._navigation.go_forward()

    assert view._tree.currentItem() is dog


def test_reopening_the_same_folder_is_not_a_second_history_stop(qtbot):
    # A rebuild re-selects the open folder every poll; each must not pile onto the
    # stack or Back would walk a hundred copies of where the user already is.
    rows = [_image("i1", "a cat", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    leaf = _at(_image_workflow(view._tree), 0, 0, 0)
    view._tree.setCurrentItem(leaf)
    depth = len(view._navigation._history._stack)

    view.refresh()
    view._poll()

    assert len(view._navigation._history._stack) == depth


def test_back_returns_to_the_favorite_collection_after_drilling_into_a_folder(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1),
            _image("i3", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    dog_key = _key(_at(_image_workflow(view._tree), 0, 0, 1))
    view._toggle_favorite(dog_key)

    view._tree.setCurrentItem(_alls(view._tree)["Favorites"])
    view._gallery_pane._drill_into(view._gallery_pane._listed_folders[0])  # into the dog folder, on i2
    _click_tile(view, "i3")            # view another item there
    assert view._tree.currentItem() is not _collection(view, FAVORITES_KEY)

    view._navigation.go_back()                                      # the folder drilled into
    view._navigation.go_back()
    assert view._tree.currentItem() is _collection(view, FAVORITES_KEY)  # Back returns to Favorites


def test_back_to_latest_restores_the_item_selected_on_the_collection(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    _click_tile(view, "i2")         # select i2 in the collection
    view._gallery_pane._thumb_widgets["i2"].double_clicked.emit("i2")  # open it in its folder
    assert view._gallery_pane.showing_latest() is False

    view._navigation.go_back()
    assert view._gallery_pane.showing_latest()                       # back in the collection...
    assert view.selected_generation() == "i2"            # ...with i2 previewed again
    assert view._gallery_pane._thumb_widgets["i2"]._selected       # and its tile re-highlighted


def test_previewing_on_the_collection_is_its_own_history_step(qtbot):
    # The reported bug: previews in a collection were collection state rather than stops, so
    # Back walked out of the collection entirely instead of to the one looked at before.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1),
            _image("i3", "a bird", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    for pid in ("i1", "i2", "i3"):
        _click_tile(view, pid)       # browse a few previews

    view._navigation.go_back()
    assert view._gallery_pane.showing_latest()                       # still in the collection...
    assert view.selected_generation() == "i2"            # ...on the one before

    view._navigation.go_back()
    assert view.selected_generation() == "i1"

    view._navigation.go_forward()
    assert view.selected_generation() == "i2"


def test_back_to_a_collection_item_re_highlights_its_tile(qtbot):
    # Landing means landing: the item previewed and its tile lit, so which of the
    # collection's items Back returned to is visible in the pane and not just the panel.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    _click_tile(view, "i1")
    _click_tile(view, "i2")

    view._navigation.go_back()

    assert view._gallery_pane._thumb_widgets["i1"]._selected
    assert not view._gallery_pane._thumb_widgets["i2"]._selected


def test_back_to_a_folder_item_re_highlights_its_tile(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["i1"])
    _click_tile(view, "i1")
    _click_tile(view, "i2")

    view._navigation.go_back()

    assert view.selected_generation() == "i1"
    assert view._gallery_pane._thumb_widgets["i1"]._selected


def test_a_poll_redrawing_a_search_is_not_a_stop(qtbot):
    # The results pane redraws for things that are not navigations — a rebuild, a
    # sort, a widening landing — and a stop per redraw would fill history with the
    # pane already on screen.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    _search_for(view, "cat")
    _click_tile(view, "i1")   # a hit picked among the results
    depth = len(view._navigation._history._stack)

    view.refresh()
    view._poll()
    view._search._on_sort_changed()

    assert len(view._navigation._history._stack) == depth


def test_back_onto_a_folder_of_sub_folders_drops_the_pick(qtbot):
    # A folder of folders has no item to land on, so that is what returning to it
    # shows — a pane still lit on the item Back just left looks like a dead press.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    lora = _at(_image_workflow(view._tree), 0, 0)
    view._tree.setCurrentItem(lora)                    # its sub-folders, none picked
    view._tree.setCurrentItem(view._leaf_by_id["i1"])  # down into one, landing on i1

    view._navigation.go_back()

    assert view._tree.currentItem() is lora   # the folder of folders...
    assert view._selected is None             # ...showing nothing picked


def test_an_item_looked_at_on_a_collection_goes_back_to_that_collection(qtbot):
    # A stop is a view, not just an item: the same generation sits in its own
    # folder too, and Back has to return to the pane it was actually picked in.
    rows = [_image("i1", "a cat", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    _click_tile(view, "i1")         # previewed in the collection
    view._tree.setCurrentItem(view._leaf_by_id["i1"])    # then off to its folder

    view._navigation.go_back()

    assert view._gallery_pane.showing_latest()
    assert view.selected_generation() == "i1"


def test_back_returns_to_the_search_results_a_hit_was_opened_from(qtbot):
    # A search owns the middle pane while it runs, so it is a view Back returns
    # to — with the query still in the field and the hits still drawn.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    _search_for(view, "cat")
    assert view.listed_prompt_ids() == ["i1"]
    view._gallery_pane._thumb_widgets["i1"].double_clicked.emit("i1")  # open the hit in its folder
    assert view._gallery_pane.showing_search() is False

    view._navigation.go_back()

    assert view._gallery_pane.showing_search()
    assert view._search.field.text() == "cat"
    assert view.listed_prompt_ids() == ["i1"]


def test_a_hit_previewed_in_the_results_is_a_stop_in_them(qtbot):
    # Clicking a result previews it without leaving the results, so Back returns
    # to the results themselves rather than to the hit's own folder.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat hat", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    _search_for(view, "cat")
    _click_tile(view, "i1")

    view._navigation.go_back()

    assert view._gallery_pane.showing_search()
    assert view._search.field.text() == "cat"


def test_typing_on_does_not_stack_a_stop_per_pause(qtbot):
    # One search field, one view: a query being narrowed re-draws the same pane, so
    # Back leaves the search rather than replaying every word on the way in.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat hat", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    lora = _at(_image_workflow(view._tree), 0, 0)
    view._tree.setCurrentItem(_children_by_prompt(lora)["a cat"])
    depth = len(view._navigation._history._stack)

    _search_for(view, "cat")
    _search_for(view, "cat h")
    _search_for(view, "cat hat")

    assert len(view._navigation._history._stack) == depth + 1

    view._navigation.go_back()
    assert view._gallery_pane.showing_search() is False


def test_the_folder_the_gallery_is_showing_is_the_one_it_reports(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    workflow = _image_workflow(view._tree)
    view._tree.setCurrentItem(workflow)
    # The row, side and all: reopening on the other side's copy of a folder is
    # reopening somewhere else.
    assert view.selected_folder() == oriented_key(_key(workflow), LANDSCAPE)


def test_naming_a_workflow_version_is_what_puts_it_in_the_folder_key(qtbot):
    # The key names the tree leaf a run lands in, and five call sites used to
    # build the row it is derived from by hand -- one leaving the workflow version
    # out, two putting it in, two spreading a whole row -- so a reader could not
    # tell which of those differences meant anything. It does mean something: the
    # version is part of the signature, and it is an argument now rather than a
    # field one dict happened to carry.
    row = _image("i1", "a cat", 50, 1)
    view = GalleryView(FakeDB([row]))
    qtbot.addWidget(view)
    view.refresh()
    params = json.loads(row["params_json"])
    version = row["workflow_version"]

    assert view.folder_key_for(row["workflow_name"], params, version)         == view.folder_key_of(row)
    assert view.folder_key_for(row["workflow_name"], params)         != view.folder_key_of(row)


def test_the_folder_key_index_is_rebuilt_when_the_image_rows_are(qtbot):
    # Memoized because it was rebuilt from scratch at eight sites, several on a
    # click's path -- but an i2v's folder key is derived against it, so a stale
    # one would file a run under the start frame the gallery used to hold.
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    first = view.image_config_index()
    assert view.image_config_index() is first          # asked twice, built once

    db._rows.append(_image("i2", "a dog", 50, 2))
    view.refresh()

    assert view.image_config_index() is not first
    assert len(view.image_config_index()) > len(first)


def test_select_folder_restores_choice_in_a_fresh_view(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    db = FakeDB(rows)
    saved = GalleryView(db)
    qtbot.addWidget(saved)
    saved.refresh()
    # SDXL workflow -> model -> "(no LoRA)" -> dog settings leaf (cat is sibling 0).
    dog_leaf = _at(_image_workflow(saved._tree), 0, 0, 1)
    saved._tree.setCurrentItem(dog_leaf)
    saved_key = saved.selected_folder()
    chosen = set(saved.listed_prompt_ids())

    # A brand-new view told to restore that key lands on the same folder.
    restored = GalleryView(db)
    qtbot.addWidget(restored)
    restored.select_folder(saved_key)
    restored.refresh()
    assert restored.selected_folder() == saved_key
    assert set(restored.listed_prompt_ids()) == chosen


def test_select_folder_falls_back_to_default_when_key_gone(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.select_folder("video/ghost")  # nothing in the tree matches
    view.refresh()
    assert view.selected_folder() is not None  # default folder, not a crash


def test_selected_folder_reports_pending_target_before_first_show(qtbot):
    # The window restores a folder, but the user never opens the Gallery tab;
    # selected_folder must still report it so closeEvent can persist it again.
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.select_folder("image/sdxl_t2i")
    assert view.selected_folder() == "image/sdxl_t2i"


def test_selected_generation_tracks_thumbnail_click(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["i1"])  # folder holding i1 and i2
    view._on_thumbnail_clicked("i2")
    assert view.selected_generation() == "i2"


def test_select_generation_restored_with_folder_after_refresh(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    db = FakeDB(rows)
    probe = GalleryView(db)
    qtbot.addWidget(probe)
    probe.refresh()
    probe._tree.setCurrentItem(probe._leaf_by_id["i1"])
    folder_key = probe.selected_folder()

    # A fresh view restoring that folder + selection lands on the same image.
    fresh = GalleryView(db)
    qtbot.addWidget(fresh)
    fresh.select_folder(folder_key)
    fresh.select_generation("i2")
    fresh.refresh()
    assert fresh.selected_generation() == "i2"
    assert fresh._selected["prompt_id"] == "i2"


def test_selected_generation_survives_a_rebuild(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    db = FakeDB(rows)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["i1"])
    view._on_thumbnail_clicked("i2")

    db.add(_image("i3", "a dog", 50, 9))  # new generation → a poll rebuild
    view._poll()

    assert view.selected_generation() == "i2"  # not cleared by the rebuild
    assert view._selected["prompt_id"] == "i2"


def test_selected_generation_reports_pending_before_show(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.select_generation("i1")
    assert view.selected_generation() == "i1"


def test_select_generation_missing_id_is_dropped(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.select_generation("ghost")  # no such generation
    view.refresh()
    # Quietly dropped (not restored) without crashing; the view falls back to
    # the folder's own default selection rather than the stale id.
    assert view.selected_generation() != "ghost"


# --- the Enhance subpanel: the app's enhancement settings -------------------


def test_the_panes_keep_their_contents_the_standard_margin_off_their_edges(qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.resize(1500, 900)
    view.show()
    for _ in range(4):  # a relayout of the settings posts the pass that fits the foot
        QApplication.processEvents()

    for inside in (view._tree, view._scroll, view._osr2_controls, view._enhance.panel):
        pane = _pane_holding(inside)
        room = pane.rect().marginsRemoved(QMargins(*[MARGIN_STANDARD] * 4))
        for child in pane.findChildren(
                QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
            if child.isVisible():
                assert room.contains(child.geometry()), (type(inside).__name__, child)


def test_the_hud_sits_top_left_over_the_search_with_a_draggable_divider_between(
        qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    divider = _pane_holding(view._osr2_controls).parentWidget()

    assert view._arrangement.folder_panes.widget(0) is divider
    assert divider.orientation() == Qt.Orientation.Vertical
    assert divider.widget(0).isAncestorOf(view._osr2_controls)
    assert any(divider.widget(n).isAncestorOf(view._search.field)
               for n in range(1, divider.count()))
    assert divider.handleWidth() == view._arrangement.panes.handleWidth()


def test_a_draggable_divider_parts_the_thumbnails_from_the_panels_below(qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    divider = _pane_holding(view._scroll).parentWidget()

    assert isinstance(divider, QSplitter)
    assert divider.orientation() == Qt.Orientation.Vertical
    assert divider.widget(0).isAncestorOf(view._scroll)
    assert divider.widget(1).isAncestorOf(view._enhance.panel)
    assert divider.handleWidth() == view._arrangement.panes.handleWidth()


def test_with_room_to_spare_the_enhance_settings_under_the_thumbnails_open_whole(qtbot,
                                                                               tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.resize(1500, 1100)
    view.show()
    for _ in range(4):  # a relayout of the settings posts the pass that fits the foot
        QApplication.processEvents()
    (settings,) = view._enhance.panel.findChildren(QScrollArea)

    assert settings.verticalScrollBar().maximum() == 0


def test_with_room_to_spare_the_hud_opens_whole_at_the_top_left_even_at_its_widest(
        qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path), client=_reroll_client(),
                       osr2_motion=_SignalMotion())
    qtbot.addWidget(view)
    view.resize(1500, 1100)
    view.show()
    view.osr2_control.setChecked(True)  # the Robot Hand driving, its widest line
    for _ in range(4):
        QApplication.processEvents()
    (hud,) = _pane_holding(view._osr2_controls).findChildren(QScrollArea)

    assert hud.horizontalScrollBar().maximum() == 0
    assert hud.verticalScrollBar().maximum() == 0


def test_the_enhance_settings_take_the_whole_foot_under_the_thumbnails(qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    divider = _pane_holding(view._scroll).parentWidget()

    assert divider.widget(1) is _pane_holding(view._enhance.panel)


def test_squeezed_smaller_than_the_hud_its_pane_scrolls_rather_than_spilling(qtbot,
                                                                           tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.resize(1500, 900)
    view.show()
    QApplication.processEvents()
    over_the_search = _pane_holding(view._osr2_controls).parentWidget()

    view._arrangement.folder_panes.moveSplitter(60, 1)
    over_the_search.moveSplitter(90, 1)
    QApplication.processEvents()
    (hud,) = over_the_search.widget(0).findChildren(QScrollArea)

    assert hud.horizontalScrollBar().maximum() > 0
    assert hud.verticalScrollBar().maximum() > 0


# --- the pane→view wiring: each pane gesture reaches its view handler --------


#
# The Gallery pane connects its tiles' signals straight to view handlers today,
# and the coupling inversion (audit item 30) re-routes every one of these wires
# through a pane signal. Each test here drives the wire end to end — emit the
# widget's own signal, observe the app-level consequence — so a re-route that
# quietly drops a wire fails a test instead of a spoken command or a click.


def test_the_experiment_tiles_keep_corner_records_the_verdict(qtbot):
    db = FakeDB([_experiment_row("e1")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, EXPERIMENTS_KEY))

    view._gallery_pane._thumb_widgets["e1"].corner_button_triggered.emit("e1", "keep")

    assert db.get_generation("e1")["experiment_verdict"] == "up"


def test_a_tiles_star_corner_favorites_that_tile(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    view._gallery_pane._thumb_widgets["i1"].control_triggered.emit(
        "i1", corner_buttons.STAR)

    assert db.get_generation("i1")["starred"]


def test_right_clicking_a_folder_tile_raises_the_folder_menu(qtbot, monkeypatch):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_image_workflow(view._tree))  # child folders as tiles
    labels = []
    _menu_labels(monkeypatch, labels)
    model = _key(_at(_image_workflow(view._tree), 0))
    (tile,) = [tile for tile in view._scroll.widget().findChildren(FolderTile)
               if tile.key == model]

    tile.context_requested.emit(model, QPoint(1, 1))

    assert "Favorite" in labels


def test_an_i2v_tiles_video_seed_corner_starts_that_folders_reroll(
        qtbot, tmp_path):
    view = GalleryView(_single_i2v_db(tmp_path, "handpicked.png"), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    leaf = view._leaf_by_id["vid"]
    view._tree.setCurrentItem(leaf)

    view._gallery_pane._thumb_widgets["vid"].corner_button_triggered.emit("vid", "video")

    (job,) = [job for jobs in view._jobs.jobs_by_folder.values() for job in jobs]
    assert job.workflow.name == "wan22_i2v"


def test_a_queue_items_cancel_drops_that_run(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.add(_running_row("rr1", prompt="a cat"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    folder_key = _key(_at(_image_workflow(view._tree), 0, 0))
    view._jobs._jobs[folder_key] = [_FakeRerollJob(
        "rr1", "sdxl_t2i", {"positive_prompt": "a cat"}, state="running")]

    (item,) = [it for it in view._inflight_items() if it.key == "rr1"]
    item.cancel()

    assert view._jobs.jobs_by_folder.get(folder_key, []) == []
    assert db.get_generation("rr1") is None


# --- the poll's batched fetch: every blocking read of one tick, in one place --


def test_the_poll_fetch_asks_only_what_each_jobs_state_deserves():
    calls = []

    class _Client:
        def fetch_history(self, prompt_id):
            calls.append(("history", prompt_id))
            return {"outputs": {}}

        def foreign_backlog(self, prompt_id):
            calls.append(("backlog", prompt_id))
            return 2

        def foreign_queue(self):
            calls.append(("queue", None))
            return ForeignQueue(running=[], pending=[])

        def executing_prompts(self):
            calls.append(("executing", None))
            return {"q1"}

    facts = gallery_view_module._fetch_poll_facts(
        _Client(),
        [("q1", "queued"), ("r1", "running"), ("f1", "finished")])

    # /history for a job that may have quietly finished; a queue position only
    # for one still waiting, and what ComfyUI is making once while any waits;
    # nothing at all for a terminal job; the shared queue once.
    assert calls == [("history", "q1"), ("backlog", "q1"),
                     ("history", "r1"), ("executing", None), ("queue", None)]
    assert set(facts.histories) == {"q1", "r1"}
    assert facts.backlogs == {"q1": 2}
    assert facts.executing == {"q1"}


def test_the_poll_asks_nothing_of_what_comfyui_is_making_while_no_job_waits_there():
    class _Client:
        def fetch_history(self, prompt_id):
            return {}

        def foreign_queue(self):
            return ForeignQueue(running=[], pending=[])

        def executing_prompts(self):
            raise AssertionError("asked with nothing waiting on the server")

    facts = gallery_view_module._fetch_poll_facts(_Client(), [("r1", "running")])

    assert facts.executing == frozenset()


def test_the_poll_tells_each_job_whether_comfyui_is_making_it(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    jobs = [_FakeRerollJob(pid, "sdxl_t2i", {}, state="queued")
            for pid in ("made", "waiting")]
    heard = []
    for job in jobs:
        job.take_executing = lambda executing, pid=job.prompt_id: heard.append(
            (pid, executing))

    view._apply_poll_facts(
        jobs, gallery_view_module._PollFacts({}, {}, None, frozenset({"made"})))

    assert heard == [("made", True), ("waiting", False)]


def test_the_poll_fetch_fails_soft_read_by_read():
    class _Wedged:
        def fetch_history(self, prompt_id):
            raise OSError("connection refused")

        def foreign_backlog(self, prompt_id):
            raise OSError("connection refused")

        def foreign_queue(self):
            raise OSError("connection refused")

        def executing_prompts(self):
            raise OSError("connection refused")

    facts = gallery_view_module._fetch_poll_facts(_Wedged(), [("q1", "queued")])

    assert facts.histories == {}          # nothing fetched: reconcile skips it
    assert facts.backlogs == {"q1": None}  # an unreadable position clears the count
    assert facts.foreign.total == 0        # an unreadable queue claims nothing
    assert facts.executing == frozenset()  # and names nothing as being made


def test_the_poll_fetch_reads_nothing_with_no_client():
    facts = gallery_view_module._fetch_poll_facts(None, [("q1", "queued")])

    assert facts == gallery_view_module._PollFacts({}, {}, None)


def test_an_event_about_an_object_already_gone_does_not_take_the_app_down(qtbot):
    """The gallery watches the whole application for its keys, so it is handed
    events about every object in it — a slideshow's own timer among them, which is
    destroyed with the slideshow while events about it are still in flight.  Asking
    the base class about one of those dereferences a freed object and takes the
    process down with it (2026-09-19 21:26, a Latest slideshow closing)."""
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    doomed = QTimer()
    sip.delete(doomed)

    assert view.eventFilter(doomed, QEvent(QEvent.Type.Timer)) is False


def test_the_view_looks_for_a_preview_where_its_actions_were_pointed(qtbot, tmp_path,
                                                                     monkeypatch):
    """The two folders a preview is resolved out of used to be read off the config
    module in the middle of the method, so the only way to point a view at a
    library of its own was to patch module state -- which four tests did while
    three thousand ran against the live one. They are the actions' now, and the
    actions are handed both at construction."""
    asked = []
    monkeypatch.setattr(
        gallery, "animated_preview_if_made",
        lambda row, places, thumb_dir: asked.append((places, thumb_dir)))
    view = GalleryView(_trash_db(), actions=FakeActions(places=OutputPlaces.in_one_folder(tmp_path / "output"),
                                                 thumb_dir=tmp_path / "thumbs"))
    qtbot.addWidget(view)

    view.animated_preview({"prompt_id": "p1"})

    assert asked == [(OutputPlaces.in_one_folder(tmp_path / "output"), tmp_path / "thumbs")]


def test_a_folders_hover_says_its_name_and_nothing_else(qtbot):
    # The name is a short code, and what the folder holds used to ride on the
    # hover: the prompt and the settings that set it apart, each cut to 24
    # characters. Cut that short it said nothing you could act on, so it is gone.
    rows = [_image("i1", "a cat asleep on a windowsill in the late sun", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    (leaf,) = _subs(_at(_image_workflow(view._tree), 0, 0))

    assert leaf.toolTip(0).startswith(leaf.text(0))
    assert "a cat" not in leaf.toolTip(0)
