from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image
from PyQt6.QtCore import (
    Qt,
)

from origenerator import (
    action_settings,
    evolver_export,
)
from origenerator.db import Database, NewGeneration
from origenerator.gallery.shapes import PORTRAIT
from origenerator.gui import (
    combine_controller,
)
from origenerator.gui import gallery_view as gallery_view_module
from origenerator.gui.folder_modify_tile import FolderModifyTile
from origenerator.gui.gallery_view import _GROUP_ROLE, GalleryView
from origenerator.gui.generating_tile import GeneratingTile
from origenerator.gui.item_tile import ItemTile
from origenerator.gui.new_tile import NewTile
from origenerator.item_shape import base_of
from origenerator.prompt_edit import work_out
from tests.gallery_view_support import (
    _REROLL_HISTORY,
    _SDXL,
    FakeDB,
    _alls,
    _at,
    _frame_shown,
    _front_panel,
    _genau_view,
    _generate_in_current_tab,
    _generating_tile,
    _image,
    _image_workflow,
    _new_tile,
    _on_screen,
    _open_leaf,
    _png_bytes,
    _reroll_client,
    _row,
    _running_reroll,
    _search_for,
    _seeded_db,
    _select_first_leaf,
    _selected_folder,
    _tile_kinds_in_order,
)

pytestmark = pytest.mark.usefixtures("_stub_preview_resolution")



