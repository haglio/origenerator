from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import (
    QEvent,
    QPoint,
    QSize,
    Qt,
)
from PyQt6.QtGui import (
    QDrag,
    QKeyEvent,
    QMovie,
)
from PyQt6.QtWidgets import (
    QApplication,
    QLineEdit,
    QPushButton,
    QToolButton,
)
from shared_ui.spacing import BUTTON_SIZE_HUD

from origenerator import (
    gallery,
)
from origenerator.comfyui_client import ComfyUIClient
from origenerator.config import (
    OUTPUT_PLACES,
    THUMB_DIR,
)
from origenerator.gallery.collection import (
    LATEST_KEY,
)
from origenerator.gui import (
    corner_buttons,
    icons,
)
from origenerator.gui.drag_thumbnail import DragOut
from origenerator.gui.drop_style import LIT
from origenerator.gui.enhance_controller import ALREADY_AT_THESE_SETTINGS
from origenerator.gui.enhance_versions import _AddRow, _VersionRow, enhance_version_mime
from origenerator.gui.gallery_view import GalleryView
from origenerator.gui.item_type_icon import ItemTypeIcon
from origenerator.workflows import detail_parts
from tests import gestures
from tests.comfyui_folders import SUITE_FOLDERS
from tests.gallery_view_support import (
    _CTRL,
    _ENHANCE_HISTORY,
    _NO_MOD,
    FakeActions,
    FakeDB,
    _alls,
    _answer_menu,
    _at,
    _click_off,
    _click_tile,
    _collection,
    _collection_row,
    _enhanceable_db,
    _enhanced_in_place,
    _i2v_video,
    _image,
    _image_workflow,
    _menu_labels,
    _name_of,
    _on_screen,
    _open_leaf,
    _pick,
    _reroll_client,
    _right_click,
    _row,
    _running_row,
    _select_first_leaf,
    _selected_folder,
    _shown_view_with_one_image,
    _trash_collection_view,
    _two_leaf_view,
    _video_workflow,
    _write_looping_webp,
)
from tests.related_links import source_tile
from tests.test_enhance_pane import _dropped_on
from tests.test_folder_tree import _shown

pytestmark = pytest.mark.usefixtures("_stub_preview_resolution")


def _two_images_on_screen(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]))
    _on_screen(qtbot, view, 1400, 900)
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    return view, view._gallery_pane._thumb_widgets["i2"]


def test_dragging_an_image_lights_the_tabs_start_image_until_it_is_let_go(qtbot, monkeypatch):
    view, tile = _two_images_on_screen(qtbot)
    tab = view._generate_pane.current_generate_tab()
    tab._workflow_dropdown.setCurrentIndex(tab._workflow_dropdown.findData("wan22_i2v"))
    well = tab._param_form._widgets["input_image"]._label
    lit_while_dragged = []
    monkeypatch.setattr(QDrag, "exec", lambda drag, *args: lit_while_dragged.append(
        well.property(LIT)) or Qt.DropAction.IgnoreAction)
    at = tile.rect().center()

    gestures.press(tile, at)
    gestures.move(tile, at + QPoint(40, 0))

    assert lit_while_dragged == [True]
    assert well.property(LIT) is False


def test_pressing_an_image_lights_it_up_and_leaves_the_tab_as_it_was(qtbot):
    view, tile = _two_images_on_screen(qtbot)

    gestures.press(tile, tile.rect().center())

    assert view.selected_prompt_ids() == ["i2"]
    assert view.selected_generation() is None


def test_dragging_an_image_out_leaves_the_tab_as_it_was(qtbot, monkeypatch):
    monkeypatch.setattr(DragOut, "start", lambda self, *args, **kwargs: None)
    view, tile = _two_images_on_screen(qtbot)
    at = tile.rect().center()
    away = at + QPoint(40, 0)

    gestures.press(tile, at)
    gestures.move(tile, away)
    gestures.release(tile, away)

    assert view.selected_generation() is None


