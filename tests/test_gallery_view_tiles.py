from __future__ import annotations

import json
import threading
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
from origenerator.gui.enhance_versions import _AddRow, _LevelRow, enhance_level_mime
from origenerator.gui.gallery_view import GalleryView
from origenerator.gui.media_badge import MediaBadge
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
from tests.test_enhance_panel import _dropped_on
from tests.test_folder_tree import _shown

pytestmark = pytest.mark.usefixtures("_stub_preview_resolution")


def _two_images_on_screen(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]))
    _on_screen(qtbot, view, 1400, 900)
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    return view, view._browser._thumb_widgets["i2"]


def test_dragging_an_image_lights_the_tabs_start_image_until_it_is_let_go(qtbot, monkeypatch):
    view, tile = _two_images_on_screen(qtbot)
    panel = view._info_tabs.current_config_panel()
    panel._workflow_combo.setCurrentIndex(panel._workflow_combo.findData("wan22_i2v"))
    well = panel._param_form._widgets["input_image"]._label
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

    # A collection gathers items from all over, so where this one actually lives is
    # the question its menu is most often asked — it leads, above a separator.
    assert labels == ["Go to folder", "Copy name", "", "Favorite 1 item", "Enhance 1 image",
                      "Delete 1 item"]
    assert view.selected_prompt_ids() == ["i2"]  # right-clicking picked it


def test_go_to_folder_is_left_off_inside_the_items_own_folder(qtbot, monkeypatch):
    # Standing in the folder already, it is a click that changes nothing — which
    # is what leaves it appearing exactly where it earns its place.
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
    monkeypatch.setattr("origenerator.gui.enhance_controller.gallery.level_matching_settings",
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
    view._browser.apply_selection("i1", _NO_MOD)
    view._browser.apply_selection("i3", _CTRL)
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
    db.add(_image("i2", "a cat", 50, 2))  # landed since the gallery last drew
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
    view._browser.apply_selection("i1", _NO_MOD)
    view._browser.apply_selection("i3", _CTRL)
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
    view._browser.clear_selection()
    QApplication.clipboard().clear()

    _press_ctrl_c(view, monkeypatch)

    assert QApplication.clipboard().text() == gallery.folder_id(
        gallery.settings_folder_key(rows[0]))


def test_ctrl_c_over_picked_folders_copies_each_folders_name(qtbot, monkeypatch):
    view, cat, dog = _two_leaf_view(qtbot)
    _pick(view, cat, dog)
    view._browser.clear_selection()
    QApplication.clipboard().clear()

    _press_ctrl_c(view, monkeypatch)

    assert QApplication.clipboard().text() == "\n".join(
        gallery.folder_id(gallery.settings_folder_key(_image(pid, prompt, 50, 1)))
        for pid, prompt in (("i1", "a cat"), ("i2", "a dog")))


def test_ctrl_c_in_a_focused_text_field_is_left_to_the_field(qtbot, tmp_path, monkeypatch):
    view, _db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    _open_leaf(view)
    view._browser.apply_selection("i1", _NO_MOD)
    monkeypatch.setattr(view, "_other_window_owns_keys", lambda: False)
    editor = QLineEdit()
    monkeypatch.setattr(
        "origenerator.gui.gallery_view.QApplication.focusWidget", lambda: editor
    )
    QApplication.clipboard().setText("words copied from the field")

    taken = view.eventFilter(view, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_C, _CTRL))

    assert (taken, QApplication.clipboard().text()) == (False, "words copied from the field")


def _folder_buttons(view):
    """The "Go to folder" buttons the front tab is actually drawing."""
    panel = view._info_tabs.current_config_panel()
    return [button for button in panel.findChildren(QPushButton, "goToFolderButton")
            if button.isVisibleTo(panel)]


def test_the_go_to_folder_button_takes_a_collection_item_home_without_a_right_click(qtbot):
    # Pressed and released like a real one, because going there rebuilds the
    # block it sits in: the button is destroyed in the middle of its own click.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    _click_tile(view, "i2")
    (button,) = _folder_buttons(view)
    button.show()   # an unshown button has no rect for a press to land in

    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)

    assert view._tree.currentItem() is view._leaf_by_id["i2"]
    assert view.selected_prompt_ids() == ["i2"]


