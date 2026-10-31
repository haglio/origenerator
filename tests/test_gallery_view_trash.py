from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import (
    QEvent,
    QPoint,
    Qt,
)
from PyQt6.QtGui import (
    QKeyEvent,
)
from PyQt6.QtWidgets import (
    QApplication,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QScrollArea,
)

from origenerator import (
    gallery,
)
from origenerator.branch_session import ENV_FLAG
from origenerator.db import Database
from origenerator.gallery.collection import (
    RECENTS_KEY,
    TRASH_KEY,
)
from origenerator.gallery.output import resolve_preview as real_resolve_preview
from origenerator.gallery_actions import GalleryActions
from origenerator.gui import gallery_view as gallery_view_module
from origenerator.gui.gallery_view import _GROUP_ROLE, GalleryView
from origenerator.output_places import OutputPlaces
from origenerator.trash import Trash
from tests import gestures
from tests.gallery_view_support import (
    _CTRL,
    _NO_MOD,
    FakeActions,
    FakeDB,
    _alls,
    _answer_confirmation,
    _answer_menu,
    _at,
    _bin_db,
    _click_beside_the_mark_of,
    _click_off,
    _click_tile,
    _collection,
    _double_click_slideshow,
    _i2v_video,
    _image,
    _image_workflow,
    _key,
    _menu_labels,
    _name_of,
    _open_leaf,
    _resolve_by_id,
    _right_click,
    _shown_view_with_one_image,
    _top_level,
    _trash_collection_view,
    _video_workflow,
    _workflow_rows,
)
from tests.test_folder_tree import _shown

pytestmark = pytest.mark.usefixtures("_stub_preview_resolution")


_SHIFT = Qt.KeyboardModifier.ShiftModifier


# --- the Trash collection: deleted items, still recoverable -----------------


def test_the_trash_collection_is_always_reachable(qtbot):
    # A bin you can only find once you have something to recover is no use: the
    # point is knowing, before you delete, that deleting is not the end.
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    view.refresh()

    collection = _alls(view._tree)["Trash"]
    assert collection.text(0) == "Trash"


def test_the_trash_collection_label_counts_what_it_holds(qtbot):
    view = GalleryView(_bin_db(held=[("d1", _image("d1", "a cat", 50, 1)),
                                     ("d2", _image("d2", "a dog", 50, 2))]))
    qtbot.addWidget(view)
    view.refresh()

    assert _shown(_alls(view._tree)["Trash"]) == "(2) Trash"