def test_right_clicking_a_recent_item_offers_its_folder_its_name_favorite_enhance_and_delete(
        qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    labels = []
    _menu_labels(monkeypatch, labels)

    _right_click(view, "i2")

    assert labels == ["Go to folder", "Copy name", "", "Favorite 1 item", "Enhance 1 image",
                      "Delete 1 item"], (
        "a collection gathers items from all over, so where this one lives is the question its "
        "menu is most often asked: it leads, above a separator")
    assert view.selected_prompt_ids() == ["i2"]


def test_go_to_folder_is_left_off_inside_the_items_own_folder(qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["i1"])
    labels = []
    _menu_labels(monkeypatch, labels)

    _right_click(view, "i1")

    assert labels == ["Copy name", "", "Favorite 1 item", "Enhance 1 image", "Delete 1 item"]


def test_enhance_is_grayed_for_an_image_that_already_has_that_enhancement(qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["i1"])
    monkeypatch.setattr("origenerator.gui.enhance_controller.gallery.version_matching_settings",
                        lambda row, settings: 0)
    offered = {}
    monkeypatch.setattr(
        "origenerator.gui.gallery_view.QMenu.exec",
        lambda menu, *a: offered.update(
            {act.text(): (act.isEnabled(), act.toolTip(), menu.toolTipsVisible())
             for act in menu.actions()}),
    )

    _right_click(view, "i1")

    assert offered["Enhance 1 image"] == (False, ALREADY_AT_THESE_SETTINGS, True)


def test_go_to_folder_from_a_collection_opens_the_folder_and_lands_on_the_item(
        qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    _answer_menu(monkeypatch, "Go to folder")

    _right_click(view, "i2")

    assert view._tree.currentItem() is view._leaf_by_id["i2"]
    assert view.selected_prompt_ids() == ["i2"]


def test_copy_name_puts_the_items_name_on_the_clipboard(qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["i1"])
    QApplication.clipboard().clear()
    _answer_menu(monkeypatch, "Copy name")

    _right_click(view, "i1")

    assert QApplication.clipboard().text() == _name_of(rows[0], 1)


def test_copying_the_names_of_picked_items_puts_them_one_to_a_line(qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2),
            _image("i3", "a cat", 50, 3)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view._gallery_pane.apply_selection("i1", _NO_MOD)
    view._gallery_pane.apply_selection("i3", _CTRL)
    QApplication.clipboard().clear()
    _answer_menu(monkeypatch, "Copy 2 names")

    _right_click(view, "i3")

    assert QApplication.clipboard().text() == "\n".join(
        [_name_of(rows[0], 2), _name_of(rows[2], 0)])


def test_an_item_the_gallery_has_not_named_yet_offers_no_name_to_copy(qtbot, monkeypatch):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    db.add(_image("i2", "a cat", 50, 2))
    labels = []
    _menu_labels(monkeypatch, labels)

    view.generation_menu(["i2"], QPoint(0, 0))

    assert labels == ["Favorite 1 item", "Enhance 1 image", "Delete 1 item"]


def _press_ctrl_c(view, monkeypatch):
    monkeypatch.setattr(view, "_gallery_owns_keys", lambda **_kw: True)
    return view.eventFilter(view, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_C, _CTRL))


def test_ctrl_c_copies_the_names_of_the_picked_items_one_to_a_line(qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2),
            _image("i3", "a cat", 50, 3)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view._gallery_pane.apply_selection("i1", _NO_MOD)
    view._gallery_pane.apply_selection("i3", _CTRL)
    QApplication.clipboard().clear()

    _press_ctrl_c(view, monkeypatch)

    assert QApplication.clipboard().text() == "\n".join(
        [_name_of(rows[0], 2), _name_of(rows[2], 0)])


def test_ctrl_c_with_no_item_picked_copies_the_folders_name(qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view._gallery_pane.clear_selection()
    QApplication.clipboard().clear()

    _press_ctrl_c(view, monkeypatch)

    assert QApplication.clipboard().text() == gallery.folder_id(
        gallery.settings_folder_key(rows[0]))


def test_ctrl_c_over_picked_folders_copies_each_folders_name(qtbot, monkeypatch):
    view, cat, dog = _two_leaf_view(qtbot)
    _pick(view, cat, dog)
    view._gallery_pane.clear_selection()
    QApplication.clipboard().clear()

    _press_ctrl_c(view, monkeypatch)

    assert QApplication.clipboard().text() == "\n".join(
        gallery.folder_id(gallery.settings_folder_key(_image(pid, prompt, 50, 1)))
        for pid, prompt in (("i1", "a cat"), ("i2", "a dog")))


def test_ctrl_c_in_a_focused_text_field_is_left_to_the_field(qtbot, tmp_path, monkeypatch):
    view, _db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    _open_leaf(view)
    view._gallery_pane.apply_selection("i1", _NO_MOD)
    monkeypatch.setattr(view, "_other_window_owns_keys", lambda: False)
    editor = QLineEdit()
    monkeypatch.setattr(
        "origenerator.gui.gallery_view.QApplication.focusWidget", lambda: editor
    )
    QApplication.clipboard().setText("words copied from the field")

    taken = view.eventFilter(view, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_C, _CTRL))

    assert (taken, QApplication.clipboard().text()) == (False, "words copied from the field")


def _folder_buttons(view):
    tab = view._generate_pane.current_generate_tab()
    return [button for button in tab.findChildren(QPushButton, "goToFolderButton")
            if button.isVisibleTo(tab)]


def test_the_go_to_folder_button_takes_a_collection_item_home_without_a_right_click(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    _click_tile(view, "i2")
    (button,) = _folder_buttons(view)
    # Qt gives an unshown button no rect for a press to land in.
    button.show()

    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)

    assert view._tree.currentItem() is view._leaf_by_id["i2"]
    assert view.selected_prompt_ids() == ["i2"]


def test_no_go_to_folder_button_inside_the_items_own_folder(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._leaf_by_id["i1"])

    assert _folder_buttons(view) == []


def test_a_deleted_item_offers_no_way_to_a_folder(qtbot):
    view = _trash_collection_view(qtbot, FakeActions())

    _click_tile(view, "d1")

    assert _folder_buttons(view) == []


def test_a_video_goes_to_its_folder_from_the_same_button(qtbot):
    view = GalleryView(FakeDB([_i2v_video("v1", "smooth")]), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    _click_tile(view, "v1")

    (button,) = _folder_buttons(view)
    button.click()

    assert view._tree.currentItem() is view._leaf_by_id["v1"]


def test_a_kind_left_off_a_collection_still_has_its_folder_to_go_to(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    _click_tile(view, "i1")
    assert _folder_buttons(view)

    view._tree.setCurrentItem(_collection_row(_alls(view._tree)["Videos"], "Latest"))

    (button,) = _folder_buttons(view)
    button.click()
    assert view._tree.currentItem() is view._leaf_by_id["i1"]


def test_leaving_the_items_folder_puts_the_go_to_folder_back_on_what_it_shows(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["i1"])
    assert _folder_buttons(view) == []

    view._tree.setCurrentItem(_alls(view._tree)["Latest"])

    (button,) = _folder_buttons(view)
    assert button.toolTip() == "Go to the folder this item is in"


def test_right_click_delete_on_the_latest_collection_removes_the_item(qtbot, monkeypatch):
    actions = FakeActions()
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows), actions=actions)
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    monkeypatch.setattr(
        "origenerator.gui.gallery_view.QMenu.exec", lambda menu, *a: menu.actions()[-1]
    )

    _right_click(view, "i1")

    assert {r["prompt_id"] for r in actions.deleted[0]} == {"i1"}


def test_right_click_favorite_on_the_latest_collection_favorites_the_item(qtbot, monkeypatch):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    _answer_menu(monkeypatch, "Favorite 1 item")

    _right_click(view, "i1")

    assert db.get_generation("i1")["starred"]
    assert view._gallery_pane.showing_latest()
    assert view._gallery_pane._thumb_widgets["i1"]._favorite is True


def test_right_click_enhance_on_the_latest_collection_queues_the_image(qtbot, tmp_path, monkeypatch):
    view = GalleryView(_enhanceable_db(tmp_path, count=1), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    _answer_menu(monkeypatch, "Enhance 1 image")

    _right_click(view, "g0")

    (job,) = view._live_jobs.values()
    assert job.workflow.name == "image_enhance"


def test_latest_video_tiles_animate_while_images_stay_still(qtbot, tmp_path, monkeypatch):
    webp = _write_looping_webp(tmp_path / "v1_anim.webp")
    rows = [
        _image("i1", "a cat", 50, 1),
        _row("v1", "wan22_i2v", {"positive_prompt": "dance", "seed": 5}, "wan22_i2v_v1.mp4"),
    ]
    calls = []

    def fake_anim(row, places, thumb_dir):
        calls.append((row["prompt_id"], places, thumb_dir))
        return str(webp) if gallery.media_type_of_row(row) == "video" else None

    monkeypatch.setattr(gallery, "animated_preview_if_made", fake_anim)
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])

    assert view._gallery_pane._thumb_widgets["v1"].findChildren(QMovie)
    assert view._gallery_pane._thumb_widgets["i1"].findChildren(QMovie) == []
    assert ("v1", OUTPUT_PLACES, THUMB_DIR) in calls


