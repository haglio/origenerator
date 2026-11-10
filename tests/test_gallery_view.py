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
from shared_ui.colors import GREEN, RED, YELLOW
from shared_ui.icons import icon_then_text
from shared_ui.spacing import MARGIN_STANDARD

from origenerator import (
    gallery,
    outside_videos,
)
from origenerator.branch_session import ENV_FLAG
from origenerator.comfyui_api import ForeignQueue
from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database, NewGeneration
from origenerator.gallery import tree as gallery_tree_module
from origenerator.gallery.collection import (
    ENHANCED_KEY,
    EXPERIMENTS_KEY,
    FAVORITES_KEY,
    TRASH_KEY,
)
from origenerator.gallery.labels import workflow_label
from origenerator.gallery.shapes import LANDSCAPE, PORTRAIT, SHAPE_LABELS, TOGETHER
from origenerator.gallery_edits import GalleryEdits
from origenerator.generation_state import GenerationSource
from origenerator.gui import (
    corner_buttons,
    icons,
    off_thread,
)
from origenerator.gui import gallery_view as gallery_view_module
from origenerator.gui.folder_tile import FolderTile
from origenerator.gui.folder_tree import RECENT_ROLE
from origenerator.gui.gallery_view import _GROUP_ROLE, GalleryView, Shared
from origenerator.item_shape import shaped_key
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
    _shape,
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
    names = []
    for i in range(item.childCount()):
        if item.child(i).data(0, _GROUP_ROLE) is not None:
            break
        names.append(item.child(i).text(0))
    return names