def test_the_trash_collection_lists_deleted_items_newest_first(qtbot):
    view = GalleryView(_bin_db(held=[("old", _image("old", "a cat", 50, 1)),
                                     ("new", _image("new", "a dog", 50, 2))]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_collection(view, TRASH_KEY))
    assert view.listed_prompt_ids() == ["new", "old"]


def test_following_a_link_to_an_item_in_the_trash_opens_the_trash_on_it(qtbot):
    view = GalleryView(_bin_db(held=[("d1", _image("d1", "a cat", 50, 1))]))
    qtbot.addWidget(view)
    view.refresh()

    view.follow_link("d1")

    assert view._browser.showing_trash()
    assert view.listed_prompt_ids() == ["d1"]


def test_a_deleted_item_reaches_the_collection_the_moment_it_is_deleted(qtbot, tmp_path):
    # End to end through the real GalleryActions: delete a tile, and the item is
    # standing in the Trash collection rather than gone.
    db = Database(tmp_path / "test.db")
    db.insert_generation(prompt_id="p1", workflow_name="sdxl_t2i",
                         workflow_version="v1", params_json="{}", workflow_json="{}")
    db.update_generation("p1", status="completed",
                         output_files=json.dumps([{"filename": "a.png", "subfolder": ""}]))
    view = GalleryView(db, actions=GalleryActions(db, OutputPlaces.in_one_folder(tmp_path / "out"),
                                                  Trash(tmp_path / "trash")))
    qtbot.addWidget(view)
    view.refresh()

    view._delete_rows([db.get_generation("p1")])

    view._tree.setCurrentItem(_collection(view, TRASH_KEY))
    assert view.listed_prompt_ids() == ["p1"]


def test_each_trash_tile_offers_restore_and_permanent_delete(qtbot):
    view = GalleryView(_bin_db(held=[("d1", _image("d1", "a cat", 50, 1))]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_collection(view, TRASH_KEY))
    tooltips = [b.toolTip() for b in view._browser._thumb_widgets["d1"]._corner_buttons]
    assert any("Restore" in t for t in tooltips)
    assert any("permanently" in t for t in tooltips)


def test_a_trash_tile_is_captioned_like_any_other_tile(qtbot):
    # Nothing counts down any more, so the caption has no deadline to carry and
    # says only what the item is.
    held = _image("d1", "a cat", 50, 1)
    view = GalleryView(_bin_db(held=[("d1", held)]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_collection(view, TRASH_KEY))
    caption = view._browser._thumb_widgets["d1"]._text_label.text()
    assert caption == f"{gallery.folder_id(gallery.settings_folder_key(held))} 000"


def test_an_old_version_the_backfill_sent_to_the_trash_says_so_on_its_tile(qtbot):
    held = {**_image("d1", "a cat", 50, 1), "old_version_of": "the video it was made again as"}
    view = GalleryView(_bin_db(held=[("d1", held)]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_collection(view, TRASH_KEY))
    caption = view._browser._thumb_widgets["d1"]._text_label.text()
    assert caption == f"Old version · {gallery.folder_id(gallery.settings_folder_key(held))} 000"


def test_the_trash_collection_states_no_deadline_over_what_it_holds(qtbot):
    view = GalleryView(_bin_db(held=[("d1", _image("d1", "a cat", 50, 1))]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_collection(view, TRASH_KEY))
    assert view._avg_label.text() == ""


def test_an_empty_trash_collection_explains_what_it_is_for(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_collection(view, TRASH_KEY))
    assert "as long as you leave them" in view._browser._trash_empty_hint()
    assert view._avg_label.text() == ""  # the hint already says it; don't say it twice


def test_restoring_from_a_tile_hands_the_id_to_the_action(qtbot):
    actions = FakeActions()
    view = GalleryView(_bin_db(held=[("d1", _image("d1", "a cat", 50, 1))]),
                       actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, TRASH_KEY))

    view._browser._thumb_widgets["d1"].corner_action_triggered.emit("d1", "restore")

    assert actions.restored == [["d1"]]


def test_a_restore_puts_the_item_back_in_its_own_folder(qtbot, tmp_path):
    db = Database(tmp_path / "test.db")
    db.insert_generation(prompt_id="p1", workflow_name="sdxl_t2i",
                         workflow_version="v1",
                         params_json=json.dumps({"steps": 20}), workflow_json="{}")
    db.update_generation("p1", status="completed",
                         output_files=json.dumps([{"filename": "a.png", "subfolder": ""}]))
    view = GalleryView(db, actions=GalleryActions(db, OutputPlaces.in_one_folder(tmp_path / "out"),
                                                  Trash(tmp_path / "trash")))
    qtbot.addWidget(view)
    view.refresh()
    view._delete_rows([db.get_generation("p1")])
    assert "Images" not in _top_level(view._tree)  # the folder emptied out with it

    view.restore_from_trash(["p1"])

    assert "SDXL T2I" in _workflow_rows(view._tree)      # back in the tree...
    assert view.listed_prompt_ids() == ["p1"]     # ...and landed on, not left in the collection
    assert view._db.list_deletions() == []


def test_purging_asks_before_it_ends_anything(qtbot, monkeypatch):
    # The one gallery action with no undo and no second copy under it.
    actions = FakeActions()
    view = GalleryView(_bin_db(held=[("d1", _image("d1", "a cat", 50, 1))]),
                       actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, TRASH_KEY))
    asked = []
    monkeypatch.setattr(view, "_confirm", lambda text: asked.append(text) or False)

    view._browser._thumb_widgets["d1"].corner_action_triggered.emit("d1", "purge")

    assert actions.purged == []                      # declined: nothing ended
    assert "cannot be undone" in asked[0]

    monkeypatch.setattr(view, "_confirm", lambda text: True)
    view._browser._thumb_widgets["d1"].corner_action_triggered.emit("d1", "purge")
    assert actions.purged == [["d1"]]


class _FailingActions(FakeActions):
    """Actions whose trash operations cannot complete — a trash folder moved out
    from under the app, a file the OS will not give back."""

    def restore_deleted(self, prompt_ids):
        raise OSError("the trash folder is gone")

    def purge_deleted(self, prompt_ids):
        raise OSError("the trash folder is gone")


def _warnings_shown(monkeypatch):
    """Collect what a warning dialog would have said, instead of opening one."""
    said = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda parent, title, text, *a, **kw: said.append((title, text))),
    )
    return said


_TWO_HELD = (("d1", "a cat"), ("d2", "a dog"))


def test_a_trash_tiles_menu_offers_the_names_and_the_two_acts_a_deleted_item_has(
        qtbot, monkeypatch):
    # The hover corners act on the one tile under the pointer; the menu acts on
    # the whole pick, which is the only way to answer for a batch at once.
    view = _trash_collection_view(qtbot, FakeActions(), held=_TWO_HELD)
    view._browser.apply_selection("d2", _CTRL)
    labels = []
    _menu_labels(monkeypatch, labels)

    _right_click(view, "d1")

    assert labels == ["Copy 2 names", "", "Restore 2 items", "Delete 2 items permanently"]


def test_a_trash_tiles_menu_copies_the_names_the_picked_items_had(qtbot, monkeypatch):
    view = _trash_collection_view(qtbot, FakeActions(), held=_TWO_HELD)
    view._browser.apply_selection("d2", _CTRL)
    QApplication.clipboard().clear()
    _answer_menu(monkeypatch, "Copy 2 names")

    _right_click(view, "d1")

    names = {"d1": _name_of(_image("d1", "a cat", 50, 1), 0),
             "d2": _name_of(_image("d2", "a dog", 50, 2), 0)}
    assert QApplication.clipboard().text() == "\n".join(
        names[prompt_id] for prompt_id in view.selected_prompt_ids())  # as the tiles stand


def test_restoring_from_a_trash_tiles_menu_brings_the_whole_pick_back(qtbot, monkeypatch):
    actions = FakeActions()
    view = _trash_collection_view(qtbot, actions, held=_TWO_HELD)
    view._browser.apply_selection("d2", _CTRL)
    picked = view.selected_prompt_ids()
    _answer_menu(monkeypatch, "Restore 2 items")

    _right_click(view, "d1")

    assert actions.restored == [picked]


def test_the_trash_tiles_menu_can_end_the_whole_pick_for_good(qtbot, monkeypatch):
    # This entry and the tile's own corner are the only two routes in the app that
    # take files with nothing under them, so the menu's wiring is not a detail.
    actions = FakeActions()
    view = _trash_collection_view(qtbot, actions, held=_TWO_HELD)
    view._browser.apply_selection("d2", _CTRL)
    picked = view.selected_prompt_ids()
    _answer_menu(monkeypatch, "Delete 2 items permanently")
    _answer_confirmation(monkeypatch, QMessageBox.StandardButton.Yes)

    _right_click(view, "d1")

    assert actions.purged == [picked]


def test_right_clicking_an_unpicked_trash_tile_narrows_to_that_one(qtbot, monkeypatch):
    # Otherwise a menu raised over one tile would answer for a pick somewhere else
    # in the collection — and here that means ending the wrong files for good.
    actions = FakeActions()
    view = _trash_collection_view(qtbot, actions, held=_TWO_HELD)  # d1 is the picked one
    _answer_menu(monkeypatch, "Restore 1 item")

    _right_click(view, "d2")

    assert actions.restored == [["d2"]]


def test_a_restore_that_cannot_finish_says_why_and_keeps_the_item_picked(
        qtbot, monkeypatch):
    # The arm that has never rendered once: a restore that throws must reach the
    # user as a sentence, not as a collection that quietly did nothing.
    view = _trash_collection_view(qtbot, _FailingActions())
    said = _warnings_shown(monkeypatch)

    view.restore_from_trash(["d1"])

    assert said == [("Restore failed",
                     "Could not restore the selected item(s):\n\nthe trash folder is gone")]
    assert view.selected_prompt_ids() == ["d1"]  # not cleared, as a success clears it


def test_a_purge_that_cannot_finish_says_why_and_keeps_the_item_picked(
        qtbot, monkeypatch):
    view = _trash_collection_view(qtbot, _FailingActions())
    _answer_confirmation(monkeypatch, QMessageBox.StandardButton.Yes)
    said = _warnings_shown(monkeypatch)

    view.purge_from_trash(["d1"])

    assert said == [("Delete failed",
                     "Could not permanently delete the selected item(s):"
                     "\n\nthe trash folder is gone")]
    assert view.selected_prompt_ids() == ["d1"]


def test_neither_trash_action_asks_anything_of_an_empty_pick(qtbot):
    # A "Permanently delete 0 items?" prompt would be the app asking the user to
    # confirm nothing; the confirmation is never reached (this test would trip the
    # suite's no-unanswered-dialog guard if it were).
    actions = _FailingActions()  # so much as touching them here would raise
    view = _trash_collection_view(qtbot, actions)

    view.restore_from_trash([])
    view.purge_from_trash([])

    assert actions.restored == []
    assert actions.purged == []


def test_delete_on_the_trash_collection_means_permanently(qtbot, monkeypatch):
    # The picked items are already deleted, so the button's one remaining
    # meaning is "for good" — rather than a live-looking control doing nothing.
    actions = FakeActions()
    view = GalleryView(_bin_db(held=[("d1", _image("d1", "a cat", 50, 1))]),
                       actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, TRASH_KEY))
    view._browser.apply_selection("d1", _NO_MOD)
    monkeypatch.setattr(view, "_confirm", lambda text: True)

    assert "Permanently delete 1 item" in view._bank.delete.toolTip()
    view._delete_selection()

    assert actions.purged == [["d1"]]
    assert actions.deleted == []  # and never the ordinary delete path