def test_no_go_to_folder_button_inside_the_items_own_folder(qtbot):
    # Standing in the folder already, there is nowhere for it to take you, and a
    # button that would do nothing is not drawn — the rule its right-click entry
    # has always followed.
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._leaf_by_id["i1"])   # which opens on i1

    assert _folder_buttons(view) == []


def test_a_deleted_item_offers_no_way_to_a_folder(qtbot):
    view = _trash_collection_view(qtbot, FakeActions())

    _click_tile(view, "d1")

    assert _folder_buttons(view) == []      # it left its folder when its row did


def test_a_video_goes_to_its_folder_from_the_same_button(qtbot):
    # A video's block above the settings carries its file, where an image's
    # carries none; the way to the folder sits over both the same.
    view = GalleryView(FakeDB([_i2v_video("v1", "smooth")]), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    _click_tile(view, "v1")

    (button,) = _folder_buttons(view)
    button.click()

    assert view._tree.currentItem() is view._leaf_by_id["v1"]


def test_a_kind_left_off_a_collection_still_has_its_folder_to_go_to(qtbot):
    # Standing in the videos' Latest leaves the folder list whole, so a tab
    # showing an image still has somewhere to go.
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

    view._tree.setCurrentItem(_alls(view._tree)["Latest"])   # the tab stays on i1

    (button,) = _folder_buttons(view)
    assert button.toolTip() == "Go to the folder this item is in"


def test_right_click_delete_on_the_latest_collection_removes_the_item(qtbot, monkeypatch):
    actions = FakeActions()
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows), actions=actions)
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    monkeypatch.setattr(  # Delete is the menu's last entry
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

    assert db.get_generation("i1")["starred"]                # persisted
    assert view._browser.showing_recents()                           # still in the collection
    assert view._browser._thumb_widgets["i1"]._favorite is True    # the tile takes the star at once


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

    assert view._browser._thumb_widgets["v1"].findChildren(QMovie)          # the video loops
    assert view._browser._thumb_widgets["i1"].findChildren(QMovie) == []    # the image is a still
    # Each tile resolved its preview through the shared helper, with the app's dirs.
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

    view._tree.setCurrentItem(view._leaf_by_id["v1"])  # the video's settings folder
    assert view._browser._thumb_widgets["v1"].findChildren(QMovie)  # its grid tile loops


def test_a_videos_moving_preview_is_made_off_the_window_thread_while_its_tile_shows_its_still(
        qtbot, tmp_path, monkeypatch):
    webp = _write_looping_webp(tmp_path / "v1_anim.webp")
    rows = [_row("v1", "wan22_i2v",
                 {"positive_prompt": "dance", "seed": 5}, "wan22_i2v_v1.mp4")]
    made_on = []
    monkeypatch.setattr(gallery, "animated_preview_if_made",
                        lambda row, o, t: str(webp) if made_on else None)
    monkeypatch.setattr(gallery, "make_animated_preview",
                        lambda row, o, t: made_on.append(threading.current_thread()) or str(webp))
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._leaf_by_id["v1"])

    assert view._browser._thumb_widgets["v1"].findChildren(QMovie) == []
    qtbot.waitUntil(lambda: bool(view._browser._thumb_widgets["v1"].findChildren(QMovie)))
    assert made_on
    assert threading.main_thread() not in made_on


def test_recents_tiles_are_badged_image_or_video(qtbot):
    # The collection mixes kinds, so each finished tile wears a corner badge naming its
    # own — an image thumbnail and a video thumbnail, told apart at a glance.
    rows = [
        _image("i1", "a cat", 50, 1),
        _row("v1", "wan22_i2v", {"positive_prompt": "dance", "seed": 5}, "wan22_i2v_v1.mp4"),
    ]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])

    def badge_type(pid):
        badges = view._browser._thumb_widgets[pid].findChildren(MediaBadge)
        return badges[0].media_type if badges else None

    assert badge_type("i1") == "image"
    assert badge_type("v1") == "video"