def test_leaf_shows_add_tile_when_client_present(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert _new_tile(view) is not None


def test_main_view_reflows_to_fill_extra_width(qtbot):
    rows = [_image(f"i{n}", "a cat", 50, n) for n in range(1, 9)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)

    layout = view._scroll.widget().layout()
    assert layout.heightForWidth(2000) < layout.heightForWidth(300)


def test_add_tile_leads_the_folders_images(qtbot):
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    layout = view._scroll.widget().layout()
    kinds = [type(layout.itemAt(index).widget()) for index in range(layout.count())]
    assert kinds.index(NewTile) < kinds.index(ItemTile)


def test_leaf_has_no_add_tile_without_a_client(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert _new_tile(view) is None


def test_no_add_tile_for_unknown_workflow(qtbot):
    rows = [_row("x1", "unknown", {"seed": 1}, "x1.png")]
    view = GalleryView(FakeDB(rows), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert _new_tile(view) is None


def test_no_add_tile_for_an_import_that_never_named_its_starting_image(qtbot):
    rows = [_row("imp", "image_enhance", {"seed": 1}, "imp.png", source="imported")]
    view = GalleryView(FakeDB(rows), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert _new_tile(view) is None


def test_add_tile_shows_for_imported_with_known_workflow(qtbot):
    rows = [_row("imp", "sdxl_t2i", {"seed": 1}, "imp.png", source="imported")]
    view = GalleryView(FakeDB(rows), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert _new_tile(view) is not None


def test_reroll_of_sparse_import_fills_params_from_defaults(qtbot, tmp_path):
    db = Database(tmp_path / "test.db")
    db.insert_generation(NewGeneration(
        prompt_id="imp", workflow_name="sdxl_t2i", workflow_version="imported",
        positive_prompt="a cat", seed=1,
        params_json=json.dumps({"positive_prompt": "a cat", "seed": 1}),
        workflow_json="{}", source="imported",
    ))
    db.update_generation("imp", status="completed",
                         output_files=json.dumps([{"filename": "imp.png", "subfolder": ""}]))
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    _new_tile(view).add_requested.emit()

    job = view._live_jobs[key]
    assert job.params["checkpoint"] == _SDXL.default_params()["checkpoint"]
    assert job.params["seed"] != 1
    client.submit_job.assert_called_once_with(job.payload, job.prompt_id)


def test_clicking_add_starts_a_reroll_with_a_new_seed(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    _new_tile(view).add_requested.emit()

    assert key in view._live_jobs
    job = view._live_jobs[key]
    assert job.workflow.name == "sdxl_t2i"
    assert job.params["seed"] != 7
    client.submit_job.assert_called_once_with(job.payload, job.prompt_id)


def test_starting_a_reroll_grays_the_plus_and_gives_the_run_a_tile_after_the_request_tile(
        qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    _new_tile(view).add_requested.emit()

    assert not _new_tile(view).isEnabled()
    kinds = _tile_kinds_in_order(view)
    assert kinds.index(FolderModifyTile) == kinds.index(NewTile) + 1
    assert kinds.index(GeneratingTile) == kinds.index(FolderModifyTile) + 1


def _press_at(qtbot, view, spot):
    container = view._scroll.widget()
    target = container.childAt(spot) or container
    qtbot.mouseClick(target, Qt.MouseButton.LeftButton, pos=target.mapFrom(container, spot))


def test_a_second_press_where_the_runs_cancel_was_starts_no_new_run(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    _on_screen(qtbot, view, 1200, 800)
    key = _select_first_leaf(view)
    _new_tile(view).add_requested.emit()
    cancel = _generating_tile(view)._cancel
    spot = cancel.mapTo(view._scroll.widget(), cancel.rect().center())

    _press_at(qtbot, view, spot)
    _press_at(qtbot, view, spot)

    assert key not in view._live_jobs
    assert client.submit_job.call_count == 1


def test_clicking_add_twice_starts_only_one_job(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    view._start_reroll(key)
    view._start_reroll(key)

    assert list(view._live_jobs) == [key]
    client.submit_job.assert_called_once()



def _request_tile(view):
    tiles = view._scroll.widget().findChildren(FolderModifyTile)
    return tiles[0] if tiles else None


def _folder_db(tmp_path, seeds=(7, 8, 9), prompt="a cat on a couch"):
    db = Database(tmp_path / "folder.db")
    for seed in seeds:
        db.insert_generation(NewGeneration(
            prompt_id=f"pic{seed}", workflow_name="sdxl_t2i",
            workflow_version=_SDXL.version, positive_prompt=prompt,
            negative_prompt="blurry", seed=seed,
            params_json=json.dumps(dict(_SDXL.default_params(), seed=seed,
                                        positive_prompt=prompt,
                                        negative_prompt="blurry")),
            workflow_json="{}",
        ))
        db.update_generation(
            f"pic{seed}", status="completed",
            output_files=json.dumps([{"filename": f"sdxl_{seed}.png", "subfolder": ""}]),
        )
    return db


def _rewritten(view, key, prompt="a dog on a couch"):
    params = dict(_SDXL.default_params(), seed=7, positive_prompt=prompt,
                  negative_prompt="blurry")
    view._on_modify_requested(key, "sdxl_t2i", params)


def test_a_folder_offers_a_request_tile_beside_its_new_tile(qtbot, tmp_path):
    view = GalleryView(_folder_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    assert _request_tile(view) is not None
    assert _new_tile(view) is not None


def test_a_folder_with_nothing_finished_in_it_has_nothing_to_request(qtbot):
    rows = [_row("run1", "sdxl_t2i", {"positive_prompt": "a cat", "seed": 1}, "x.png",
                 status="running", output_files=json.dumps([]))]
    view = GalleryView(FakeDB(rows), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    assert _request_tile(view) is None


def test_the_tile_opens_the_folders_prompt_in_a_tab_rather_than_launching(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_folder_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    _request_tile(view).clicked.emit()

    tab = view._generate_pane.current_generate_tab()
    assert tab._folder_modify.folder_key == key
    assert tab._viewport._stack.currentWidget() is tab._viewport._sheet
    client.submit_job.assert_not_called()


def test_a_request_runs_every_image_again_with_its_own_seed(qtbot, tmp_path):
    view = GalleryView(_folder_db(tmp_path, seeds=(7, 8, 9)), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    _rewritten(view, key)

    jobs = view._jobs.all_jobs
    assert sorted(job.params["seed"] for job in jobs) == [7, 8, 9]
    assert {job.params["positive_prompt"] for job in jobs} == {"a dog on a couch"}


def test_a_rewrite_never_stops_one_of_its_own_images_for_the_next(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_folder_db(tmp_path, seeds=(7, 8, 9)), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    _rewritten(view, key)

    client.interrupt.assert_not_called()
    client.submit_job.assert_called_once()


def test_the_rewrite_lands_in_one_folder_beside_the_one_it_came_from(qtbot, tmp_path):
    view = GalleryView(_folder_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    _rewritten(view, key)

    landing = set(view._jobs.jobs_by_folder)
    assert len(landing) == 1
    assert landing != {key}


def test_each_rewritten_image_is_linked_to_the_one_it_came_from(qtbot, tmp_path):
    db = _folder_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    _rewritten(view, key)

    records = db.list_requests()
    assert {r["source_prompt_id"] for r in records} == {"pic7", "pic8", "pic9"}
    assert {r["prompt_id"] for r in records} == {job.prompt_id for job in view._jobs.all_jobs}
    one = records[0]
    assert one["old_positive"] == "a cat on a couch"
    assert one["new_positive"] == "a dog on a couch"
    assert one["heard"] == ""


def test_a_rewrite_of_a_folder_that_has_gone_launches_nothing(qtbot, tmp_path):
    view = GalleryView(_folder_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    _rewritten(view, "image/sdxl_t2i/nosuchfolder")

    assert view._jobs.all_jobs == []


def test_the_folders_live_tile_stands_the_image_it_was_asked_of_behind_the_wait(
        qtbot, tmp_path):
    thumb = tmp_path / "asked_of.png"
    Image.new("RGB", (32, 24), (40, 160, 80)).save(thumb)
    db = _folder_db(tmp_path, seeds=(7,))
    db.update_generation("pic7", thumbnail_path=str(thumb))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    _rewritten(view, key)

    assert not _generating_tile(view)._image.pixmap().isNull()


def test_the_whole_batch_shows_in_the_new_folder_at_once(qtbot, tmp_path):
    view = GalleryView(_folder_db(tmp_path, seeds=(7, 8, 9)), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    _rewritten(view, key)

    queued = [job.prompt_id for job in view._jobs.all_jobs]
    assert _generating_tile(view) is not None
    in_front = view._jobs.queue_order[0]
    assert set(view._gallery_pane._inflight_tiles) == set(queued) - {in_front}
    assert len(queued) == 3


def test_the_new_folder_lists_its_images_in_the_order_the_old_one_reads(qtbot, tmp_path):
    db = _folder_db(tmp_path, seeds=(7, 8, 9))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    was = [row["seed"] for row in view._tree_item_for(key).data(0, _GROUP_ROLE).rows]

    _rewritten(view, key)

    made = {job.prompt_id for job in view._jobs.all_jobs}
    now = [row["seed"] for row in db.list_generations() if row["prompt_id"] in made]
    assert was == [9, 8, 7]
    assert now == was



def test_toggling_populate_starts_populate(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    view._buttons.populate.click()

    assert view._populate.is_active(key)
    assert key in view._live_jobs
    client.submit_job.assert_called_once()
    assert view._buttons.populate.isChecked()


def test_populating_in_a_folder_favorites_it(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    view._buttons.populate.click()

    assert db.folder_meta_map()[key]["starred"] is True
    assert view.group_for_key(key).favorite


def test_populating_in_a_favorite_folder_leaves_it_a_favorite(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_favorite(key)

    view._buttons.populate.click()

    assert db.folder_meta_map()[key]["starred"] is True
    assert view.group_for_key(key).favorite


def test_populate_relaunches_when_a_variation_finishes(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_populate(True)
    job = view._live_jobs[key]

    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)

    assert client.submit_job.call_count == 2
    assert view._populate.is_active(key)
    assert key in view._live_jobs


def test_turning_populate_on_in_a_second_folder_ends_it_in_the_first(qtbot, tmp_path):
    client = _reroll_client()
    db = _seeded_db(tmp_path)
    db.insert_generation(NewGeneration(
        prompt_id="other", workflow_name="sdxl_t2i", workflow_version=_SDXL.version,
        positive_prompt="a dog", negative_prompt="", seed=9,
        params_json=json.dumps(dict(_SDXL.default_params(), seed=9,
                                    positive_prompt="a dog")),
        workflow_json="{}",
    ))
    db.update_generation("other", status="completed",
                         output_files=json.dumps([{"filename": "b.png", "subfolder": ""}]))
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    settings = _at(_image_workflow(view._tree), 0, 0)
    first = _at(settings, 0).data(0, _GROUP_ROLE).key
    view._tree.setCurrentItem(_at(settings, 0))
    view._toggle_populate(True)

    view._tree.setCurrentItem(_at(settings, 1))
    view._toggle_populate(True)
    second = _selected_folder(view)

    assert view._populate.is_active(second)
    assert not view._populate.is_active(first)
    assert view._buttons.populate.isChecked()


def test_toggling_populate_off_stops_populate(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_populate(True)
    job = view._live_jobs[key]

    view._toggle_populate(False)
    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)

    assert client.submit_job.call_count == 1
    assert not view._populate.is_active(key)


def test_populate_stops_when_a_variation_fails(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_populate(True)
    job = view._live_jobs[key]

    client.job_error.emit(job.prompt_id, "boom")

    assert not view._populate.is_active(key)
    assert client.submit_job.call_count == 1


def test_cancelling_a_reroll_keeps_populate_on_and_tries_another_seed(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_populate(True)
    canceled = view._live_jobs[key].prompt_id

    view._cancel_reroll(key)

    assert view._populate.is_active(key)
    assert view._buttons.populate.isChecked()
    assert client.submit_job.call_count == 2
    assert view._live_jobs[key].prompt_id != canceled


def test_cancelling_an_populate_folders_job_by_name_keeps_populate_going(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_populate(True)
    canceled = view._live_jobs[key].prompt_id

    view._cancel_job(canceled)

    assert view._populate.is_active(key)
    assert client.submit_job.call_count == 2
    assert view._live_jobs[key].prompt_id != canceled


def test_a_tab_watching_populate_follows_it_onto_the_next_seed(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_populate(True)
    _generating_tile(view).selected.emit()
    tab = view._generate_pane.current_generate_tab()

    tab._cancel_btn.click()
    client.preview_image.emit(view._live_jobs[key].prompt_id, _png_bytes())

    assert tab.watched_key() == key
    assert _frame_shown(tab._viewport, _png_bytes())


def test_only_the_populate_toggle_ends_populate_not_a_string_of_cancels(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_populate(True)

    for _ in range(3):
        view._cancel_reroll(key)
    assert view._populate.is_active(key)
    assert client.submit_job.call_count == 4

    view._toggle_populate(False)

    assert not view._populate.is_active(key)


def _folder_tab(view, db):
    row = db.get_generation("orig")
    view._generate_pane.load_selection(row, [row])
    return view._generate_pane.current_generate_tab()


def test_populate_rewords_the_cancel_hover_in_all_three_panes(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    _folder_tab(view, db)

    view._toggle_populate(True)

    next_seed = "Throw away this seed and start the next"
    assert _generating_tile(view)._cancel.text() == "Cancel"
    assert _generating_tile(view)._cancel.toolTip() == next_seed
    assert [row._cancel.text() for row in view._queue.rows()] == ["Cancel"]
    assert [row._cancel.toolTip() for row in view._queue.rows()] == [next_seed]
    assert view._generate_pane.current_generate_tab()._cancel_btn.toolTip() == next_seed


def test_turning_populate_off_hovers_a_plain_cancel_again_with_the_run_still_in_flight(
        qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _folder_tab(view, db)
    view._toggle_populate(True)

    view._toggle_populate(False)

    assert key in view._live_jobs
    plain = "Cancel this generation"
    assert _generating_tile(view)._cancel.toolTip() == plain
    assert [row._cancel.toolTip() for row in view._queue.rows()] == [plain]
    assert view._generate_pane.current_generate_tab()._cancel_btn.toolTip() == plain


def test_the_tiles_new_seed_lights_the_tab_showing_that_folder(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    _folder_tab(view, db)

    _new_tile(view).add_requested.emit()

    tab = view._generate_pane.current_generate_tab()
    job = next(iter(view._live_jobs.values()))
    assert tab._cancel_btn.isHidden() is False
    assert tab.launched_runs() == [job.origin]


def test_populate_lights_the_tab_showing_that_folder_too(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _folder_tab(view, db)

    view._toggle_populate(True)
    first = view._live_jobs[key]
    assert view._generate_pane.current_generate_tab().launched_runs() == [first.origin]

    client.job_completed.emit(first.prompt_id, _REROLL_HISTORY)

    tab = view._generate_pane.current_generate_tab()
    assert tab._cancel_btn.isHidden() is False
    assert tab.launched_runs() == [view._live_jobs[key].origin]


def test_populate_opens_no_tabs(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    view._toggle_populate(True)
    for _ in range(3):
        client.job_completed.emit(view._live_jobs[key].prompt_id, _REROLL_HISTORY)

    assert view._generate_pane.count() == 1
    tab = view._generate_pane.current_generate_tab()
    assert tab.displayed_row()["prompt_id"] == "orig"

    landed = next(r for r in db.list_generations() if r["status"] == "completed")
    view._on_thumbnail_clicked(landed["prompt_id"])

    assert view._generate_pane.count() == 1


def test_populate_leaves_the_open_tabs_preview_alone(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    tab = _folder_tab(view, db)
    showing = tab._displayed_row
    tab._viewport.show_frame = MagicMock()
    tab._viewport.show_media = MagicMock()

    view._toggle_populate(True)
    job = view._live_jobs[key]
    client.preview_image.emit(job.prompt_id, b"a frame")
    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)

    tab._viewport.show_frame.assert_not_called()
    tab._viewport.show_media.assert_not_called()
    assert tab._displayed_row is showing
    assert view._selected_reroll_key is None


def test_watching_populate_in_the_pane_carries_on_to_the_next_variation(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_populate(True)
    _generating_tile(view).selected.emit()
    tab = view._generate_pane.current_generate_tab()
    tab._viewport.show_frame = MagicMock()

    client.job_completed.emit(view._live_jobs[key].prompt_id, _REROLL_HISTORY)
    client.preview_image.emit(view._live_jobs[key].prompt_id, b"the next one")

    assert view._selected_reroll_key == key
    tab._viewport.show_frame.assert_called_with(b"the next one")


def test_populate_ending_lets_the_pane_go(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_populate(True)
    _generating_tile(view).selected.emit()
    client.job_completed.emit(view._live_jobs[key].prompt_id, _REROLL_HISTORY)

    view._toggle_populate(False)
    view._cancel_reroll(key)

    assert view._selected_reroll_key is None


def test_a_tab_on_other_settings_does_not_claim_the_tiles_launch(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    tab = _folder_tab(view, db)
    tab._param_form.set_values({"positive_prompt": "an entirely different subject"})

    _new_tile(view).add_requested.emit()

    assert view._live_jobs
    assert tab._cancel_btn.isHidden() is True
    assert tab._generating is False


def test_a_run_no_open_tab_is_for_opens_one_of_its_own(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    parked = _folder_tab(view, db)
    parked._param_form.set_values({"positive_prompt": "an entirely different subject"})

    _new_tile(view).add_requested.emit()

    opened = view._generate_pane.current_generate_tab()
    assert opened is not parked
    assert opened.watched_key() == key
    assert parked.watched_key() is None


def test_the_tab_opened_on_the_tiles_run_is_kept(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    parked = _folder_tab(view, db)
    parked._param_form.set_values({"positive_prompt": "an entirely different subject"})

    _new_tile(view).add_requested.emit()

    assert view._generate_pane._preview_tab is None


def test_populate_toggle_greys_off_a_settings_leaf_but_stays_on_screen(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert not view._buttons.populate.isHidden()
    assert view._buttons.populate.isEnabled()

    view._tree.setCurrentItem(_image_workflow(view._tree))

    assert not view._buttons.populate.isHidden()
    assert not view._buttons.populate.isEnabled()
    assert view._buttons.populate.toolTip() == (
        "Populate works in a leaf folder, where every item shares its settings. "
        "Open one to use it.")


def test_populate_greyed_on_a_leaf_with_no_comfyui_says_so(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=None)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    assert not view._buttons.populate.isEnabled()
    assert view._buttons.populate.toolTip() == (
        "Populate needs ComfyUI, and Origenerator is not connected to it.")


def test_the_switchs_tip_takes_you_to_whichever_folder_populate_runs_in(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_populate(True)
    view._tree.setCurrentItem(_image_workflow(view._tree))
    assert _selected_folder(view) != key

    view._buttons.populate_tip.link_activated.emit("populate")

    assert _selected_folder(view) == key



def test_generate_launches_a_reroll_in_the_configs_existing_folder(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    orig_folder = _select_first_leaf(view)
    view._tree.setCurrentItem(_image_workflow(view._tree))

    folder = _generate_in_current_tab(view, positive_prompt="a cat", seed=123)

    assert folder == orig_folder
    assert folder in view._live_jobs
    assert _selected_folder(view) == folder
    assert view._selected_reroll_key == folder


def test_generate_navigates_to_a_brand_new_folder_immediately(qtbot, tmp_path):
    db = _seeded_db(tmp_path, seed=7)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    before = {base_of(key) for key in view._item_by_key}

    folder = _generate_in_current_tab(view, positive_prompt="a totally new prompt", seed=5)

    assert folder not in before
    assert view._tree_item_for(folder) is not None
    assert folder in view._live_jobs
    assert _selected_folder(view) == folder



def test_a_tabs_go_to_folder_opens_the_folder_its_settings_have_made(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    folder = _select_first_leaf(view)
    tab = view._generate_pane.current_generate_tab()
    tab.prefill("sdxl_t2i",
                  dict(_SDXL.default_params(), seed=7, positive_prompt="a cat"))
    view._tree.setCurrentItem(_image_workflow(view._tree))

    view._generate_pane.folder_requested.emit(tab.settings_folder_key())

    assert _selected_folder(view) == folder


def test_a_tabs_go_to_folder_puts_a_running_search_away(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    tab = view._generate_pane.current_generate_tab()
    tab.prefill("sdxl_t2i",
                  dict(_SDXL.default_params(), seed=7, positive_prompt="a cat"))
    _search_for(view, "cat")

    view._generate_pane.folder_requested.emit(tab.settings_folder_key())

    assert view._search.field.text() == ""


def test_a_run_generated_with_a_request_typed_on_its_tab_is_recorded_as_one(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view._on_thumbnail_clicked("orig")
    tab = view._generate_pane.current_generate_tab()
    view._voice.requests._wait_for_the_graphics_card = lambda comfyui, holder, **settings: True
    view._voice.requests._work_out = lambda positive, negative, words, **_: work_out(
        positive, negative, words, ask=lambda p, n, r, known: ("two cats", n, "Two cats."))
    exchange = tab._param_form.request_exchange()
    qtbot.keyClicks(exchange._line, "two cats")
    qtbot.keyClick(exchange._line, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: exchange.turns() == [("two cats", "Two cats.")], timeout=5000)

    view._on_generate_requested("sdxl_t2i", [{"seed": 9, "positive_prompt": "two cats"}])

    (job,) = view._live_jobs.values()
    record = db.get_request(job.prompt_id)
    assert (record["asked"], record["heard"], record["source_prompt_id"]) == ("two cats", "", "orig")
    assert (record["old_positive"], record["new_positive"]) == ("a cat", "two cats")
    (turn,) = db.requests.exchange_of(job.prompt_id)
    assert (turn.said, turn.answered, turn.old_positive, turn.new_positive) == (
        "two cats", "Two cats.", "a cat", "two cats")


def test_generate_under_a_turn_runs_it_records_its_request_and_leaves_the_tab_on_its_image(
        qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view._on_thumbnail_clicked("orig")
    tab = view._generate_pane.current_generate_tab()
    view._voice.requests._wait_for_the_graphics_card = lambda comfyui, holder, **settings: True
    view._voice.requests._work_out = lambda positive, negative, words, **_: work_out(
        positive, negative, words, ask=lambda p, n, r, known: ("two cats", n, "Two cats."))
    exchange = tab._param_form.request_exchange()
    qtbot.keyClicks(exchange._line, "two cats")
    qtbot.keyClick(exchange._line, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: exchange.turns() == [("two cats", "Two cats.")], timeout=5000)

    exchange.generate_asked.emit(0)

    (job,) = view._live_jobs.values()
    record = db.get_request(job.prompt_id)
    assert (record["asked"], record["source_prompt_id"], record["new_positive"]) == (
        "two cats", "orig", "two cats")
    assert tab.displayed_row()["prompt_id"] == "orig"
    assert [entry.made for entry in exchange._entries()] == [job.prompt_id]
    assert list(exchange._in_flight) == [job.prompt_id]


def test_a_run_generated_with_no_request_records_none(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view._on_thumbnail_clicked("orig")

    view._on_generate_requested("sdxl_t2i", [{"seed": 9, "positive_prompt": "a dog"}])

    (job,) = view._live_jobs.values()
    assert db.get_request(job.prompt_id) is None


def test_generate_request_over_a_duplicate_re_rolls_without_asking(qtbot, tmp_path):
    db = _seeded_db(tmp_path, seed=42)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._on_generate_requested("sdxl_t2i", [{"seed": 42, "positive_prompt": "a cat"}])

    job = next(iter(view._live_jobs.values()))
    assert job.workflow.name == "sdxl_t2i"
    assert job.params["seed"] != 42


def test_generate_from_a_tab_back_on_its_videos_own_seeds_draws_a_fresh_one(qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    db.insert_generation(NewGeneration(
        prompt_id="vid", workflow_name="wan22_i2v", workflow_version="v002",
        params_json=json.dumps({"positive_prompt": "dance", "input_image": "frame.png",
                                "noise_seed": 22, "audio_seed": 33}),
        workflow_json="{}"))
    db.update_generation("vid", status="completed", output_files=json.dumps(
        [{"filename": "vid.mp4", "subfolder": "video"}]))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    tab = _front_panel(view)
    tab._viewport.show_media = MagicMock()
    tab.show_saved_generation(db.get_generation("vid"), [])
    tab._param_form.set_seed_random(False)

    tab._on_generate()

    job = next(iter(view._live_jobs.values()))
    assert job.params["noise_seed"] != 22


def test_generate_request_without_a_duplicate_launches_straight_away(qtbot, tmp_path):
    db = _seeded_db(tmp_path, seed=42)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._on_generate_requested("sdxl_t2i", [{"seed": 999, "positive_prompt": "a novel prompt"}])

    job = next(iter(view._live_jobs.values()))
    assert job.params["seed"] == 999


def test_a_press_for_several_puts_every_one_in_its_folder_at_once(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    tab = view._generate_pane.current_generate_tab()
    tab._workflow_dropdown.setCurrentIndex(tab._workflow_dropdown.findData("sdxl_t2i"))
    tab._how_many.set_how_many(4)

    tab._on_generate()

    (folder,) = view._jobs.jobs_by_folder.values()
    assert len({job.params["seed"] for job in folder}) == 4
    client.interrupt.assert_not_called()
    assert len(tab.launched_runs()) == 4
    assert tab._generate_btn.isEnabled() is False



def test_the_genau_lane_runs_looping_settings(qtbot, tmp_path, monkeypatch):
    view = _genau_view(qtbot, tmp_path)

    view._combine.generate_category("img", "alpha", action_settings.GENAU)

    job = next(iter(view._live_jobs.values()))
    assert job.workflow.name == "wan22_flf2v_loop"
    assert job.params["input_image"] == "sdxl_pick.png [output]"


def test_the_view_asks_the_video_lane_unless_told_otherwise(qtbot, tmp_path, monkeypatch):
    view = _genau_view(qtbot, tmp_path)
    asked = []

    def spy(category, candidates, intent=action_settings.VIDEO):
        asked.append(intent)
        return "vid"

    monkeypatch.setattr(combine_controller.action_settings, "most_used_video", spy)

    view._combine.generate_category("img", "dancing")
    view._combine.generate_category("img", "dancing", action_settings.GENAU)

    assert asked == [action_settings.VIDEO, action_settings.GENAU]


def test_a_pressed_generate_leaves_its_clip_in_the_gallery(qtbot, tmp_path, monkeypatch):
    view = _genau_view(qtbot, tmp_path)
    monkeypatch.setattr(gallery_view_module.gallery, "resolve_preview",
                        lambda row, out: (Path("C:/out/flf2v_loop_1.mp4"), "video"))
    sent = []
    monkeypatch.setattr(evolver_export, "export_video",
                        lambda src, dest, funscript=None: sent.append(src))

    view._combine.generate_category("img", "alpha", action_settings.GENAU)
    job = next(iter(view._live_jobs.values()))
    assert view._db.get_generation(job.prompt_id)["genau_requested_at"] is None

    view._on_reroll_finished("k", "loop")
    assert sent == []
    assert view._db.get_generation("loop")["genau_exported_at"] is None


def test_a_tabs_generate_goes_off_the_moment_its_folder_is_making_one(qtbot, tmp_path):
    db = _seeded_db(tmp_path, seed=42)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    tab = view._generate_pane.current_generate_tab()
    tab._workflow_dropdown.setCurrentIndex(tab._workflow_dropdown.findData("sdxl_t2i"))
    assert tab._generate_btn.isEnabled() is True
    config = tab.current_config()

    view._on_generate_requested(config.workflow_name, [config.params])

    assert tab._generate_btn.isEnabled() is False


def test_a_second_press_into_a_folder_already_making_one_makes_nothing(qtbot, tmp_path):
    db = _seeded_db(tmp_path, seed=42)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    tab = view._generate_pane.current_generate_tab()
    tab._workflow_dropdown.setCurrentIndex(tab._workflow_dropdown.findData("sdxl_t2i"))
    config = tab.current_config()

    view._on_generate_requested(config.workflow_name, [config.params])
    view._on_generate_requested(config.workflow_name, [config.params])

    assert len(view._jobs.all_jobs) == 1


def test_only_a_settings_folder_has_generations_to_rewrite(qtbot, tmp_path):
    view = GalleryView(_folder_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    assert GalleryView._folder_modify_rows(_image_workflow(view._tree).data(0, _GROUP_ROLE)) == []


def test_the_tile_counts_a_run_for_every_image_with_or_without_a_thumbnail(qtbot, tmp_path):
    view = GalleryView(_folder_db(tmp_path, seeds=(7, 8, 9)), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    _request_tile(view).clicked.emit()

    tab = view._generate_pane.current_generate_tab()
    assert tab._folder_modify.count == 3


def test_opening_a_folders_prompt_in_a_tab_puts_the_run_down_as_the_selection(qtbot, tmp_path):
    view = GalleryView(_folder_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _running_reroll(view)
    assert view._selected_reroll_key is not None

    _request_tile(view).clicked.emit()

    assert view._selected_reroll_key is None


def test_a_rewrite_that_comfyui_refuses_for_one_image_still_sends_the_rest(qtbot, tmp_path):
    client = _reroll_client()
    sent = []

    def refusing_the_first(payload, prompt_id):
        sent.append(prompt_id)
        if len(sent) == 1:
            raise ConnectionError("made-up refusal")
        return prompt_id

    client.submit_job = refusing_the_first
    db = _folder_db(tmp_path, seeds=(7, 8, 9))
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    _rewritten(view, key)

    assert len(db.list_requests()) == 2


def test_a_rewrite_of_a_sparsely_recorded_image_keeps_its_own_seed_not_the_tabs(qtbot, tmp_path):
    db = Database(tmp_path / "sparse.db")
    db.insert_generation(NewGeneration(
        prompt_id="sparse", workflow_name="sdxl_t2i", workflow_version=_SDXL.version,
        positive_prompt="a cat", negative_prompt="", seed=5,
        params_json=json.dumps({"positive_prompt": "a cat"}), workflow_json="{}"))
    db.update_generation("sparse", status="completed",
                         output_files=json.dumps([{"filename": "a.png", "subfolder": ""}]))
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    view._on_modify_requested(key, "sdxl_t2i", {"positive_prompt": "a dog", "seed": 123456})

    (job,) = view._jobs.all_jobs
    assert job.params["seed"] != 123456


def test_a_rewrite_lands_in_the_folder_of_its_words_on_the_workflows_defaults(qtbot, tmp_path):
    view = GalleryView(_folder_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    view._on_modify_requested(key, "sdxl_t2i", {"positive_prompt": "a dog"})

    assert list(view._jobs.jobs_by_folder) == [view.folder_key_for(
        "sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a dog"))]


def test_populate_switched_on_over_a_folder_already_making_one_stays_on(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _new_tile(view).add_requested.emit()

    view._toggle_populate(True)

    assert view._populate.is_active(key)


def test_switching_populate_off_from_another_folder_stops_it_there(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_populate(True)
    view._tree.setCurrentItem(_image_workflow(view._tree))

    view._toggle_populate(False)

    assert not view._populate.is_active(key)


def test_populate_that_could_not_launch_forgets_the_settings_it_read(qtbot, tmp_path):
    client = _reroll_client()

    def refusing(payload, prompt_id):
        raise ConnectionError("made-up refusal")

    client.submit_job = refusing
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    view._toggle_populate(True)

    assert view._populate_settings == {}


def test_populate_ending_forgets_the_settings_it_ran_on(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_populate(True)
    assert key in view._populate_settings

    view._toggle_populate(False)

    assert view._populate_settings == {}


def test_watching_populate_the_next_variation_is_the_selection_not_a_saved_item(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_populate(True)
    _generating_tile(view).selected.emit()

    client.job_completed.emit(view._live_jobs[key].prompt_id, _REROLL_HISTORY)

    assert view.selected_generation() is None
    assert view.selected_prompt_ids() == []


def test_populates_launches_are_remembered_only_while_they_can_still_finish(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_populate(True)

    view._cancel_reroll(key)

    assert view._populate_origins == {view._live_jobs[key].origin}


def test_with_populate_running_elsewhere_the_switch_leaves_the_saying_to_its_tip(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view._toggle_populate(True)
    assert view._buttons.populate.toolTip() != ""

    view._tree.setCurrentItem(_image_workflow(view._tree))

    assert view._buttons.populate.toolTip() == ""


def test_a_seed_re_roll_into_a_folder_already_making_one_starts_nothing(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    _new_tile(view).add_requested.emit()
    asked = []
    view._jobs.reroll_image_seed = lambda *args: asked.append(args)

    view._reroll_item_seed("orig", "image")

    assert asked == []


def test_a_launch_in_a_portrait_folder_is_shown_on_that_side_whichever_is_browsed(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(_alls(view._tree)["Latest"])
    params = dict(_SDXL.default_params(), positive_prompt="a tall one", width=720, height=1280)
    key = view.folder_key_for("sdxl_t2i", params)
    view._jobs.start_prepared(key, _SDXL, params)

    assert view._launched_side(key) == PORTRAIT