def test_the_delete_button_is_dark_on_an_unpicked_trash_collection(qtbot):
    view = GalleryView(_bin_db(held=[("d1", _image("d1", "a cat", 50, 1))]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_collection(view, TRASH_KEY))

    assert not view._bank.delete.isEnabled()


def test_a_purge_clears_the_item_off_the_collection(qtbot, tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    db.insert_generation(prompt_id="p1", workflow_name="sdxl_t2i",
                         workflow_version="v1", params_json="{}", workflow_json="{}")
    db.update_generation("p1", status="completed",
                         output_files=json.dumps([{"filename": "a.png", "subfolder": ""}]))
    view = GalleryView(db, actions=GalleryActions(db, OutputPlaces.in_one_folder(tmp_path / "out"),
                                                  Trash(tmp_path / "trash")))
    qtbot.addWidget(view)
    view.refresh()
    view._delete_rows([db.get_generation("p1")])
    monkeypatch.setattr(view, "_confirm", lambda text: True)

    view.purge_from_trash(["p1"])

    view._tree.setCurrentItem(_collection(view, TRASH_KEY))
    assert view.listed_prompt_ids() == []
    assert db.list_deletions() == []


def test_the_trash_collection_is_a_place_back_returns_to(qtbot):
    view = GalleryView(_bin_db([_image("i1", "a cat", 50, 1)],
                               held=[("d1", _image("d1", "a dog", 50, 2))]))
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_collection(view, TRASH_KEY))
    view._tree.setCurrentItem(_collection(view, RECENTS_KEY))
    view._navigation.go_back()

    assert view._tree.currentItem() is _collection(view, TRASH_KEY)


def test_a_preview_offers_every_held_deletion_like_the_live_app(qtbot, monkeypatch):
    # One library, one trash: what any instance deleted, any instance can put
    # back, so the collection holds the same items whichever app is looking at it.
    monkeypatch.setenv(ENV_FLAG, "1")
    db = _bin_db(held=[("mine", _image("mine", "a dog", 50, 2))],
                 inherited=[("live", _image("live", "a cat", 50, 1))])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(_collection(view, TRASH_KEY))
    assert sorted(view.listed_prompt_ids()) == ["live", "mine"]
    assert "preview" not in view._browser._trash_empty_hint()

    view.restore_from_trash(["mine"])

    assert db.get_generation("mine") is not None
    assert db.get_deletion("live") is not None  # still offered, untouched


# --- a deleted item is still a generation you can look at -------------------


def test_clicking_a_deleted_tile_opens_it_like_any_other_generation(qtbot):
    # Its row left the gallery, but the bin kept it whole and its files are all
    # in the trash — so it fills a config tab with the settings that made it,
    # which is the whole point of being able to look before you decide.
    view = GalleryView(_bin_db(held=[("d1", _image("d1", "a cat", 50, 1))]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, TRASH_KEY))

    _click_tile(view, "d1")

    assert view._selected_row["prompt_id"] == "d1"
    shown = view._info_tabs.current_config_panel().displayed_row()
    assert shown["prompt_id"] == "d1"


def test_double_clicking_a_deleted_tile_keeps_its_tab(qtbot):
    # The gesture a folder's tiles carry, since the one a collection's carry — jump to
    # its folder — is the single thing a deleted item hasn't got.
    view = GalleryView(_bin_db(held=[("d1", _image("d1", "a cat", 50, 1))]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, TRASH_KEY))

    view._browser._thumbnail_double_clicked("d1")

    panel = view._info_tabs.current_config_panel()
    assert panel.displayed_row()["prompt_id"] == "d1"
    assert view._info_tabs._preview_panel is not panel  # pinned: it stays


def test_the_trash_collection_plays_as_a_slideshow(qtbot, monkeypatch):
    # Deciding what to keep out of a bin of sixty days' deletions is exactly what
    # a slideshow is for — one at a time, full size, rather than a grid of stamps.
    _resolve_by_id(monkeypatch)
    view = GalleryView(_bin_db(held=[("d1", _image("d1", "a cat", 50, 1)),
                                     ("d2", _image("d2", "a dog", 50, 2))]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, TRASH_KEY))

    assert not view._bank.slideshow.isHidden()
    view._slideshows.start()

    qtbot.addWidget(view._slideshows.showing.shown)
    assert {item[2] for item in view._slideshows.showing._set.playlist._items} == {"d1", "d2"}
    view._slideshows.showing.close()


def test_a_deleted_item_double_clicked_open_steps_through_the_collection(qtbot, monkeypatch):
    # Left/Right work here for the same reason they work in a folder: the collection's
    # items resolve to real files, so there is a set to step through.
    _resolve_by_id(monkeypatch)
    view = GalleryView(_bin_db(held=[("d1", _image("d1", "a cat", 50, 1)),
                                     ("d2", _image("d2", "a dog", 50, 2))]))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_collection(view, TRASH_KEY))
    view._on_thumbnail_clicked("d1")

    slideshow = _double_click_slideshow(view, qtbot)

    assert [item[2] for item in slideshow._set.playlist._items] == view.listed_prompt_ids()
    assert slideshow._set.playlist.current()[2] == "d1"  # opened on the shown item
    slideshow.close()