def test_inflight_card_is_badged_by_its_media_type(qtbot):
    # A running video row with no file yet still badges its in-flight card a video,
    # inferred from the workflow — so the kind reads before the first frame lands.
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.add(_running_row("rr1", workflow="wan22_i2v"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    items = {it.key: it for it in view._inflight_items()}
    assert items["rr1"].media_type == "video"


def _source_tile(view):
    return view._info_tabs.current_config_panel()._related._source_tile


def test_video_source_tile_points_to_its_image_and_navigates(qtbot):
    image = _image("img1", "a cat", 50, 1)  # output: sdxl_t2i_img1.png
    video = _row("vid1", "wan22_i2v",
                 {"positive_prompt": "dance", "seed": 5,
                  "input_image": "sdxl_t2i_img1.png"},
                 "wan22_i2v_00001_.mp4")
    view = GalleryView(FakeDB([video, image]), client=ComfyUIClient(folders=SUITE_FOLDERS))
    qtbot.addWidget(view)
    view.refresh()
    for panel in view._info_tabs.config_panels():
        panel._preview.show_media = MagicMock()  # don't start WMF playback

    # Viewing the video shows a tile pointing back to the image it was built from.
    view._on_thumbnail_clicked("vid1")
    assert not _source_tile(view).isHidden()
    assert _source_tile(view)._prompt_id == "img1"

    # Clicking that tile navigates the gallery to the source image.
    _source_tile(view).activated.emit("img1")
    assert "img1" in view.listed_prompt_ids()
    assert view._selected["prompt_id"] == "img1"
    # The image itself has no source image, so no tile shows.
    view._on_thumbnail_clicked("img1")
    assert _source_tile(view).isHidden()


def test_toolbar_is_a_group_of_compact_icon_buttons(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    # Back, forward, undo and delete are one group of icon-only tool buttons, not
    # the oversized text buttons that split them across the header.
    for btn in (view._bank.back, view._bank.forward, view._bank.undo, view._bank.delete):
        assert isinstance(btn, QToolButton)
        assert not btn.icon().isNull()
        assert btn.text() == ""


def test_delete_button_enables_for_a_selection_or_a_deletable_folder(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    workflow = _image_workflow(view._tree)  # a workflow — not deletable, nothing picked
    view._tree.setCurrentItem(workflow)
    assert not view._bank.delete.isEnabled()

    _select_first_leaf(view)                    # a settings folder — deletable
    assert view._bank.delete.isEnabled()

    _click_tile(view, "i1")               # a picked thumbnail — deletable
    assert view._bank.delete.isEnabled()


def test_delete_button_deletes_the_picked_thumbnails(qtbot):
    actions = FakeActions()
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]),
                       actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    _click_tile(view, "i1")

    view._bank.delete.click()

    assert actions.deleted
    assert {r["prompt_id"] for r in actions.deleted[0]} == {"i1"}


# --- the bank's act-on-this trio: star and enhance aim where delete aims ------


def test_favorite_button_aims_at_the_picked_thumbnails_and_toggles(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    _click_tile(view, "i1")

    assert view._bank.favorite.isEnabled()
    assert view._bank.favorite.toolTip() == "Favorite 1 item"
    view._bank.favorite.click()
    assert db.get_generation("i1")["starred"]

    # A second press is the other half of the one toggle.
    _click_tile(view, "i1")
    assert view._bank.favorite.toolTip() == "Unfavorite 1 item"
    view._bank.favorite.click()
    assert not db.get_generation("i1")["starred"]


def test_favorite_button_falls_back_to_the_folder_on_screen(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    _click_off(view)                               # nothing picked inside it
    assert view._bank.favorite.isEnabled()
    assert "folder" in view._bank.favorite.toolTip()

    view._bank.favorite.click()

    key = _selected_folder(view)
    assert view._db.folder_meta_map()[key]["starred"]


def test_favorite_button_is_dark_where_a_favorite_means_nothing(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, LATEST_KEY))   # a collection is nobody's folder
    assert not view._bank.favorite.isEnabled()
    assert view._bank.favorite.toolTip() == "Nothing here to favorite"


def test_enhance_button_takes_the_picked_thumbnails_over_the_folder(qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path, count=2), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    queued = []
    view._enhance.enhance_items = queued.append

    _click_tile(view, "g0")
    assert view._bank.enhance.toolTip().startswith("Enhance 1 item")
    view._bank.enhance.click()

    assert queued == [["g0"]]  # just the picked one, not the whole folder


def _video_leaf(view):
    """Open the settings folder under the video workflow, its deepest branch's
    only leaf."""
    item = _video_workflow(view._tree)
    while item.childCount():
        item.setExpanded(True)
        item = _at(item, 0)
    view._tree.setCurrentItem(item)


def test_enhance_is_dark_on_a_video_and_says_why(qtbot):
    # There is no video enhancer — the workflow under all of this refines a
    # still — so a picked video is nothing to run, not a run that fails.
    view = GalleryView(FakeDB([_i2v_video("v1", "styleA")]))
    qtbot.addWidget(view)
    view.refresh()
    _video_leaf(view)
    assert not view._bank.enhance.isEnabled()   # the folder holds only videos

    _click_tile(view, "v1")
    assert not view._bank.enhance.isEnabled()
    assert "no video enhancer" in view._bank.enhance.toolTip()


def test_the_enhance_panel_grays_out_on_a_video_too(qtbot):
    view = GalleryView(FakeDB([_i2v_video("v1", "styleA"), _image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    _video_leaf(view)
    assert not view._enhance.panel.isEnabled()
    assert "no video enhancer" in view._enhance.panel.toolTip()

    _select_first_leaf(view)   # back on images, and the settings come back
    assert view._enhance.panel.isEnabled()
    assert view._enhance.panel.toolTip() == ""


def test_enhance_goes_dark_on_an_image_already_made_at_these_settings(qtbot, tmp_path):
    # Pressing it would spend a generation arriving at the image already
    # sitting in the version list. Turning any setting makes it a different
    # enhancement, and the button comes back — which is what tells the two
    # reasons apart: "you have this one" rather than "not this image".
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    settings = gallery.EnhanceSettings(auto=False, params={"enhance_scale": 2.0})
    view.set_enhance_settings(settings.to_json())
    _enhanced_in_place(db)
    # The level records what the run actually used, as a landed enhance does —
    # the source-matched model resolved to this image's own checkpoint.
    db.update_generation("g0", enhance_history=json.dumps([
        {"filename": "image_enhance_00001_.png",
         "params": gallery.enhance_params_for(db.get_generation("g0"), settings)},
    ]))
    view.refresh()
    _select_first_leaf(view)

    _click_tile(view, "g0")
    assert not view._bank.enhance.isEnabled()
    assert "these settings" in view._bank.enhance.toolTip()

    # The panel edited to something else: that enhancement doesn't exist yet.
    view._enhance._on_settings_changed(
        gallery.EnhanceSettings(auto=False, params={"enhance_scale": 3.0}))
    assert view._bank.enhance.isEnabled()


def test_a_version_dragged_onto_the_enhance_panel_grays_the_enhance_that_would_repeat_it(
        qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(detail_parts, "list_detector_files", lambda: ["hand_finder.pt"])
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.set_enhance_settings(gallery.EnhanceSettings(auto=False, params={
        "enhance_scale": 3.0,
        "enhance_fix_prompts": {"hands": {"prompt": "open palms", "avoid": "fists"}}}).to_json())
    _enhanced_in_place(db)
    # Made before a fix had prompts of its own, so the version records none.
    ran = gallery.enhance_params_for(db.get_generation("g0"), gallery.EnhanceSettings(
        params={"enhance_scale": 2.0, "enhance_detail_fixes": {"hands": 0.45}}))
    ran.pop("enhance_fix_prompts")
    db.update_generation("g0", enhance_history=json.dumps([
        {"filename": "image_enhance_00001_.png", "params": ran}]))
    view.refresh()
    _select_first_leaf(view)
    _click_tile(view, "g0")
    versions = view._info_tabs.current_config_panel()._versions
    version = next(row for row in versions._host.findChildren(_LevelRow) if row._params)
    mime = enhance_level_mime(version._params)

    _dropped_on(view._enhance.panel, mime)

    assert not view._bank.enhance.isEnabled()
    (tile,) = versions._host.findChildren(_AddRow)
    assert "already has a version" in tile.toolTip()


# --- the controls a tile wears in its own corners -----------------------------


def test_a_star_pressed_on_one_tile_favorites_it_at_once_and_leaves_the_rest(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)])
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])  # both on screen

    view._browser._thumb_widgets["i2"]._controls.triggered.emit(corner_controls.STAR)

    assert db.get_generation("i2")["starred"]
    assert view._browser._thumb_widgets["i2"]._favorite is True   # the tile takes the star at once
    assert not db.get_generation("i1").get("starred")


def test_a_favorite_tiles_favorite_corner_takes_the_favorite_away(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.set_generation_favorite("i1", True)
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    view._browser._thumb_widgets["i1"]._controls.triggered.emit(corner_controls.STAR)

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
    assert view._browser._thumb_widgets["i1"]._favorite is True
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

    view._browser._thumb_widgets["g0"]._controls.triggered.emit(corner_controls.STAR)

    assert view.listed_prompt_ids() == []


def test_favoriting_the_picked_items_turns_the_favorite_button_to_unfavorite(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    _click_tile(view, "i1")
    assert view._bank.favorite.toolTip() == "Favorite 1 item"

    view._bank.favorite.click()

    assert view._bank.favorite.toolTip() == "Unfavorite 1 item"


def test_a_tiles_trash_corner_deletes_that_tile(qtbot):
    actions = FakeActions()
    db = FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)])
    view = GalleryView(db, actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])  # both on screen

    view._browser._thumb_widgets["i2"]._controls.triggered.emit(corner_controls.TRASH)

    assert [r["prompt_id"] for r in actions.deleted[0]] == ["i2"]


def test_a_corner_control_acts_on_its_own_tile_not_the_selection(qtbot):
    # The control is drawn on a particular image, in that image's own corner,
    # so it has already said which item it is about. The menu is where a whole
    # selection is acted on.
    db = FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 2)])
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])  # both on screen
    _click_tile(view, "i1")
    view._browser.selected_ids.add("i2")   # both picked, as a Ctrl-click

    view._browser._thumb_widgets["i1"]._controls.triggered.emit(corner_controls.STAR)

    assert db.get_generation("i1")["starred"]
    assert not db.get_generation("i2").get("starred")