def test_settings_folder_video_tiles_animate(qtbot, tmp_path, monkeypatch):
    webp = _write_looping_webp(tmp_path / "v1_anim.webp")
    rows = [_row("v1", "wan22_i2v",
                 {"positive_prompt": "dance", "seed": 5}, "wan22_i2v_v1.mp4")]
    monkeypatch.setattr(
        gallery, "animated_preview_if_made",
        lambda row, o, t: str(webp) if gallery.media_type_of_row(row) == "video" else None,
    )
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._leaf_by_id["v1"])
    assert view._gallery_pane._thumb_widgets["v1"].findChildren(QMovie)


def test_latest_tiles_wear_an_image_or_video_item_type_icon(qtbot):
    rows = [
        _image("i1", "a cat", 50, 1),
        _row("v1", "wan22_i2v", {"positive_prompt": "dance", "seed": 5}, "wan22_i2v_v1.mp4"),
    ]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])

    def icon_type(pid):
        icons_found = view._gallery_pane._thumb_widgets[pid].findChildren(ItemTypeIcon)
        return icons_found[0].media_type if icons_found else None

    assert icon_type("i1") == "image", (
        "the collection mixes kinds, so each tile says its own at a glance")
    assert icon_type("v1") == "video"


def test_a_folder_of_one_kind_leaves_the_item_type_icon_off_its_tiles(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    _select_first_leaf(view)

    assert view._gallery_pane._thumb_widgets["i1"].findChildren(ItemTypeIcon) == [], (
        "inside a folder of one kind the icon would only repeat what the folder already says")


def test_an_inflight_tile_wears_the_item_type_icon_of_its_media_type(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.add(_running_row("rr1", workflow="wan22_i2v"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    items = {it.key: it for it in view._inflight_items()}
    assert items["rr1"].media_type == "video"


def _source_tile(view):
    return source_tile(view._generate_pane.current_generate_tab()._related)


def test_video_source_tile_points_to_its_image_and_navigates(qtbot):
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

    view._on_thumbnail_clicked("vid1")
    assert not _source_tile(view).isHidden()
    assert _source_tile(view)._prompt_id == "img1"

    _source_tile(view).activated.emit("img1")
    assert "img1" in view.listed_prompt_ids()
    assert view._selected["prompt_id"] == "img1"
    view._on_thumbnail_clicked("img1")
    assert _source_tile(view).isHidden()


def test_the_gallery_pane_buttons_are_a_group_of_compact_icon_buttons(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    for btn in (view._buttons.back, view._buttons.forward, view._buttons.undo, view._buttons.delete):
        assert isinstance(btn, QToolButton)
        assert not btn.icon().isNull()
        assert btn.text() == ""


def test_delete_button_enables_for_a_selection_or_a_deletable_folder(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    workflow = _image_workflow(view._tree)
    view._tree.setCurrentItem(workflow)
    assert not view._buttons.delete.isEnabled()

    _select_first_leaf(view)
    assert view._buttons.delete.isEnabled()

    _click_tile(view, "i1")
    assert view._buttons.delete.isEnabled()


def test_delete_button_deletes_the_picked_thumbnails(qtbot):
    actions = FakeActions()
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]),
                       actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    _click_tile(view, "i1")

    view._buttons.delete.click()

    assert actions.deleted
    assert {r["prompt_id"] for r in actions.deleted[0]} == {"i1"}



def test_favorite_button_aims_at_the_picked_thumbnails_and_toggles(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    _click_tile(view, "i1")

    assert view._buttons.favorite.isEnabled()
    assert view._buttons.favorite.toolTip() == "Favorite 1 item"
    view._buttons.favorite.click()
    assert db.get_generation("i1")["starred"]

    _click_tile(view, "i1")
    assert view._buttons.favorite.toolTip() == "Unfavorite 1 item"
    view._buttons.favorite.click()
    assert not db.get_generation("i1")["starred"]


def test_favorite_button_falls_back_to_the_folder_on_screen(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    _click_off(view)
    assert view._buttons.favorite.isEnabled()
    assert "folder" in view._buttons.favorite.toolTip()

    view._buttons.favorite.click()

    key = _selected_folder(view)
    assert view._db.folder_meta_map()[key]["starred"]


def test_favorite_button_is_dark_where_a_favorite_means_nothing(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, LATEST_KEY))
    assert not view._buttons.favorite.isEnabled()
    assert view._buttons.favorite.toolTip() == "Nothing here to favorite"


def test_enhance_button_takes_the_picked_thumbnails_over_the_folder(qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path, count=2), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    queued = []
    view._enhance.enhance_items = queued.append

    _click_tile(view, "g0")
    assert view._buttons.enhance.toolTip().startswith("Enhance 1 item")
    view._buttons.enhance.click()

    assert queued == [["g0"]]


def test_enhance_button_with_nothing_picked_enhances_the_folder_on_screen(qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path, count=2), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    _click_off(view)

    view._buttons.enhance.click()

    assert sorted(j.params["input_image"] for j in view._jobs.all_jobs) == [
        "image/sdxl_t2i_g0.png [output]", "image/sdxl_t2i_g1.png [output]"], (
        "with nothing picked, a press of Enhance acts on the folder on screen, as a press of "
        "Favorite or Delete does")


def _video_leaf(view):
    item = _video_workflow(view._tree)
    while item.childCount():
        item.setExpanded(True)
        item = _at(item, 0)
    view._tree.setCurrentItem(item)


def test_enhance_is_dark_on_a_video_and_says_why(qtbot):
    view = GalleryView(FakeDB([_i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()
    _video_leaf(view)
    assert not view._buttons.enhance.isEnabled()

    _click_tile(view, "v1")
    assert not view._buttons.enhance.isEnabled()
    assert "no video enhancer" in view._buttons.enhance.toolTip()


def test_the_enhance_pane_grays_out_on_a_video_too(qtbot):
    view = GalleryView(FakeDB([_i2v_video("v1", "styleA"), _image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    _video_leaf(view)
    assert not view._enhance.pane.isEnabled()
    assert "no video enhancer" in view._enhance.pane.toolTip()

    _select_first_leaf(view)
    assert view._enhance.pane.isEnabled()
    assert view._enhance.pane.toolTip() == ""


def test_enhance_goes_dark_on_an_image_already_made_at_these_settings(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    settings = gallery.EnhanceSettings(auto=False, params={"enhance_scale": 2.0})
    view.set_enhance_settings(settings.to_json())
    _enhanced_in_place(db)
    db.update_generation("g0", enhance_history=json.dumps([
        {"filename": "image_enhance_00001_.png",
         "params": gallery.enhance_params_for(db.get_generation("g0"), settings)},
    ]))
    view.refresh()
    _select_first_leaf(view)

    _click_tile(view, "g0")
    assert not view._buttons.enhance.isEnabled()
    assert "these settings" in view._buttons.enhance.toolTip()

    view._enhance._on_settings_changed(
        gallery.EnhanceSettings(auto=False, params={"enhance_scale": 3.0}))
    assert view._buttons.enhance.isEnabled()


def test_a_version_dragged_onto_the_enhance_pane_grays_the_enhance_that_would_repeat_it(
        qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(detail_parts, "list_detector_files", lambda: ["hand_finder.pt"])
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.set_enhance_settings(gallery.EnhanceSettings(auto=False, params={
        "enhance_scale": 3.0,
        "enhance_fix_prompts": {"hands": {"prompt": "open palms", "avoid": "fists"}}}).to_json())
    _enhanced_in_place(db)
    ran = gallery.enhance_params_for(db.get_generation("g0"), gallery.EnhanceSettings(
        params={"enhance_scale": 2.0, "enhance_detail_fixes": {"hands": 0.45}}))
    ran.pop("enhance_fix_prompts")
    db.update_generation("g0", enhance_history=json.dumps([
        {"filename": "image_enhance_00001_.png", "params": ran}]))
    view.refresh()
    _select_first_leaf(view)
    _click_tile(view, "g0")
    versions = view._generate_pane.current_generate_tab()._versions
    version = next(row for row in versions._host.findChildren(_VersionRow) if row._params)
    mime = enhance_version_mime(version._params)

    _dropped_on(view._enhance.pane, mime)

    assert not view._buttons.enhance.isEnabled()
    (tile,) = versions._host.findChildren(_AddRow)
    assert "already has a version" in tile.toolTip()



def test_a_star_pressed_on_one_tile_favorites_it_at_once_and_leaves_the_rest(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)])
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])

    view._gallery_pane._thumb_widgets["i2"]._controls.triggered.emit(corner_buttons.STAR)

    assert db.get_generation("i2")["starred"]
    assert view._gallery_pane._thumb_widgets["i2"]._favorite is True
    assert not db.get_generation("i1").get("starred")


def test_a_favorite_tiles_favorite_corner_takes_the_favorite_away(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.set_generation_favorite("i1", True)
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    view._gallery_pane._thumb_widgets["i1"]._controls.triggered.emit(corner_buttons.STAR)

    assert not db.get_generation("i1")["starred"]


def test_a_favorite_from_a_slideshow_marks_its_tile_without_rebuilding_the_gallery(qtbot, monkeypatch):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    rebuilds = []
    monkeypatch.setattr(view, "_rebuild", lambda rows, meta: rebuilds.append(rows))

    view.favorite_generation("i1")

    assert db.get_generation("i1")["starred"]
    assert view._gallery_pane._thumb_widgets["i1"]._favorite is True
    assert rebuilds == []


def test_the_favorites_count_follows_a_favorite_without_rebuilding_the_gallery(qtbot, monkeypatch):
    db = FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)])
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    rebuilds = []
    monkeypatch.setattr(view, "_rebuild", lambda rows, meta: rebuilds.append(rows))

    view.favorite_generation("i1")
    assert _shown(_alls(view._tree)["Favorites"]) == "(1) Favorites"

    view.set_items_favorite(["i1"], False)
    assert _shown(_alls(view._tree)["Favorites"]) == "Favorites"
    assert rebuilds == []


def test_unfavoriting_a_favorite_drops_it_from_the_collection_with_a_real_library(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=2)
    db.set_generation_favorite("g0", True)
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Favorites"])
    assert view.listed_prompt_ids() == ["g0"]

    view._gallery_pane._thumb_widgets["g0"]._controls.triggered.emit(corner_buttons.STAR)

    assert view.listed_prompt_ids() == []


def test_favoriting_the_picked_items_turns_the_favorite_button_to_unfavorite(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    _click_tile(view, "i1")
    assert view._buttons.favorite.toolTip() == "Favorite 1 item"

    view._buttons.favorite.click()

    assert view._buttons.favorite.toolTip() == "Unfavorite 1 item"


def test_a_tiles_trash_corner_deletes_that_tile(qtbot):
    actions = FakeActions()
    db = FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)])
    view = GalleryView(db, actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])

    view._gallery_pane._thumb_widgets["i2"]._controls.triggered.emit(corner_buttons.TRASH)

    assert [r["prompt_id"] for r in actions.deleted[0]] == ["i2"]


def test_a_corner_control_acts_on_its_own_tile_not_the_selection(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)])
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    _click_tile(view, "i1")
    view._gallery_pane.selected_ids.add("i2")

    view._gallery_pane._thumb_widgets["i1"]._controls.triggered.emit(corner_buttons.STAR)

    assert db.get_generation("i1")["starred"]
    assert not db.get_generation("i2").get("starred")


def test_a_tiles_plus_corner_queues_an_enhance_of_that_image(qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path, count=1), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    view._gallery_pane._thumb_widgets["g0"]._controls.triggered.emit(corner_buttons.ENHANCE)

    (job,) = view._live_jobs.values()
    assert job.workflow.name == "image_enhance"


def test_pressing_a_tabs_preview_star_turns_that_star_on(qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path, count=1))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    _click_tile(view, "g0")
    star = view._generate_pane.current_generate_tab()._viewport._controls.buttons()[0]

    star.click()

    assert star.toolTip() == "Unfavorite this item"


def test_a_tabs_preview_plus_stops_offering_once_its_enhancement_lands(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_enhanceable_db(tmp_path, count=1), client=client)
    qtbot.addWidget(view)
    view.refresh()
    view._on_thumbnail_clicked("g0")
    plus = view._generate_pane.current_generate_tab()._viewport._controls.buttons()[2]
    plus.click()
    (job,) = view._jobs.all_jobs

    client.job_completed.emit(job.prompt_id, _ENHANCE_HISTORY)

    assert not plus.isEnabled()


def test_an_unenhanced_image_offers_its_first_enhancement_in_the_corner(qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path, count=1), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    assert view._gallery_pane._thumb_widgets["g0"].enhance_state() == icons.ENHANCE_OPEN


def test_a_video_tile_has_no_enhance_corner_to_offer(qtbot):
    view = GalleryView(FakeDB([_i2v_video("v1", "styleA")]), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])

    assert view._gallery_pane._thumb_widgets["v1"].enhance_state() is None