def test_a_deleted_video_plays_its_own_file_out_of_the_trash(qtbot, tmp_path):
    # End to end through the real delete: what the collection hands the preview is the
    # clip where it now sits, not the folder it was taken out of.
    db = Database(tmp_path / "test.db")
    out = tmp_path / "out" / "video"
    out.mkdir(parents=True)
    (out / "clip.mp4").write_bytes(b"x")
    db.insert_generation(prompt_id="v1", workflow_name="wan22_i2v",
                         workflow_version="v1", params_json="{}", workflow_json="{}")
    db.update_generation("v1", status="completed", output_files=json.dumps(
        [{"filename": "clip.mp4", "subfolder": "video"}]))
    view = GalleryView(db, actions=GalleryActions(db, OutputPlaces.in_one_folder(tmp_path / "out"),
                                                  Trash(tmp_path / "trash")))
    qtbot.addWidget(view)
    view.refresh()
    view._delete_rows([db.get_generation("v1")])

    view._tree.setCurrentItem(_collection(view, TRASH_KEY))
    (held,) = view._held_rows
    # The real resolver, not this module's autouse "nothing to show" stub.
    resolved = real_resolve_preview(held, tmp_path / "out")

    assert resolved is not None
    path, media_type = resolved
    assert media_type == "video"
    assert Path(path).exists()
    assert Path(path).is_relative_to(tmp_path / "trash")


def _scroll_into_view(widget):
    """Bring *widget* into its scroll area's viewport, as a person scrolls to it."""
    inside = widget.parentWidget()
    while inside is not None and not isinstance(inside, QScrollArea):
        inside = inside.parentWidget()
    if inside is not None:
        inside.ensureWidgetVisible(widget)
        QApplication.processEvents()


# --- deletion & undo ------------------------------------------------------


def test_delete_key_deletes_the_selected_thumbnail(qtbot):
    actions = FakeActions()
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)

    view._browser.apply_selection("i1", _NO_MOD)
    view._delete_selection()

    assert len(actions.deleted) == 1
    assert [r["prompt_id"] for r in actions.deleted[0]] == ["i1"]


def test_a_branch_session_deletes_into_the_shared_trash(qtbot, monkeypatch, tmp_path):
    # The composition, not just the rule: a preview's gallery builds its actions
    # around the production app's trash, the same one its rows and files belong
    # to, so a delete in a preview is a delete -- recoverable from the Trash
    # collection of whichever instance looks next.
    monkeypatch.setenv(ENV_FLAG, "1")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    file_path = output_dir / "sdxl_t2i_i1.png"
    file_path.write_bytes(b"data")
    monkeypatch.setattr(gallery_view_module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output_dir))
    monkeypatch.setattr(gallery_view_module, "TRASH_DIR", tmp_path / "trash")
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db)  # builds its own actions, the way the app does
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)

    view._browser.apply_selection("i1", _NO_MOD)
    view._delete_selection()

    assert db.get_generation("i1") is None
    assert not file_path.exists()
    assert list((tmp_path / "trash").rglob("*.png"))


def test_ctrl_click_extends_selection_and_delete_takes_all_picked(qtbot):
    actions = FakeActions()
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2),
            _image("i3", "a cat", 50, 3)]
    view = GalleryView(FakeDB(rows), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)

    view._browser.apply_selection("i1", _NO_MOD)
    view._browser.apply_selection("i3", _CTRL)
    assert set(view.selected_prompt_ids()) == {"i1", "i3"}

    view._delete_selection()
    assert {r["prompt_id"] for r in actions.deleted[0]} == {"i1", "i3"}