def test_a_tiles_plus_corner_queues_an_enhance_of_that_image(qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path, count=1), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    view._browser._thumb_widgets["g0"]._controls.triggered.emit(corner_controls.ENHANCE)

    (job,) = view._live_jobs.values()
    assert job.workflow.name == "image_enhance"


def test_pressing_a_tabs_preview_star_turns_that_star_on(qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path, count=1))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    _click_tile(view, "g0")
    star = view._info_tabs.current_config_panel()._preview._controls.buttons()[0]

    star.click()

    assert star.toolTip() == "Unfavorite this item"


def test_a_tabs_preview_plus_stops_offering_once_its_enhancement_lands(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_enhanceable_db(tmp_path, count=1), client=client)
    qtbot.addWidget(view)
    view.refresh()
    view._on_thumbnail_clicked("g0")
    plus = view._info_tabs.current_config_panel()._preview._controls.buttons()[2]
    plus.click()
    (job,) = view._jobs.all_jobs

    client.job_completed.emit(job.prompt_id, _ENHANCE_HISTORY)

    assert not plus.isEnabled()


def test_an_unenhanced_image_offers_its_first_enhancement_in_the_corner(qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path, count=1), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    assert view._browser._thumb_widgets["g0"].enhance_state() == icons.ENHANCE_OPEN