def test_the_enhance_corner_offers_another_the_moment_a_setting_moves(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    settings = gallery.EnhanceSettings(auto=False, params={"enhance_scale": 2.0})
    view.set_enhance_settings(settings.to_json())
    _enhanced_in_place(db)
    db.update_generation("g0", enhance_history=json.dumps([
        {"filename": "image_enhance_00001_.png",
         "params": gallery.enhance_params_for(db.get_generation("g0"), settings)},
    ]))
    view.refresh()
    _select_first_leaf(view)
    assert view._gallery_pane._thumb_widgets["g0"].enhance_state() == icons.ENHANCE_HELD

    view._enhance._on_settings_changed(
        gallery.EnhanceSettings(auto=False, params={"enhance_scale": 3.0}))

    assert view._gallery_pane._thumb_widgets["g0"].enhance_state() == icons.ENHANCE_MORE


def test_a_mixed_pick_enhances_the_images_in_it(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    _click_tile(view, "i1")
    view._gallery_pane.selected_ids.add("v1")
    view._re_aim()
    queued = []
    view._enhance.enhance_items = queued.append

    assert view._buttons.enhance.isEnabled()
    assert view._enhance.pane.isEnabled()
    view._buttons.enhance.click()

    assert queued == [["i1"]]


def test_the_bank_groups_its_buttons_with_a_space_between(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    groups = [buttons for _gap, buttons in view._buttons._groups]
    assert groups[0] == (view._buttons.back, view._buttons.forward), (
        "icon-only buttons lean on their neighbors to be read, so they are laid out in groups "
        "with a space between")
    assert groups[1] == (view._buttons.undo, view._buttons.redo)
    assert groups[3] == (view._buttons.favorite, view._buttons.enhance, view._buttons.delete)
    assert view._buttons.populate in groups[4]
    assert view._buttons.radio in groups[4]
    assert groups[5] == (view._buttons.power, view._buttons.play_pause, view._buttons.reference,
                         view._buttons.mic)


def test_a_group_with_nothing_showing_takes_no_space(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    view.show()
    _select_first_leaf(view)

    gaps = {id(gap): gap for gap, _ in view._buttons._groups}
    leading, group_gap = view._buttons._groups[0][0], view._buttons._groups[2][0]
    assert not leading.isVisible()
    assert view._buttons.group.isHidden()
    assert not group_gap.isVisible()
    assert view._buttons._groups[3][0].isVisible()
    assert len(gaps) == len(view._buttons._groups)


def test_the_bank_wraps_onto_another_row_rather_than_squeezing_its_buttons(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    view.show()
    host = view._buttons

    host.setFixedWidth(BUTTON_SIZE_HUD * 3)
    host.updateGeometry()
    qtbot.wait(10)

    shown = [b for _gap, group in view._buttons._groups for b in group
             if not b.isHidden()]
    assert len(shown) > 3
    for button in shown:
        assert button.size() == QSize(BUTTON_SIZE_HUD, BUTTON_SIZE_HUD)
    rows = {button.y() for button in shown}
    assert len(rows) > 1
    assert host.heightForWidth(host.width()) >= BUTTON_SIZE_HUD * len(rows)


def test_a_favorite_row_renders_a_favorite_tile(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    db = FakeDB(rows)
    db.set_generation_favorite("i2", True)
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)

    assert view._gallery_pane._thumb_widgets["i1"]._favorite is False
    assert view._gallery_pane._thumb_widgets["i2"]._favorite is True


def test_right_click_favorite_favorites_the_picked_thumbnail(qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    db = FakeDB(rows)
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    _answer_menu(monkeypatch, "Favorite 1 item")

    view._gallery_pane._thumbnail_context_menu("i1", QPoint(0, 0))

    assert db.get_generation("i1")["starred"]
    assert view._gallery_pane._thumb_widgets["i1"]._favorite is True


def test_right_click_unfavorite_clears_a_favorite_thumbnail(qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1)]
    db = FakeDB(rows)
    db.set_generation_favorite("i1", True)
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    _answer_menu(monkeypatch, "Unfavorite 1 item")

    view._gallery_pane._thumbnail_context_menu("i1", QPoint(0, 0))

    assert not db.get_generation("i1")["starred"]


def test_right_click_favorite_acts_on_the_whole_multi_selection(qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2),
            _image("i3", "a cat", 50, 3)]
    db = FakeDB(rows)
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view._gallery_pane.apply_selection("i1", _NO_MOD)
    view._gallery_pane.apply_selection("i3", _CTRL)
    _answer_menu(monkeypatch, "Favorite 2 items")

    view._gallery_pane._thumbnail_context_menu("i3", QPoint(0, 0))

    assert db.get_generation("i1")["starred"]
    assert db.get_generation("i3")["starred"]
    assert not db.get_generation("i2").get("starred")