def test_ctrl_click_again_deselects_a_tile(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)

    view._browser.apply_selection("i1", _NO_MOD)
    view._browser.apply_selection("i2", _CTRL)
    view._browser.apply_selection("i2", _CTRL)  # toggle i2 back off
    assert view.selected_prompt_ids() == ["i1"]


def test_shift_click_selects_the_contiguous_range(qtbot):
    rows = [_image(f"i{i}", "a cat", 50, i) for i in range(1, 5)]  # i1..i4
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    order = view.listed_prompt_ids()  # newest-first display order

    view._browser.apply_selection(order[0], _NO_MOD)
    view._browser.apply_selection(order[2], _SHIFT)
    assert view.selected_prompt_ids() == order[:3]


def test_plain_click_replaces_the_whole_selection(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)

    view._browser.apply_selection("i1", _NO_MOD)
    view._browser.apply_selection("i2", _CTRL)     # now both selected
    view._browser.apply_selection("i2", _NO_MOD)   # plain click collapses to one
    assert view.selected_prompt_ids() == ["i2"]


def test_changing_folders_clears_the_selection(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    cat_leaf = _open_leaf(view)
    view._browser.apply_selection("i1", _NO_MOD)
    assert view.selected_prompt_ids() == ["i1"]

    # Drilling to the sibling settings folder must not carry the pick over: what
    # is picked there is that folder's own first item.
    dog_leaf = _at(cat_leaf.parent(), 1)
    view._tree.setCurrentItem(dog_leaf)
    assert view.selected_prompt_ids() == ["i2"]


def test_clicking_the_pane_background_drops_the_selection(qtbot):
    """Click off and nothing is picked — the way out of a selection that would
    otherwise keep Enhance/Favorite/Delete aimed at one tile instead of the folder."""
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view._browser.apply_selection("i1", _NO_MOD)
    assert view.selected_prompt_ids() == ["i1"]

    pane = view._scroll.widget()
    pane.resize(600, 600)  # room under the tiles for a press to land on nothing
    qtbot.mouseClick(pane, Qt.MouseButton.LeftButton, pos=QPoint(560, 560))

    assert view.selected_prompt_ids() == []
    # And the buttons re-aimed with it: Enhance is the folder's again.
    assert "folder" in view._bank.enhance.toolTip()


def test_clicking_the_pane_background_leaves_the_tiles_on_screen(qtbot):
    """Dropping the pick is not a rebuild — the folder stays open, unhighlighted."""
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view._browser.apply_selection("i1", _NO_MOD)

    pane = view._scroll.widget()
    pane.resize(600, 600)
    qtbot.mouseClick(pane, Qt.MouseButton.LeftButton, pos=QPoint(560, 560))

    assert set(view.listed_prompt_ids()) == {"i1", "i2"}
    assert not any(w._selected for w in view._browser._thumb_widgets.values())


def test_clicking_a_thumbnail_keeps_its_press_to_itself(qtbot):
    """A tile answers its own click, so the pane under it never sees one — else
    picking a thumbnail would select it and deselect it in the same press."""
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)

    qtbot.mouseClick(view._browser._thumb_widgets["i1"], Qt.MouseButton.LeftButton)
    assert view.selected_prompt_ids() == ["i1"]


def test_right_clicking_the_pane_background_keeps_the_selection(qtbot):
    """Only a left press means "nothing" — a right one is on its way to a menu."""
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view._browser.apply_selection("i1", _NO_MOD)

    pane = view._scroll.widget()
    pane.resize(600, 600)
    qtbot.mouseClick(pane, Qt.MouseButton.RightButton, pos=QPoint(560, 560))

    assert view.selected_prompt_ids() == ["i1"]


def test_delete_on_a_settings_folder_with_no_pick_deletes_the_whole_folder(
        qtbot, monkeypatch):
    actions = FakeActions()
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    _click_off(view)  # leaf selected, nothing picked
    _answer_confirmation(monkeypatch, QMessageBox.StandardButton.Yes)

    view._delete_selection()

    assert {r["prompt_id"] for r in actions.deleted[0]} == {"i1", "i2"}


def test_deleting_a_folder_can_be_cancelled_at_the_prompt(qtbot, monkeypatch):
    actions = FakeActions()
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    _click_off(view)  # nothing picked, so Delete is the folder's
    _answer_confirmation(monkeypatch, QMessageBox.StandardButton.No)  # user says no

    view._delete_selection()

    assert actions.deleted == []


def test_delete_key_on_a_workflow_folder_does_nothing(qtbot):
    actions = FakeActions()
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    workflow = _image_workflow(view._tree)
    view._tree.setCurrentItem(workflow)  # a whole-workflow folder
    view._confirm = lambda text: True    # even if it asked, it must not

    view._delete_selection()

    assert actions.deleted == []  # workflow folders are off-limits


def test_a_failed_delete_is_surfaced_not_swallowed(qtbot, monkeypatch):
    class BoomActions(FakeActions):
        def delete_rows(self, rows):
            raise OSError("the file is held by another process")

    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), actions=BoomActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view._browser.apply_selection("i1", _NO_MOD)
    warned = []
    monkeypatch.setattr(
        "origenerator.gui.gallery_view.QMessageBox.warning",
        lambda *a, **k: warned.append(a),
    )

    view._delete_selection()  # must not raise

    assert warned  # the user is told the delete failed instead of nothing happening