def test_refresh_builds_workflow_model_settings_tree(qtbot):
    rows = [
        _image("i1", "a cat", 50, 1),
        _image("i2", "a cat", 50, 2),
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
    assert len(_subs(workflow_node)) == 1
    assert len(_subs(_at(workflow_node, 0))) == 1
    assert len(_subs(_at(workflow_node, 0, 0))) == 1


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
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    asked = []

    def fake(trees, rows, *args, **kwargs):
        asked.append((sorted(trees), [row["prompt_id"] for row in rows]))
        return {(LANDSCAPE, "image/sdxl_t2i")}

    monkeypatch.setattr(gallery, "recently_worked_folders", fake)
    view.refresh()

    assert asked == [([LANDSCAPE, "portrait"], ["i1"])]

    view._tree.together_button.click()

    assert asked[-1] == (["both"], ["i1"])
    view._tree.separate_button.click()
    workflow = _image_workflow(view._tree)
    assert workflow.data(0, RECENT_ROLE)
    assert "worked in recently" in workflow.toolTip(0)
    assert not _at(workflow, 0).data(0, RECENT_ROLE)


def test_tree_rows_carry_a_toc_initial(qtbot):
    view = GalleryView(FakeDB([_i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()

    workflow = _video_workflow(view._tree)
    model = _at(workflow, 0)
    lora = _at(model, 0)
    source = _at(lora, 0)
    settings = _at(source, 0)

    assert not workflow.icon(0).isNull()
    assert "Workflow" in workflow.toolTip(0)
    assert not model.icon(0).isNull()
    assert "Model" in model.toolTip(0)
    assert not lora.icon(0).isNull()
    assert lora.toolTip(0).endswith("· LoRA")
    assert not source.icon(0).isNull()
    assert "Source Image" in source.toolTip(0)
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
    # Qt lays the text out after the icon, so the text's edge steps unevenly between rows with and without one.
    rows = [_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]
    view = GalleryView(FakeDB(rows))
    _on_screen(qtbot, view, 1200, 800)
    tree = _shape(view._tree)
    step = tree.indentation()
    assert step <= 16

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
    assert all(len(xs) == 1 for xs in starts.values()), starts
    at = [next(iter(starts[d])) for d in sorted(starts)]
    assert [b - a for a, b in pairwise(at)] == [step] * (len(at) - 1)


def test_selecting_a_folder_shows_its_full_name_as_a_title(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    workflow = _image_workflow(view._tree)
    view._tree.setCurrentItem(workflow)
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

    lora = _at(_image_workflow(view._tree), 0, 0)
    view._tree.setCurrentItem(lora)
    assert len(view._gallery_pane._listed_folders) == 2
    assert view.listed_prompt_ids() == []

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

    lora = _at(_image_workflow(view._tree), 0, 0)
    view._tree.setCurrentItem(lora)
    a_tile_key = view._gallery_pane._listed_folders[0]

    view._gallery_pane._drill_into(a_tile_key)
    assert view.listed_prompt_ids()


def test_opening_a_folder_lands_on_its_first_item(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._leaf_by_id["i1"])

    assert view.listed_prompt_ids()[0] == "i1"
    assert view.selected_generation() == "i1", (
        "picking a folder is picking what is in it, so it opens ready to work in rather than beside "
        "whatever the tab in front happened to hold")
    assert view.selected_prompt_ids() == ["i1"]
    tab = view._generate_pane.current_generate_tab()
    assert tab.displayed_row()["prompt_id"] == "i1"
    assert view._generate_pane._preview_tab is tab


def _first_leaf(view):
    return _at(_image_workflow(view._tree), 0, 0, 0)


def test_the_all_row_holds_images_and_videos_and_is_where_the_gallery_lands(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    all_row = _top_level(view._tree)["All"]
    assert [row.text(0) for row in _subs(all_row)] == ["Images", "Videos"]
    assert all_row.isExpanded()
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
        kino=tmp_path / "kino", records_folder=tmp_path / "records",
        frames_dir=tmp_path / "frames", thumb_dir=tmp_path / "thumbs",
        skip_sources=frozenset(), library_root=tmp_path, journal=journal))
    view = GalleryView(FakeDB([video]))
    qtbot.addWidget(view)
    view.refresh()

    view.set_items_favorite(["o1"], True)

    [line] = journal.read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["event"] == "favorite"


def _square_texts(view, key) -> list[str]:
    (square,) = [tile for tile in view._scroll.widget().findChildren(FolderTile)
                 if tile.key == key]
    return [label.text() for label in square.findChildren(QLabel)]


def test_clicking_the_star_beside_a_folder_stars_its_square_in_the_pane_beside_it(qtbot):
    view, cat, dog = _two_leaf_view(qtbot)
    view._tree.setCurrentItem(view._tree_item_for(cat).parent())

    _click_beside_the_mark_of(qtbot, view, dog, which=0)

    assert any(text.startswith("<img") and text.endswith(view.group_for_key(dog).label)
               for text in _square_texts(view, dog))
    assert not any(text.startswith("<img") for text in _square_texts(view, cat))


def test_a_folder_the_user_made_takes_no_favorite(qtbot):
    view, cat, _dog = _two_leaf_view(qtbot)
    made = gallery.custom_collection_key(_make_folder(view, "Mine", [cat]))

    view._toggle_favorite(made)

    assert not view.group_for_key(made).favorite


def test_the_favorite_button_offers_to_take_back_the_favorite_it_just_made(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    _click_off(view)

    view._buttons.favorite.click()

    assert view._buttons.favorite.toolTip().startswith("Unfavorite folder")


def test_unfavoriting_a_folder_takes_it_off_the_open_favorites_collection(qtbot):
    view, _cat, dog = _two_leaf_view(qtbot)
    view._toggle_favorite(dog)
    view._tree.setCurrentItem(_collection(view, FAVORITES_KEY))
    assert view._gallery_pane._listed_folders == [dog]

    view._toggle_favorite(dog)

    assert view._gallery_pane._listed_folders == []
    assert _shown(_collection(view, FAVORITES_KEY)) == "Favorites"


def _long_list_view(qtbot):
    view = GalleryView(FakeDB([_image(f"i{n}", f"prompt {n}", 50, n) for n in range(30)]))
    _on_screen(qtbot, view, 700, 500)
    lora = _at(_image_workflow(view._tree), 0, 0)
    for item in (lora.parent().parent(), lora.parent(), lora):
        item.setExpanded(True)
    return view, _subs(lora)


def test_starring_a_folder_marks_its_row_where_it_stands(qtbot):
    view, folders = _long_list_view(qtbot)
    half = _shape(view._tree)
    view._tree.setCurrentItem(folders[0])
    half.scrollToItem(folders[-1])
    target, key = folders[-1], _key(folders[-1])
    scrolled_to = half.verticalScrollBar().value()
    assert scrolled_to > 0

    view._toggle_favorite(key)

    assert view._tree_item_for(key) is target
    assert target.data(0, _GROUP_ROLE).favorite
    assert half.verticalScrollBar().value() == scrolled_to


def test_starring_a_folder_marks_it_on_both_sides_of_the_list(qtbot):
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
    view, cat, dog = _two_leaf_view(qtbot)
    view._tree.setCurrentItem(view._tree_item_for(cat).parent())
    view._tree.setCurrentItem(view._tree_item_for(cat))

    view._toggle_favorite(dog)

    assert view.group_for_key(dog).favorite


def test_the_tick_after_a_star_finds_nothing_to_redraw(qtbot):
    view, _cat, dog = _two_leaf_view(qtbot)
    view._toggle_favorite(dog)
    row = view._tree_item_for(dog)

    view._poll()

    assert view._tree_item_for(dog) is row


def test_each_tick_puts_what_a_slideshow_is_locked_on_first(qtbot, monkeypatch):
    view, _cat, _dog = _two_leaf_view(qtbot)
    ticks = []
    monkeypatch.setattr(view._enhance, "put_what_is_locked_first", lambda: ticks.append(1))

    view._poll()

    assert ticks == [1]


def test_a_reading_of_the_library_taken_before_a_star_does_not_take_it_back(qtbot,
                                                                            monkeypatch):
    view, _cat, dog = _two_leaf_view(qtbot)
    held = []
    monkeypatch.setattr(view, "off_thread", lambda work, done: held.append((work(), done)))
    view._finish_poll([], None)

    view._toggle_favorite(dog)
    row = view._tree_item_for(dog)
    (reading, deliver), = held
    deliver(reading)

    assert view._tree_item_for(dog) is row
    assert row.data(0, _GROUP_ROLE).favorite


def test_favoriting_a_folder_persists_without_reordering(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    db = FakeDB(rows)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    lora = _at(_image_workflow(view._tree), 0, 0)
    cat_key = _key(_at(lora, 0))
    dog_key = _key(_at(lora, 1))
    view._toggle_favorite(dog_key)

    assert db.folder_meta_map()[dog_key]["starred"] is True
    lora = _at(_image_workflow(view._tree), 0, 0)
    assert [_key(row) for row in _subs(lora)] == [cat_key, dog_key]
    assert _at(lora, 1).data(0, _GROUP_ROLE).favorite is True
    assert _at(lora, 0).data(0, _GROUP_ROLE).favorite is False
    assert not _at(lora, 1).text(0).startswith("★")


def test_favoriting_a_folder_from_its_menu_leaves_it_open(qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    db = FakeDB(rows)
    view = GalleryView(db)
    _on_screen(qtbot, view, 600, 600)

    tree = view._tree
    _top_level(tree)["All"].setExpanded(True)
    images = _image_workflow(tree)
    images.setExpanded(True)
    key = _key(images)
    half = _shape(tree, LANDSCAPE)
    row = half.visualRect(half.indexFromItem(images))
    caret = QPoint(row.left() - half.indentation() // 2, row.center().y())

    qtbot.mouseClick(half.viewport(), Qt.MouseButton.RightButton, pos=caret)
    monkeypatch.setattr(
        "origenerator.gui.gallery_view.QMenu.exec",
        lambda menu, *a: next(act for act in menu.actions() if act.text() == "Favorite"),
    )
    view._on_tree_context_menu(images, caret, LANDSCAPE)

    assert db.folder_meta_map()[key]["starred"] is True
    assert _image_workflow(view._tree).isExpanded(), (
        "the menu covers the TOC, so a right-click that shut the folder on the way in is seen only "
        "once the menu closes")


def test_favorite_collection_is_pinned_first_and_collects_favorite_folders(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    db = FakeDB(rows)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    lora = _at(_image_workflow(view._tree), 0, 0)
    dog_key = _key(_at(lora, 1))
    view._toggle_favorite(dog_key)

    assert list(_alls(view._tree))[:2] == ["Latest", "Favorites"]
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

    view._toggle_favorite(_key(cat))

    alls = _alls(view._tree)
    assert _shown(alls["Favorites"]) == "(2) Favorites"
    assert _shown(_top_level(view._tree)["All"]) == "(3) All"
    assert _shown(alls["Latest"]) == "Latest"


def test_experiments_collection_is_always_reachable(qtbot):
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
    experiment = _experiment_row("e1", steps=30)
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), experiment]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_collection(view, EXPERIMENTS_KEY))
    view._gallery_pane._thumb_widgets["e1"].double_clicked.emit("e1")

    assert _selected_folder(view) == gallery.settings_folder_key(experiment)
    assert view.listed_prompt_ids() == ["e1"]
    assert view.selected_prompt_ids() == ["e1"]
    assert view._gallery_pane._thumb_widgets["e1"]._selected


def test_keeping_an_experiment_clears_it_from_the_review_queue(qtbot):
    db = FakeDB([_experiment_row("e1")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    assert "SDXL T2I" in _workflow_rows(view._tree)

    view._on_experiment_verdict("e1", "keep")

    assert db.get_generation("e1")["experiment_verdict"] == "up"
    view._tree.setCurrentItem(_collection(view, EXPERIMENTS_KEY))
    assert view.listed_prompt_ids() == []
    assert "SDXL T2I" in _workflow_rows(view._tree)


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

    view._on_reroll_finished("some-key", "e1")
    assert shown == []

    view._on_reroll_finished("some-key", "i1")
    assert [r["prompt_id"] for r in shown] == ["i1"]


def test_the_experiments_switch_reports_what_each_position_means(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    view.refresh()
    assert view.experiments_enabled() is False
    assert "Off" in view._experiments_status.text()

    view.set_experiments_enabled(True)
    assert view.experiments_enabled() is True
    assert view._experiments_cb.isChecked()
    assert "close the app" in view._experiments_status.text()

    view._experiments_cb.setChecked(False)
    assert view.experiments_enabled() is False
    assert "Off" in view._experiments_status.text()


def test_an_open_app_queues_no_experiments_however_the_switch_is_set(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db, client=ComfyUIClient(folders=SUITE_FOLDERS))
    qtbot.addWidget(view)
    view.refresh()

    view.set_experiments_enabled(True)

    assert [r for r in db.list_generations() if r.get("source") == "experiment"] == []


def test_a_branch_session_schedules_no_experiments_at_all(qtbot, monkeypatch):
    monkeypatch.setenv(ENV_FLAG, "1")
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db, client=ComfyUIClient(folders=SUITE_FOLDERS))
    qtbot.addWidget(view)
    view.refresh()

    view.set_experiments_enabled(True)

    assert view.experiments_enabled() is False
    assert not view._experiments_cb.isEnabled()
    assert "production app" in view._experiments_status.text()

    view._experiments_cb.setChecked(True)

    assert [r for r in db.list_generations() if r.get("source") == "experiment"] == []


def test_a_branch_session_reviews_experiments_like_the_live_app(qtbot, monkeypatch):
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

    lora = _at(_image_workflow(view._tree), 0, 0)
    dog_key = _key(_at(lora, 1))
    view._toggle_favorite(dog_key)

    collection = _alls(view._tree)["Favorites"]
    view._tree.setCurrentItem(collection)
    view._gallery_pane._drill_into(view._gallery_pane._listed_folders[0])
    assert set(view.listed_prompt_ids()) == {"i2"}


def test_favorite_collection_shows_empty_state_when_nothing_is_favorite(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    collection = _alls(view._tree)["Favorites"]
    view._tree.setCurrentItem(collection)
    assert view._gallery_pane._listed_folders == []
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
    assert view.listed_prompt_ids() == ["i2"]
    assert view._gallery_pane._thumb_widgets["i2"]._favorite is True


def test_favorite_collection_shows_both_favorite_items_and_folders(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    db = FakeDB(rows)
    db.set_generation_favorite("i1", True)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    lora = _at(_image_workflow(view._tree), 0, 0)
    dog_key = _key(_at(lora, 1))
    view._toggle_favorite(dog_key)

    collection = _alls(view._tree)["Favorites"]
    view._tree.setCurrentItem(collection)
    assert view.listed_prompt_ids() == ["i1"]
    assert view._gallery_pane._listed_folders == [dog_key]


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
    assert view.listed_prompt_ids() == []


def test_favorite_collection_stays_selected_across_a_refresh(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Favorites"])

    view.refresh()

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
        f"{SHAPE_LABELS[LANDSCAPE]}  \u203a  All  \u203a  Images  \u203a  {workflow.text(0)}  \u203a  Latest")


def test_a_folders_collection_names_itself_by_its_path_to_the_slideshow_button(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    workflow = _image_workflow(view._tree)

    view._tree.setCurrentItem(workflow.child(0))

    assert view.slideshow_subject() == (
        f"{SHAPE_LABELS[LANDSCAPE]}  \u203a  All  \u203a  Images  \u203a  {workflow.text(0)}  \u203a  Latest")


def test_latest_collection_is_pinned_first_and_lists_recent_items(qtbot):
    rows = [_image("i2", "a dog", 50, 2), _image("i1", "a cat", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    assert next(iter(_alls(view._tree))) == "Latest"
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    assert view.listed_prompt_ids() == ["i2", "i1"]
    assert view._gallery_pane._listed_folders == []


def test_latest_collection_lists_imported_files_too(qtbot):
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
    _click_tile(view, "i2")
    assert view.selected_generation() == "i2"
    assert view._gallery_pane.showing_latest()
    assert set(view.listed_prompt_ids()) == {"i1", "i2"}


def test_double_clicking_a_recent_item_opens_it_selected_in_its_folder(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    view._gallery_pane._thumb_widgets["i2"].double_clicked.emit("i2")
    assert view.selected_generation() == "i2"
    assert view._gallery_pane.showing_latest() is False
    assert set(view.listed_prompt_ids()) == {"i2"}
    assert view.selected_prompt_ids() == ["i2"]
    assert view._gallery_pane._thumb_widgets["i2"]._selected


def test_double_clicking_a_recent_item_also_keeps_its_tab(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    _click_tile(view, "i2")
    assert view._generate_pane._preview_tab is not None

    view._gallery_pane._thumb_widgets["i2"].double_clicked.emit("i2")

    assert view._generate_pane._preview_tab is None


def test_latest_collection_shows_empty_state_when_nothing_has_a_result(qtbot):
    pending = _row("wip", "sdxl_t2i", {"seed": 9}, "wip.png", status="running", output_files=None)
    view = GalleryView(FakeDB([pending]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    assert view.listed_prompt_ids() == []


def test_latest_collection_stays_selected_across_a_refresh(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])

    view.refresh()

    assert view._tree.currentItem().text(0) == "Latest"


def _many_latest(count):
    return [_image(f"i{n}", "a cat", 50, n) for n in reversed(range(count))]


def test_latest_opens_on_one_page_however_far_back_it_goes(qtbot):
    view = GalleryView(FakeDB(_many_latest(120)))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    assert len(_drawn(view)) == 50
    assert _drawn(view)[0] == "i119"


def _scroll_to_the_end(view):
    QApplication.processEvents()
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
    db = FakeDB(_many_latest(120))
    view = GalleryView(db)
    _on_screen(qtbot, view, 1800, 1300)
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    _scroll_to_the_end(view)
    scrolled_into = _drawn(view)

    db._rows.insert(0, _image("fresh", "a dog", 50, 999))
    view.refresh()

    assert _drawn(view) == ["fresh", *scrolled_into]


def test_a_double_click_on_an_image_in_latest_plays_everything_latest_lists(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB(_many_latest(120)))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])

    slideshow = view._slideshows.open_in_its_folder(("i119.png", "image"), "i119")
    qtbot.addWidget(slideshow.shown)

    assert len(slideshow._set.playlist.in_play_order()) == 120
    slideshow.close()


def test_a_double_clicked_tile_plays_its_folder_from_it(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB(_many_latest(120)))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])

    view._gallery_pane._thumbnail_double_clicked("i110")
    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)

    assert len(slideshow._set.playlist.in_play_order()) == 120
    assert slideshow._set.current_prompt_id() == "i110"
    slideshow.close()


def test_a_double_clicked_preview_plays_its_item_alone_locked(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    view = GalleryView(FakeDB(_many_latest(120)))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])

    slideshow = view._slideshows.open_on_preview(("i119.png", "image"), "i119")
    qtbot.addWidget(slideshow.shown)

    assert [item[2] for item in slideshow._set.playlist.in_play_order()] == ["i119"]
    assert slideshow.locked
    slideshow.close()


def test_alls_latest_lists_both_kinds(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_alls(view._tree)["Latest"])

    assert set(view.listed_prompt_ids()) == {"i1", "v1"}


def test_the_shapes_radio_wears_the_waiting_cursor_while_it_redraws(qtbot, monkeypatch):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()
    while_drawing = []
    real = view.refresh
    monkeypatch.setattr(view, "refresh", lambda *a: (
        while_drawing.append(QApplication.overrideCursor()), real(*a))[1])

    view._tree.together_button.click()

    assert [cursor and cursor.shape() for cursor in while_drawing] == [Qt.CursorShape.WaitCursor], (
        "a redraw holds the window's thread, so without the cursor the window reads as dead for as "
        "long as it takes rather than as working")
    assert QApplication.overrideCursor() is None


def test_opening_one_kinds_latest_lists_it_without_building_the_list_again(qtbot, monkeypatch):
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
    db.add(_running_row("rr1", workflow="wan22_i2v"))
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

    db.add(_row("v1", "wan22_i2v", {"positive_prompt": "dance", "seed": 5},
                "wan22_i2v_00001_.mp4"))
    view._poll()
    assert set(_workflow_rows(view._tree)) == {"SDXL T2I", "WAN 2.2 I2V"}


def test_the_gallery_polls_on_a_timer_of_its_own(qtbot):
    db = FakeDB([_image("old", "a cat", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])

    assert view._poll_timer.isActive()
    assert view._poll_timer.interval() == 1500

    db.add(_image("new", "a dog", 50, 2))
    view._poll_timer.timeout.emit()

    assert view.listed_prompt_ids() == ["new", "old"]


def test_a_hidden_gallery_stops_polling_and_takes_it_up_again_when_shown(qtbot):
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
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_image_workflow(view._tree))

    assert view._gallery_pane._listed_folders
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

    _shape, *above, _here = view._tree_view.path_steps(here)

    assert list(_path_links(view)) == [step.name for step in above]


def test_a_collections_path_links_the_folders_above_it_and_wears_its_star(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_collection(view, FAVORITES_KEY))

    path = view._folder_path.findChild(shared_folder_path.FolderPath)
    assert list(_path_links(view)) == ["All"]
    assert icon_then_text("star", "Favorites", color=GREEN,
                          size=path.fontMetrics().height()) in path.text()
    assert view._folder_path.display_text() == f"{SHAPE_LABELS[LANDSCAPE]}  \u203a  All  \u203a  Favorites"


def test_enhanceds_path_wears_the_plus_where_favorites_wears_its_star(qtbot):
    view = GalleryView(FakeDB([_enhanced_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_collection(view, ENHANCED_KEY))

    path = view._folder_path.findChild(shared_folder_path.FolderPath)
    assert icon_then_text("plus", "Enhanced", color=YELLOW,
                          size=path.fontMetrics().height()) in path.text()


def test_trashs_path_wears_its_red_can_as_the_toc_does(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_collection(view, TRASH_KEY))

    path = view._folder_path.findChild(shared_folder_path.FolderPath)
    assert icon_then_text("trash", "Trash", color=RED,
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
    for tab in view._generate_pane.generate_tabs():
        tab._viewport.show_media = MagicMock()
    _select_first_leaf(view)

    view._on_thumbnail_clicked("g2")

    name = f"{gallery.folder_id(gallery.settings_folder_key(newer))} 001"
    assert view._gallery_pane._thumb_widgets["g2"]._text_label.text() == name
    assert view._generate_pane.tabText(view._generate_pane.currentIndex()) == name


def test_a_tab_put_back_before_the_gallery_first_loads_takes_its_items_name_then(qtbot):
    row = _image("g1", "a cat", 50, 1)
    view = GalleryView(FakeDB([row]), client=ComfyUIClient(folders=SUITE_FOLDERS))
    qtbot.addWidget(view)
    for tab in view._generate_pane.generate_tabs():
        tab._viewport.show_media = MagicMock()
    view._generate_pane.load_selection(row, [row])

    view.refresh()

    name = f"{gallery.folder_id(gallery.settings_folder_key(row))} 000"
    assert view._generate_pane.tabText(view._generate_pane.currentIndex()) == name


def test_going_to_an_item_draws_its_folder_even_when_that_row_is_already_current(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), client=ComfyUIClient(folders=SUITE_FOLDERS))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert "i1" in view.listed_prompt_ids()
    view._gallery_pane.show_empty()
    assert "i1" not in view.listed_prompt_ids()

    view._go_to_generation("i1")

    assert "i1" in view.listed_prompt_ids()
    assert view._selected["prompt_id"] == "i1"


def test_going_to_a_failed_generation_opens_the_folder_its_settings_name(qtbot):
    done = _image("i1", "a cat", 50, 1)
    failed = dict(done, prompt_id="x1", status="error", output_files="[]",
                  thumbnail_path=None)
    view = GalleryView(FakeDB([done, failed]), client=ComfyUIClient(folders=SUITE_FOLDERS))
    qtbot.addWidget(view)
    view.refresh()
    assert "x1" not in view._leaf_by_id

    view._go_to_generation("x1")

    assert "i1" in view.listed_prompt_ids()
    assert view._selected["prompt_id"] == "x1"


def test_following_a_link_lands_in_one_tab(qtbot):
    image = _image("img1", "a cat", 50, 1)
    video = _row("vid1", "wan22_i2v",
                 {"positive_prompt": "dance", "seed": 5,
                  "input_image": "sdxl_t2i_img1.png"},
                 "wan22_i2v_00001_.mp4")
    view = GalleryView(FakeDB([video, image]), client=ComfyUIClient(folders=SUITE_FOLDERS))
    qtbot.addWidget(view)
    view.refresh()
    for tab in view._generate_pane.generate_tabs():
        tab._viewport.show_media = MagicMock()
    view._tree.setCurrentItem(view._leaf_by_id["vid1"])
    _click_tile(view, "vid1")
    tabs = view._generate_pane.count()

    view.follow_link("img1")

    assert view._generate_pane.count() == tabs
    assert view._generate_pane.current_generate_tab().displayed_row()["prompt_id"] == "img1"


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
    _click_tile(view, "vid1")
    view.follow_link("img1")

    assert view._selected["prompt_id"] == "img1"
    view._navigation.go_back()
    assert view._selected["prompt_id"] == "vid1"


def test_nav_buttons_enable_only_when_there_is_somewhere_to_go(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]))
    qtbot.addWidget(view)
    view.refresh()
    assert not view._buttons.back.isEnabled()
    assert not view._buttons.forward.isEnabled()

    _select_first_leaf(view)
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
    for pid, prompt, steps in (("a", "alpha", 10), ("b", "beta", 20)):
        db.insert_generation(NewGeneration(prompt_id=pid, workflow_name="sdxl_t2i", workflow_version="v002",
                             positive_prompt=prompt, seed=1,
                             params_json=json.dumps({"positive_prompt": prompt, "seed": 1, "steps": steps}),
                             workflow_json="{}"))
        db.update_generation(pid, status="completed",
                             output_files=json.dumps([{"filename": f"{pid}.png", "subfolder": ""}]))
    actions = GalleryEdits(db, OutputPlaces.in_one_folder(tmp_path / "out"), Trash(tmp_path / "trash"))
    view = GalleryView(db, actions=actions)
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._leaf_by_id["a"])
    _click_tile(view, "a")
    assert view._selected["prompt_id"] == "a"
    view._confirm = lambda text: True
    view._delete_folders(view._current_deletable_folders())
    assert db.get_generation("a") is None
    assert view._selected is None

    view._undo()
    assert db.get_generation("a") is not None
    assert view._selected["prompt_id"] == "a"


def test_back_after_following_a_link_returns_to_the_viewed_generation(qtbot):
    image = _image("img1", "a cat", 50, 1)
    video = _row("vid1", "wan22_i2v",
                 {"positive_prompt": "dance", "seed": 5,
                  "input_image": "sdxl_t2i_img1.png"},
                 "wan22_i2v_00001_.mp4")
    view = GalleryView(FakeDB([video, image]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["vid1"])
    _click_tile(view, "vid1")
    assert view._selected["prompt_id"] == "vid1"

    view.follow_link("img1")
    assert view._selected["prompt_id"] == "img1"
    view._navigation.go_back()
    assert view._selected["prompt_id"] == "vid1"


def _linked_view(qtbot, source="i7", count=12):
    images = [_image(f"i{n}", "a cat", 50, n) for n in range(1, count + 1)]
    video = _row("vid1", "wan22_i2v",
                 {"positive_prompt": "dance", "seed": 5,
                  "input_image": f"sdxl_t2i_{source}.png"},
                 "wan22_i2v_00001_.mp4")
    view = GalleryView(FakeDB([video, *images]))
    _on_screen(qtbot, view, 1100, 1200)
    view._tree.setCurrentItem(view._leaf_by_id["vid1"])
    _click_tile(view, "vid1")
    return view


def test_following_a_source_link_lands_on_the_image_itself(qtbot):
    view = _linked_view(qtbot)

    view.follow_link("i7")

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
    view = _linked_view(qtbot)

    view.follow_link("i7")

    assert _in_view(view, "i7")


def test_moving_on_after_a_followed_link_leaves_the_folder_chosen_instead(qtbot):
    view = _linked_view(qtbot)

    view.follow_link("i7")
    view._tree.setCurrentItem(view._leaf_by_id["vid1"])
    qtbot.wait(1)

    assert view.listed_prompt_ids() == ["vid1"]
    assert _scroll_bar(view).value() == 0


def test_history_spans_folder_navigation(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2),
            _i2v_video("v1", "styleA")]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["v1"])
    view._tree.setCurrentItem(view._leaf_by_id["i1"])
    _click_tile(view, "i2")
    assert view._selected["prompt_id"] == "i2"

    view._navigation.go_back()
    assert view._tree.currentItem() is view._leaf_by_id["i1"]
    assert view._selected["prompt_id"] == "i1"

    view._navigation.go_back()
    assert view._tree.currentItem() is view._leaf_by_id["v1"]
    assert view._selected["prompt_id"] == "v1"


def test_back_returns_to_the_latest_collection_then_forward_reopens_the_folder(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    view._gallery_pane._thumb_widgets["i2"].double_clicked.emit("i2")
    assert view._gallery_pane.showing_latest() is False
    assert view._buttons.back.isEnabled()

    view._navigation.go_back()
    assert view._gallery_pane.showing_latest()

    view._navigation.go_forward()
    assert view._gallery_pane.showing_latest() is False
    assert view.selected_generation() == "i2"


def test_back_returns_to_a_collection_left_by_opening_a_folder(qtbot):
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
    view._gallery_pane._drill_into(view._gallery_pane._listed_folders[0])
    _click_tile(view, "i3")
    assert view._tree.currentItem() is not _collection(view, FAVORITES_KEY)

    view._navigation.go_back()
    view._navigation.go_back()
    assert view._tree.currentItem() is _collection(view, FAVORITES_KEY)


def test_back_to_latest_restores_the_item_selected_on_the_collection(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    _click_tile(view, "i2")
    view._gallery_pane._thumb_widgets["i2"].double_clicked.emit("i2")
    assert view._gallery_pane.showing_latest() is False

    view._navigation.go_back()
    assert view._gallery_pane.showing_latest()
    assert view.selected_generation() == "i2"
    assert view._gallery_pane._thumb_widgets["i2"]._selected


def test_previewing_on_the_collection_is_its_own_history_step(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1),
            _image("i3", "a bird", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    for pid in ("i1", "i2", "i3"):
        _click_tile(view, pid)

    view._navigation.go_back()
    assert view._gallery_pane.showing_latest()
    assert view.selected_generation() == "i2"

    view._navigation.go_back()
    assert view.selected_generation() == "i1"

    view._navigation.go_forward()
    assert view.selected_generation() == "i2"


def test_back_to_a_collection_item_re_highlights_its_tile(qtbot):
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
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    _search_for(view, "cat")
    _click_tile(view, "i1")
    depth = len(view._navigation._history._stack)

    view.refresh()
    view._poll()
    view._search._on_sort_changed()

    assert len(view._navigation._history._stack) == depth


def test_back_onto_a_folder_of_sub_folders_drops_the_pick(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    lora = _at(_image_workflow(view._tree), 0, 0)
    view._tree.setCurrentItem(lora)
    view._tree.setCurrentItem(view._leaf_by_id["i1"])

    view._navigation.go_back()

    assert view._tree.currentItem() is lora
    assert view._selected is None


def test_an_item_looked_at_on_a_collection_goes_back_to_that_collection(qtbot):
    rows = [_image("i1", "a cat", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    _click_tile(view, "i1")
    view._tree.setCurrentItem(view._leaf_by_id["i1"])

    view._navigation.go_back()

    assert view._gallery_pane.showing_latest()
    assert view.selected_generation() == "i1"


def test_back_returns_to_the_search_results_a_hit_was_opened_from(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    _search_for(view, "cat")
    assert view.listed_prompt_ids() == ["i1"]
    view._gallery_pane._thumb_widgets["i1"].double_clicked.emit("i1")
    assert view._gallery_pane.showing_search() is False

    view._navigation.go_back()

    assert view._gallery_pane.showing_search()
    assert view._search.field.text() == "cat"
    assert view.listed_prompt_ids() == ["i1"]


def test_a_hit_previewed_in_the_results_is_a_stop_in_them(qtbot):
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
    assert view.selected_folder() == shaped_key(_key(workflow), LANDSCAPE)


def test_naming_a_workflow_version_is_what_puts_it_in_the_folder_key(qtbot):
    row = _image("i1", "a cat", 50, 1)
    view = GalleryView(FakeDB([row]))
    qtbot.addWidget(view)
    view.refresh()
    params = json.loads(row["params_json"])
    version = row["workflow_version"]

    assert view.folder_key_for(row["workflow_name"], params, version)         == view.folder_key_of(row)
    assert view.folder_key_for(row["workflow_name"], params)         != view.folder_key_of(row)


def test_the_folder_key_index_is_rebuilt_when_the_image_rows_are(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    first = view.image_config_index()
    assert view.image_config_index() is first

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
    dog_leaf = _at(_image_workflow(saved._tree), 0, 0, 1)
    saved._tree.setCurrentItem(dog_leaf)
    saved_key = saved.selected_folder()
    chosen = set(saved.listed_prompt_ids())

    restored = GalleryView(db)
    qtbot.addWidget(restored)
    restored.select_folder(saved_key)
    restored.refresh()
    assert restored.selected_folder() == saved_key
    assert set(restored.listed_prompt_ids()) == chosen


def test_select_folder_falls_back_to_default_when_key_gone(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.select_folder("video/ghost")
    view.refresh()
    assert view.selected_folder() is not None


def test_selected_folder_reports_pending_target_before_first_show(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.select_folder("image/sdxl_t2i")
    assert view.selected_folder() == "image/sdxl_t2i"


def test_selected_generation_tracks_thumbnail_click(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["i1"])
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

    db.add(_image("i3", "a dog", 50, 9))
    view._poll()

    assert view.selected_generation() == "i2"
    assert view._selected["prompt_id"] == "i2"


def test_selected_generation_reports_pending_before_show(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.select_generation("i1")
    assert view.selected_generation() == "i1"


def test_select_generation_missing_id_is_dropped(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.select_generation("ghost")
    view.refresh()
    assert view.selected_generation() != "ghost"



def test_the_panes_keep_their_contents_the_standard_margin_off_their_edges(qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.resize(1500, 900)
    view.show()
    for _ in range(4):
        QApplication.processEvents()

    for inside in (view._tree, view._scroll, view._osr2_controls, view._enhance.pane):
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
    assert divider.widget(1).isAncestorOf(view._enhance.pane)
    assert divider.handleWidth() == view._arrangement.panes.handleWidth()


def test_with_room_to_spare_the_enhance_settings_under_the_thumbnails_open_whole(qtbot,
                                                                               tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.resize(1500, 1100)
    view.show()
    for _ in range(4):
        QApplication.processEvents()
    (settings,) = view._enhance.pane.findChildren(QScrollArea)

    assert settings.verticalScrollBar().maximum() == 0


def test_with_room_to_spare_the_hud_opens_whole_at_the_top_left_even_at_its_widest(
        qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path), client=_reroll_client(), shared=Shared(osr2_motion=_SignalMotion()))
    qtbot.addWidget(view)
    view.resize(1500, 1100)
    view.show()
    view.osr2_control.setChecked(True)
    for _ in range(4):
        QApplication.processEvents()
    (hud,) = _pane_holding(view._osr2_controls).findChildren(QScrollArea)

    assert hud.horizontalScrollBar().maximum() == 0
    assert hud.verticalScrollBar().maximum() == 0


def test_the_enhance_settings_take_the_whole_foot_under_the_thumbnails(qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    divider = _pane_holding(view._scroll).parentWidget()

    assert divider.widget(1) is _pane_holding(view._enhance.pane)


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
    view._tree.setCurrentItem(_image_workflow(view._tree))
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

    assert facts.histories == {}
    assert facts.backlogs == {"q1": None}
    assert facts.foreign.total == 0
    assert facts.executing == frozenset()


def test_the_poll_fetch_reads_nothing_with_no_client():
    facts = gallery_view_module._fetch_poll_facts(None, [("q1", "queued")])

    assert facts == gallery_view_module._PollFacts({}, {}, None)


def test_an_event_about_an_object_already_gone_does_not_take_the_app_down(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    doomed = QTimer()
    sip.delete(doomed)

    assert view.eventFilter(doomed, QEvent(QEvent.Type.Timer)) is False


def test_the_view_looks_for_a_preview_where_its_actions_were_pointed(qtbot, tmp_path,
                                                                     monkeypatch):
    asked = []
    monkeypatch.setattr(
        gallery, "animated_preview_if_made",
        lambda row, places, thumb_dir: asked.append((places, thumb_dir)))
    view = GalleryView(_trash_db(), actions=FakeActions(places=OutputPlaces.in_one_folder(tmp_path / "output"),
                                                 thumb_dir=tmp_path / "thumbs"))
    qtbot.addWidget(view)

    view.animated_preview({"prompt_id": "p1"})

    assert asked == [(OutputPlaces.in_one_folder(tmp_path / "output"), tmp_path / "thumbs")]


def test_a_gallery_given_no_thumbnails_folder_shows_stills(qtbot, tmp_path):
    view = GalleryView(_trash_db(), actions=FakeActions(places=OutputPlaces.in_one_folder(tmp_path),
                                                 thumb_dir=None))
    qtbot.addWidget(view)

    assert view.animated_preview({"prompt_id": "p1"}) is None


def test_a_folders_hover_says_its_name_and_nothing_else(qtbot):
    rows = [_image("i1", "a cat asleep on a windowsill in the late sun", 50, 1)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    (leaf,) = _subs(_at(_image_workflow(view._tree), 0, 0))

    assert leaf.toolTip(0).startswith(leaf.text(0))
    assert "a cat" not in leaf.toolTip(0)


def test_the_experiments_switch_is_up_only_in_the_experiments_collection(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_collection(view, EXPERIMENTS_KEY))
    assert not view._experiments_bar.isHidden()

    view._tree.setCurrentItem(view._leaf_by_id["i1"])
    assert view._experiments_bar.isHidden()


def test_back_returns_to_where_the_gallery_first_landed(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    landed = view._tree.currentItem()

    view._tree.setCurrentItem(view._leaf_by_id["i1"])
    view._navigation.go_back()

    assert view._tree.currentItem() is landed


def test_the_shapes_chosen_before_the_first_draw_read_nothing(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    read = []
    db.list_generations = lambda: read.append("read") or []

    view.set_toc_sides(list(TOGETHER))

    assert read == []


def test_a_folder_drawn_again_where_it_stands_is_one_visit(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["i1"])
    visits = list(view._folder_history)

    view.hand_pane_back()

    assert view._folder_history == visits


def test_with_nothing_selected_the_shape_in_view_is_the_one_holding_landscape(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)

    assert view.shape_in_view() == LANDSCAPE


def test_a_key_naming_a_drawn_shape_is_answered_by_that_shape_alone(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    key = _key(view._leaf_by_id["i1"])

    assert view._tree_item_for(shaped_key(key, LANDSCAPE)) is view._leaf_by_id["i1"]
    assert view._tree_item_for(shaped_key(key, PORTRAIT)) is None


def _a_folder_on_both_sides(qtbot):
    shapes = {"i1": (1280, 720), "i2": (720, 1280)}
    view = GalleryView(FakeDB([
        _row(pid, "sdxl_t2i", {"positive_prompt": f"prompt {pid}", "steps": 50,
                               "width": width, "height": height}, f"sdxl_t2i_{pid}.png")
        for pid, (width, height) in shapes.items()]))
    qtbot.addWidget(view)
    view.refresh()
    return view, _key(_image_workflow(view._tree))


def test_a_folders_own_key_stays_on_the_shape_being_browsed(qtbot):
    view, key = _a_folder_on_both_sides(qtbot)

    for shape in (LANDSCAPE, PORTRAIT):
        row = view._tree_item_for(shaped_key(key, shape))
        view._tree.setCurrentItem(row)
        assert view._tree_item_for(key) is row


def test_what_a_delete_takes_off_the_tree_is_a_folders_row_on_each_side_and_under_it(qtbot):
    view, key = _a_folder_on_both_sides(qtbot)
    group = view.group_for_key(key)

    keys = view._keys_under(group)

    assert {shaped_key(key, LANDSCAPE), shaped_key(key, PORTRAIT)} <= keys
    assert len(keys) > 2


def test_a_folder_at_the_top_of_the_list_and_one_it_has_not_got_have_no_place_to_name(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    assert view._folder_context(view.selected_folder_key()) == ""
    assert view._folder_context("image/no-such-folder") == ""


def test_following_a_link_stops_nowhere_on_its_way_through_a_folder(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("d1", "a dog", 50, 1), _image("d2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["i1"])
    (first, other) = [view.row_for(pid)["prompt_id"] for pid in ("d1", "d2")]

    view.follow_link(other)
    view._navigation.go_back()

    assert first != other
    assert view.selected_generation() == "i1"


def test_an_item_the_tree_has_nowhere_to_put_has_no_folder_row(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    assert view._folder_row_for("no-such-item") is None
