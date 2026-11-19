from __future__ import annotations

from PySide6.QtCore import QPoint

from origenerator.gui.corner_buttons import ENHANCE, STAR, TRASH
from origenerator.gui.gallery_view import GalleryView
from tests.gallery_view_support import (
    _REROLL_HISTORY,
    _generating_tile,
    _menu_offering,
    _new_tile,
    _reroll_client,
    _seeded_db,
    _select_first_leaf,
)


def _a_run_on_its_way(qtbot, tmp_path):
    client = _reroll_client()
    db = _seeded_db(tmp_path, seed=7)
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _new_tile(view).add_requested.emit()
    return view, db, client, view._live_jobs[key].prompt_id


def test_the_star_on_a_tile_being_generated_favorites_the_item_at_once(qtbot, tmp_path):
    view, db, _client, prompt_id = _a_run_on_its_way(qtbot, tmp_path)

    _generating_tile(view).control_triggered.emit(STAR)

    assert db.get_generation(prompt_id)["starred"] == 1
    assert _generating_tile(view)._controls._star.toolTip() == "Unfavorite this image", (
        "the star on the tile itself fills, in the item's own folder as in Latest")


def test_the_tile_being_generated_wears_the_name_the_item_keeps(qtbot, tmp_path):
    view, _db, client, prompt_id = _a_run_on_its_way(qtbot, tmp_path)
    shown = _generating_tile(view)._name.text()

    client.job_completed.emit(prompt_id, _REROLL_HISTORY)

    assert shown != ""
    assert shown == view._item_names.of(prompt_id)


def test_the_trash_on_a_tile_being_generated_lets_the_run_finish_into_trash(qtbot, tmp_path):
    view, db, client, prompt_id = _a_run_on_its_way(qtbot, tmp_path)

    _generating_tile(view).control_triggered.emit(TRASH)

    assert db.get_generation(prompt_id)["status"] == "running", "the run goes on"
    assert _generating_tile(view) is None, "the item leaves the gallery, as a trashed item does"

    client.job_completed.emit(prompt_id, _REROLL_HISTORY)

    assert db.get_generation(prompt_id) is None
    assert db.asked_when_finished() == []
    assert prompt_id in {row["prompt_id"] for row in db.list_trashed()}


def test_the_enhance_on_an_image_being_generated_enhances_it_once_it_finishes(qtbot, tmp_path):
    view, db, client, prompt_id = _a_run_on_its_way(qtbot, tmp_path)
    asked = []
    view.enhance.enhance_items = asked.append

    _generating_tile(view).control_triggered.emit(ENHANCE)
    assert asked == [], "an image not yet made has nothing to enhance"
    assert _generating_tile(view)._controls._blink.isActive(), (
        "the plus blinks yellow while the enhancement waits for the image")

    client.job_completed.emit(prompt_id, _REROLL_HISTORY)

    assert asked == [[prompt_id]]
    assert db.asked_when_finished() == []


def test_a_wish_left_by_a_run_that_finished_while_the_app_was_closed_is_carried_out(
        qtbot, tmp_path):
    view, db, _client, prompt_id = _a_run_on_its_way(qtbot, tmp_path)
    db.ask_when_finished(prompt_id, "enhance")
    db.update_generation(prompt_id, status="completed")
    asked = []
    view.enhance.enhance_items = asked.append

    view.carry_out_when_finished()

    assert asked == [[prompt_id]]


def test_the_right_click_menus_enhance_and_delete_wait_for_the_item_like_its_corner_icons(
        qtbot, tmp_path, monkeypatch):
    view, db, _client, prompt_id = _a_run_on_its_way(qtbot, tmp_path)
    _menu_offering(monkeypatch, pick="Enhance")
    view.generation_menu([prompt_id], QPoint(0, 0))
    assert db.get_generation(prompt_id)["enhance_requested_at"]

    _menu_offering(monkeypatch, pick="Delete")
    view.generation_menu([prompt_id], QPoint(0, 0))
    row = db.get_generation(prompt_id)
    assert row["trash_requested_at"]
    assert row["status"] == "running"
    assert _generating_tile(view) is None