def test_right_clicking_an_unpicked_thumbnail_selects_it(qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    monkeypatch.setattr("origenerator.gui.gallery_view.QMenu.exec", lambda self, *a: None)

    view._browser._thumbnail_context_menu("i2", QPoint(0, 0))

    assert view.selected_prompt_ids() == ["i2"]


def test_right_click_delete_removes_the_picked_thumbnails(qtbot, monkeypatch):
    actions = FakeActions()
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    # Choosing the menu's only entry ("Delete").
    monkeypatch.setattr(
        "origenerator.gui.gallery_view.QMenu.exec", lambda self, *a: self.actions()[-1]
    )

    view._browser._thumbnail_context_menu("i1", QPoint(0, 0))

    assert {r["prompt_id"] for r in actions.deleted[0]} == {"i1"}


def test_right_click_delete_acts_on_the_whole_multi_selection(qtbot, monkeypatch):
    actions = FakeActions()
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2),
            _image("i3", "a cat", 50, 3)]
    view = GalleryView(FakeDB(rows), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view._browser.apply_selection("i1", _NO_MOD)
    view._browser.apply_selection("i3", _CTRL)  # i1 + i3 selected
    monkeypatch.setattr(
        "origenerator.gui.gallery_view.QMenu.exec", lambda self, *a: self.actions()[-1]
    )

    # Right-clicking a tile already in the selection keeps the whole set.
    view._browser._thumbnail_context_menu("i3", QPoint(0, 0))

    assert {r["prompt_id"] for r in actions.deleted[0]} == {"i1", "i3"}


def test_right_clicking_a_selected_tile_preserves_the_multi_selection(qtbot, monkeypatch):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2),
            _image("i3", "a cat", 50, 3)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    view._browser.apply_selection("i1", _NO_MOD)
    view._browser.apply_selection("i3", _CTRL)  # i1 + i3
    monkeypatch.setattr("origenerator.gui.gallery_view.QMenu.exec", lambda self, *a: None)

    # A real right-press on a selected tile must not collapse the selection to one.
    qtbot.mouseClick(view._browser._thumb_widgets["i3"], Qt.MouseButton.RightButton)

    assert set(view.selected_prompt_ids()) == {"i1", "i3"}


def test_deleting_a_folder_lands_on_the_parent_not_the_top(qtbot, tmp_path):
    db = Database(tmp_path / "g.db")
    out = tmp_path / "output"
    out.mkdir()
    for pid, prompt in [("i1", "a cat"), ("i2", "a dog")]:  # two settings groups, one model
        db.insert_generation(
            prompt_id=pid, workflow_name="sdxl_t2i", workflow_version="v1",
            positive_prompt=prompt,
            params_json=json.dumps({"positive_prompt": prompt, "steps": 20}),
            workflow_json="{}",
        )
        (out / f"sdxl_t2i_{pid}.png").write_bytes(b"x")
        db.update_generation(
            pid, status="completed",
            output_files=json.dumps([{"filename": f"sdxl_t2i_{pid}.png", "subfolder": ""}]),
        )
    actions = GalleryActions(db, OutputPlaces.in_one_folder(out), Trash(tmp_path / "trash"))
    view = GalleryView(db, actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    model = _at(_image_workflow(view._tree), 0)
    view._tree.setCurrentItem(_at(model, 0, 0))  # one of the two settings leaves
    _click_off(view)                                   # nothing picked: Delete is the folder's
    view._confirm = lambda text: True

    view._delete_selection()  # deletes that settings folder

    # The leaf's parent — the "(no LoRA)" folder — survives via its sibling leaf,
    # so the tree falls back onto it rather than jumping up to the top.
    current = view._tree.currentItem().data(0, _GROUP_ROLE)
    assert isinstance(current, gallery.LoraGroup)


def test_deleting_a_folder_returns_to_the_most_recent_one_still_there(qtbot, tmp_path):
    db = Database(tmp_path / "g.db")
    out = tmp_path / "output"
    out.mkdir()
    for pid, prompt in [("i1", "a cat"), ("i2", "a dog")]:  # two settings folders
        db.insert_generation(
            prompt_id=pid, workflow_name="sdxl_t2i", workflow_version="v1",
            positive_prompt=prompt,
            params_json=json.dumps({"positive_prompt": prompt, "steps": 20}),
            workflow_json="{}",
        )
        (out / f"sdxl_t2i_{pid}.png").write_bytes(b"x")
        db.update_generation(
            pid, status="completed",
            output_files=json.dumps([{"filename": f"sdxl_t2i_{pid}.png", "subfolder": ""}]),
        )
    actions = GalleryActions(db, OutputPlaces.in_one_folder(out), Trash(tmp_path / "trash"))
    view = GalleryView(db, actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    lora = _at(_image_workflow(view._tree), 0, 0)  # the (no LoRA) folder
    first_leaf, second_leaf = _at(lora, 0), _at(lora, 1)
    first_key = first_leaf.data(0, _GROUP_ROLE).key
    view._tree.setCurrentItem(first_leaf)   # visit the first settings folder
    view._tree.setCurrentItem(second_leaf)  # then the second (now current)
    _click_off(view)                        # nothing picked: Delete is the folder's
    view._confirm = lambda text: True

    view._delete_selection()  # deletes the second folder

    # Return to the first — the most recent folder we were in that still exists —
    # rather than the deleted folder's parent.
    current = view._tree.currentItem().data(0, _GROUP_ROLE)
    assert isinstance(current, gallery.SettingsGroup)
    assert current.key == first_key


def test_delete_folder_refuses_a_workflow_group(qtbot):
    actions = FakeActions()
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    view._confirm = lambda text: True

    view._delete_folders([_image_workflow(view._tree).data(0, _GROUP_ROLE)])

    assert actions.deleted == []  # only folders inside a workflow may go


def test_the_hover_rows_trash_icon_deletes_the_folder_it_names(qtbot, monkeypatch):
    # A tree row's own trash control, which reaches a delete without passing
    # through the toolbar button or any menu.
    actions = FakeActions()
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    lora = _at(_image_workflow(view._tree), 0, 0)
    _answer_confirmation(monkeypatch, QMessageBox.StandardButton.Yes)

    _click_beside_the_mark_of(qtbot, view, _key(_at(lora, 0)), which=1)

    assert {r["prompt_id"] for r in actions.deleted[0]} == {"i1"}  # that row's folder


def test_a_model_folder_deletes_all_its_settings_groups(qtbot):
    actions = FakeActions()
    # Two settings groups (cat, dog) share one model -> a single model folder.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)]
    view = GalleryView(FakeDB(rows), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    model = _at(_image_workflow(view._tree), 0)
    view._tree.setCurrentItem(model)  # a model folder, nested in the workflow
    view._confirm = lambda text: True

    view._delete_selection()

    assert {r["prompt_id"] for r in actions.deleted[0]} == {"i1", "i2"}


def test_a_lora_folder_is_deletable_and_takes_only_its_own_rows(qtbot):
    actions = FakeActions()
    # One base model, two LoRA folders (styleA, styleB). Deleting the styleA LoRA
    # folder must remove only its video, leaving the styleB sibling intact.
    rows = [_i2v_video("v1", "styleA"), _i2v_video("v2", "styleB")]
    view = GalleryView(FakeDB(rows), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    # WAN I2V -> model -> LoRA (styleA is first by appearance).
    lora = _at(_video_workflow(view._tree), 0, 0)
    assert isinstance(lora.data(0, _GROUP_ROLE), gallery.LoraGroup)
    view._tree.setCurrentItem(lora)
    view._confirm = lambda text: True

    view._delete_selection()

    assert {r["prompt_id"] for r in actions.deleted[0]} == {"v1"}


def test_undo_button_reflects_pending_action_and_triggers_undo(qtbot):
    actions = FakeActions()
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    assert not view._bank.undo.isEnabled()  # nothing to undo at rest

    _open_leaf(view)
    view._browser.apply_selection("i1", _NO_MOD)
    view._delete_selection()
    assert view._bank.undo.isEnabled()
    assert "Delete" in view._bank.undo.toolTip()

    view._bank.undo.click()
    assert actions.undo_count == 1
    assert not view._bank.undo.isEnabled()


def test_redo_button_sits_beside_undo_and_walks_back_the_other_way(qtbot):
    actions = FakeActions()
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    assert not view._bank.redo.isEnabled()  # nothing undone, so nothing to redo
    assert view._bank.redo.toolTip() == "Nothing to redo"

    _open_leaf(view)
    view._browser.apply_selection("i1", _NO_MOD)
    view._delete_selection()
    view._bank.undo.click()

    assert view._bank.redo.isEnabled()
    assert "Delete" in view._bank.redo.toolTip()
    view._bank.redo.click()
    assert actions.redo_count == 1
    assert not view._bank.redo.isEnabled()
    assert view._bank.undo.isEnabled()


def test_ctrl_shift_z_redoes_where_ctrl_z_undoes(qtbot, monkeypatch):
    actions = FakeActions()
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), actions=actions)
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(view, "_gallery_owns_keys", lambda **_kw: True)
    _open_leaf(view)
    view._browser.apply_selection("i1", _NO_MOD)
    view._delete_selection()

    ctrl = Qt.KeyboardModifier.ControlModifier
    view.eventFilter(view, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Z, ctrl))
    assert (actions.undo_count, actions.redo_count) == (1, 0)

    view.eventFilter(view, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Z,
                                     ctrl | Qt.KeyboardModifier.ShiftModifier))
    assert (actions.undo_count, actions.redo_count) == (1, 1)