def test_a_video_tile_has_no_enhance_corner_to_offer(qtbot):
    view = GalleryView(FakeDB([_i2v_video("v1", "styleA")]), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])

    assert view._browser._thumb_widgets["v1"].enhance_state() is None


def test_the_enhance_corner_offers_another_the_moment_a_setting_moves(qtbot, tmp_path):
    # An image holding the very version the panel describes has nothing to gain
    # from a press, so its plus is the solid yellow badge alone. Turn a setting and
    # what it holds is one enhancement short of what the panel now describes, so
    # the plus goes back to offering — with the one it has as a shadow under it.
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
    assert view._browser._thumb_widgets["g0"].enhance_state() == icons.ENHANCE_HELD

    view._enhance._on_settings_changed(
        gallery.EnhanceSettings(auto=False, params={"enhance_scale": 3.0}))

    # Re-read in place: no tile was touched and the pane was never rebuilt.
    assert view._browser._thumb_widgets["g0"].enhance_state() == icons.ENHANCE_MORE


def test_a_mixed_pick_enhances_the_images_in_it(qtbot):
    # A folder can hold both; picking across them enhances what can be enhanced
    # rather than going dark because one video is in the set.
    db = FakeDB([_image("i1", "a cat", 50, 1), _i2v_video("v1", "styleA")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    _click_tile(view, "i1")
    view._browser.selected_ids.add("v1")   # as a Ctrl-click across the two
    view._re_aim()
    queued = []
    view._enhance.enhance_items = queued.append

    assert view._bank.enhance.isEnabled()
    assert view._enhance.panel.isEnabled()
    view._bank.enhance.click()

    assert queued == [["i1"]]


def test_the_bank_groups_its_buttons_with_a_space_between(qtbot):
    # Icon-only buttons lean on their neighbors to be read, so the bank is laid
    # out in groups: where you are, what you did, what you picked, what to do
    # with what's in front of you, and what the app is doing on its own.
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    groups = [buttons for _gap, buttons in view._bank._groups]
    assert groups[0] == (view._bank.back, view._bank.forward)
    assert groups[1] == (view._bank.undo, view._bank.redo)
    assert groups[3] == (view._bank.favorite, view._bank.enhance, view._bank.delete)
    assert view._bank.auto in groups[4]
    assert view._bank.radio in groups[4]
    # The mic has a space of its own: the group beside it is what the app is
    # doing, and the mic is what it hears with.
    assert groups[5] == (view._bank.mic,)
    assert view._bank.mic not in groups[4]


def test_a_group_with_nothing_showing_takes_no_space(qtbot):
    # Group, Auto and Slideshow come and go; the space in front of them must go
    # with them, or the bank wears a stray gap (or two in a row) where a hidden
    # group used to be, and starts indented.
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    view.show()
    _select_first_leaf(view)

    gaps = {id(gap): gap for gap, _ in view._bank._groups}
    leading, group_gap = view._bank._groups[0][0], view._bank._groups[2][0]
    assert not leading.isVisible()          # nothing to separate from, at the front
    assert view._bank.group.isHidden()
    assert not group_gap.isVisible()
    assert view._bank._groups[3][0].isVisible()  # the trio is always there
    assert len(gaps) == len(view._bank._groups)


def test_the_bank_wraps_onto_another_row_rather_than_squeezing_its_buttons(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    view.show()
    host = view._bank

    host.setFixedWidth(BUTTON_SIZE_HUD * 3)  # far narrower than the whole bank
    host.updateGeometry()
    qtbot.wait(10)

    shown = [b for _gap, group in view._bank._groups for b in group
             if not b.isHidden()]
    assert len(shown) > 3                       # more buttons than fit on one row
    for button in shown:
        assert button.size() == QSize(BUTTON_SIZE_HUD, BUTTON_SIZE_HUD)  # none squeezed
    rows = {button.y() for button in shown}
    assert len(rows) > 1                        # so they went onto further rows
    assert host.heightForWidth(host.width()) >= BUTTON_SIZE_HUD * len(rows)


def test_a_favorite_row_renders_a_favorite_tile(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    db = FakeDB(rows)
    db.set_generation_favorite("i2", True)
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)

    assert view._browser._thumb_widgets["i1"]._favorite is False
    assert view._browser._thumb_widgets["i2"]._favorite is True


def test_right_click_favorite_favorites_the_picked_thumbnail(qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    db = FakeDB(rows)
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    _answer_menu(monkeypatch, "Favorite 1 item")

    view._browser._thumbnail_context_menu("i1", QPoint(0, 0))

    assert db.get_generation("i1")["starred"]           # persisted
    assert view._browser._thumb_widgets["i1"]._favorite is True  # the tile takes the star at once


def test_right_click_unfavorite_clears_a_favorite_thumbnail(qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1)]
    db = FakeDB(rows)
    db.set_generation_favorite("i1", True)
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    _answer_menu(monkeypatch, "Unfavorite 1 item")  # a favorited item offers Unfavorite

    view._browser._thumbnail_context_menu("i1", QPoint(0, 0))

    assert not db.get_generation("i1")["starred"]      # cleared


def test_right_click_favorite_acts_on_the_whole_multi_selection(qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2),
            _image("i3", "a cat", 50, 3)]
    db = FakeDB(rows)
    view = GalleryView(db, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view._browser.apply_selection("i1", _NO_MOD)
    view._browser.apply_selection("i3", _CTRL)  # i1 + i3 selected
    _answer_menu(monkeypatch, "Favorite 2 items")

    view._browser._thumbnail_context_menu("i3", QPoint(0, 0))

    assert db.get_generation("i1")["starred"]
    assert db.get_generation("i3")["starred"]
    assert not db.get_generation("i2").get("starred")  # untouched