def test_delete_then_undo_through_the_view_round_trips(qtbot, tmp_path):
    db = Database(tmp_path / "g.db")
    output_dir = tmp_path / "output"
    db.insert_generation(
        prompt_id="i1", workflow_name="sdxl_t2i", workflow_version="v002",
        params_json=json.dumps({"steps": 50}), workflow_json="{}",
    )
    file_path = output_dir / "sdxl_t2i_i1.png"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"img")
    db.update_generation(
        "i1", status="completed",
        output_files=json.dumps([{"filename": "sdxl_t2i_i1.png", "subfolder": ""}]),
    )
    actions = GalleryActions(db, OutputPlaces.in_one_folder(output_dir), Trash(tmp_path / "trash"))
    view = GalleryView(db, actions=actions)
    qtbot.addWidget(view)
    view.refresh()

    _open_leaf(view)
    view._browser.apply_selection("i1", _NO_MOD)
    view._delete_selection()
    assert db.get_generation("i1") is None
    assert not file_path.exists()

    view._undo()
    assert db.get_generation("i1") is not None
    assert file_path.exists()


def test_a_delete_can_let_go_of_the_files_it_is_about_to_move(qtbot):
    # The app holding a file open is what used to fail its own delete: Windows
    # refuses to move one. Attached to the actions rather than to any one caller,
    # so it covers every delete there is — a picked tile, a folder, a rejected
    # experiment, a slideshow's Up key.
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    assert view._actions._environment.release_files == view._release_held_media


def test_releasing_held_media_clears_a_pane_under_the_one_in_front(qtbot, tmp_path):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    doomed = tmp_path / "doomed.png"
    doomed.write_bytes(b"x")
    covered = view._info_tabs.current_config_panel()
    covered._preview.show_image(doomed)
    view._info_tabs._add_subtab()  # a second tab takes the front

    view._release_held_media([doomed])

    assert not covered._preview.is_showing_any([doomed])


def test_releasing_held_media_reaches_an_open_slideshow(qtbot, tmp_path):
    # Its Up key condemns the very item it's playing — the file it holds open.
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    view._slideshows._slideshow = MagicMock()

    view._release_held_media([tmp_path / "clip.mp4"])

    # With the paths, not merely called: handing the slideshow an empty list releases
    # nothing, and Windows then refuses to move the file the delete is about.
    view._slideshows.showing.release_media.assert_called_once_with([tmp_path / "clip.mp4"])


def test_pressing_delete_after_clicking_a_thumbnail_removes_it(qtbot, tmp_path):
    view, db, file_path = _shown_view_with_one_image(qtbot, tmp_path)
    _open_leaf(view)
    thumb = view._browser._thumb_widgets["i1"]

    qtbot.mouseClick(thumb, Qt.MouseButton.LeftButton)  # select, the way a user does
    qtbot.keyClick(thumb, Qt.Key.Key_Delete)            # the event filter catches it

    assert db.get_generation("i1") is None
    assert not file_path.exists()


def test_delete_works_with_gallery_as_the_central_widget(qtbot, tmp_path):
    # Mirror the real app: the gallery is the window's central widget, and the
    # app-wide Delete key filter must still reach it.
    db = Database(tmp_path / "g.db")
    out = tmp_path / "output"
    out.mkdir()
    db.insert_generation(
        prompt_id="i1", workflow_name="sdxl_t2i", workflow_version="v1",
        positive_prompt="a cat",
        params_json=json.dumps({"positive_prompt": "a cat", "steps": 20}),
        workflow_json="{}",
    )
    (out / "sdxl_t2i_i1.png").write_bytes(b"x")
    db.update_generation(
        "i1", status="completed",
        output_files=json.dumps([{"filename": "sdxl_t2i_i1.png", "subfolder": ""}]),
    )
    actions = GalleryActions(db, OutputPlaces.in_one_folder(out), Trash(tmp_path / "trash"))
    view = GalleryView(db, actions=actions)
    win = QMainWindow()
    win.setCentralWidget(view)
    qtbot.addWidget(win)
    with qtbot.waitExposed(win):
        win.show()
    view.refresh()
    view._tree.setCurrentItem(_at(_image_workflow(view._tree), 0, 0, 0))
    view._browser.apply_selection("i1", _NO_MOD)

    qtbot.keyClick(view, Qt.Key.Key_Delete)

    assert db.get_generation("i1") is None


def test_delete_after_a_click_in_the_info_pane_wipes_no_thumbnail(qtbot, tmp_path):
    # The grid and an editable config form are visible together, so the app-wide
    # Delete/Undo filter must disarm while a config control has focus — its combos
    # and buttons aren't text fields, so without this it would wipe a thumbnail.
    view, db, _file_path = _shown_view_with_one_image(qtbot, tmp_path)
    _open_leaf(view)
    with qtbot.waitActive(view):
        view.activateWindow()
    thumb = view._browser._thumb_widgets["i1"]
    gestures.click(thumb, thumb.rect().center())
    form = view._info_tabs.current_config_panel()._param_form
    header = next(iter(form._sections.values()))._header
    # The row saying what the image shows sits above the form, so in a window
    # this short the first section header hangs below the fold, where a click
    # would land on nothing and leave the focus where it was.
    _scroll_into_view(header)
    gestures.click(header, header.rect().center())

    gestures.press_key(view, Qt.Key.Key_Delete)

    assert db.get_generation("i1") is not None


def test_delete_works_without_a_thumbnail_holding_focus(qtbot, tmp_path):
    # The real-app failure: a selected item, but focus is on the tree (or nowhere
    # in the gallery), so a focus-scoped handler never fired. The app-wide filter
    # must still delete because the Gallery tab is the one on screen.
    view, db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    _open_leaf(view)
    view._browser.apply_selection("i1", _NO_MOD)

    qtbot.keyClick(view, Qt.Key.Key_Delete)

    assert db.get_generation("i1") is None


def test_insert_key_also_deletes(qtbot, tmp_path):
    # Some keyboards send Insert where Delete is expected; the gallery treats
    # both the same (see the event filter).
    view, db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    _open_leaf(view)
    view._browser.apply_selection("i1", _NO_MOD)

    qtbot.keyClick(view, Qt.Key.Key_Insert)

    assert db.get_generation("i1") is None


def test_ctrl_z_undoes_a_delete(qtbot, tmp_path):
    view, db, file_path = _shown_view_with_one_image(qtbot, tmp_path)
    _open_leaf(view)
    view._browser.apply_selection("i1", _NO_MOD)
    qtbot.keyClick(view, Qt.Key.Key_Delete)
    assert db.get_generation("i1") is None

    qtbot.keyClick(view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)

    assert db.get_generation("i1") is not None
    assert file_path.exists()


def test_delete_on_a_tree_folder_removes_it_via_the_keyboard(qtbot, tmp_path):
    view, db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    _open_leaf(view)  # the settings folder is the current tree item
    view._confirm = lambda text: True

    qtbot.keyClick(view._tree, Qt.Key.Key_Delete)

    assert db.get_generation("i1") is None


def test_delete_is_ignored_when_the_gallery_tab_is_not_showing(qtbot, tmp_path):
    view, db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    _open_leaf(view)
    view._browser.apply_selection("i1", _NO_MOD)
    view.hide()  # another tab is active

    qtbot.keyClick(view, Qt.Key.Key_Delete)

    assert db.get_generation("i1") is not None  # the gallery doesn't grab the key


def test_delete_passes_through_to_a_focused_text_field(qtbot, tmp_path, monkeypatch):
    view, db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    _open_leaf(view)
    view._browser.apply_selection("i1", _NO_MOD)
    # A text field (the search, say) has focus: Delete edits text.
    editor = QLineEdit()
    monkeypatch.setattr(
        "origenerator.gui.gallery_view.QApplication.focusWidget", lambda: editor
    )

    qtbot.keyClick(view, Qt.Key.Key_Delete)

    assert db.get_generation("i1") is not None
