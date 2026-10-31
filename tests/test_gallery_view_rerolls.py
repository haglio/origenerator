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
    act_settings,
    evolver_export,
)
from origenerator.db import Database
from origenerator.gui import (
    combine_controller,
)
from origenerator.gui import gallery_view as gallery_view_module
from origenerator.gui.folder_modify_tile import FolderModifyTile
from origenerator.gui.gallery_view import _GROUP_ROLE, GalleryView
from origenerator.gui.generating_tile import GeneratingTile
from origenerator.gui.reroll_tile import RerollTile
from origenerator.gui.thumbnail_widget import ThumbnailWidget
from origenerator.orientation import base_of
from tests.gallery_view_support import (
    _REROLL_HISTORY,
    _SDXL,
    FakeDB,
    _at,
    _frame_shown,
    _front_panel,
    _genau_view,
    _generate_in_current_tab,
    _generating_tile,
    _image,
    _image_workflow,
    _on_screen,
    _open_leaf,
    _png_bytes,
    _reroll_client,
    _reroll_tile,
    _row,
    _search_for,
    _seeded_db,
    _select_first_leaf,
    _selected_folder,
    _tile_kinds_in_order,
)

pytestmark = pytest.mark.usefixtures("_stub_preview_resolution")


# --- re-roll ("+") tile -----------------------------------------------------


def test_leaf_shows_add_tile_when_client_present(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert _reroll_tile(view) is not None


def test_main_view_reflows_to_fill_extra_width(qtbot):
    # The main view flows tiles to fill the pane: a wide pane packs more per row
    # and so is shorter than a narrow one. The old fixed 4-column grid ignored
    # the available width, so its height never changed.
    rows = [_image(f"i{n}", "a cat", 50, n) for n in range(1, 9)]  # eight tiles
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)

    layout = view._scroll.widget().layout()
    assert layout.heightForWidth(2000) < layout.heightForWidth(300)


def test_add_tile_leads_the_folders_images(qtbot):
    # Thumbnails are newest-first, so the "new variation" tile leads them rather
    # than trailing the oldest.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    view = GalleryView(FakeDB(rows), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    layout = view._scroll.widget().layout()
    kinds = [type(layout.itemAt(index).widget()) for index in range(layout.count())]
    assert kinds.index(RerollTile) < kinds.index(ThumbnailWidget)


def test_leaf_has_no_add_tile_without_a_client(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert _reroll_tile(view) is None


def test_no_add_tile_for_unknown_workflow(qtbot):
    rows = [_row("x1", "unknown", {"seed": 1}, "x1.png")]
    view = GalleryView(FakeDB(rows), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert _reroll_tile(view) is None


def test_no_add_tile_for_an_import_that_never_named_its_starting_image(qtbot):
    rows = [_row("imp", "image_enhance", {"seed": 1}, "imp.png", source="imported")]
    view = GalleryView(FakeDB(rows), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert _reroll_tile(view) is None


def test_add_tile_shows_for_imported_with_known_workflow(qtbot):
    # Re-roll works anywhere Reuse Parameters does, imports included — the
    # workflow's defaults fill in whatever sparse metadata an import lacks.
    rows = [_row("imp", "sdxl_t2i", {"seed": 1}, "imp.png", source="imported")]
    view = GalleryView(FakeDB(rows), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert _reroll_tile(view) is not None


def test_reroll_of_sparse_import_fills_params_from_defaults(qtbot, tmp_path):
    # An import keeps only sparse metadata (no checkpoint/vae); re-roll must
    # still build a valid payload by borrowing the workflow's defaults.
    db = Database(tmp_path / "test.db")
    db.insert_generation(
        prompt_id="imp", workflow_name="sdxl_t2i", workflow_version="imported",
        positive_prompt="a cat", seed=1,
        params_json=json.dumps({"positive_prompt": "a cat", "seed": 1}),  # sparse
        workflow_json="{}", source="imported",
    )
    db.update_generation("imp", status="completed",
                         output_files=json.dumps([{"filename": "imp.png", "subfolder": ""}]))
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    _reroll_tile(view).add_requested.emit()

    job = view._live_jobs[key]
    assert job.params["checkpoint"] == _SDXL.default_params()["checkpoint"]  # filled in
    assert job.params["seed"] != 1  # re-rolled
    client.submit_job.assert_called_once_with(job.payload, job.prompt_id)  # built without error


def test_clicking_add_starts_a_reroll_with_a_new_seed(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    _reroll_tile(view).add_requested.emit()

    assert key in view._live_jobs
    job = view._live_jobs[key]
    assert job.workflow.name == "sdxl_t2i"
    assert job.params["seed"] != 7  # same settings, fresh seed
    client.submit_job.assert_called_once_with(job.payload, job.prompt_id)


def test_starting_a_reroll_grays_the_plus_and_gives_the_run_a_tile_after_the_request_card(
        qtbot, tmp_path):
    # Reported: the press that started a run turned the + itself into the run,
    # with the run's Cancel where the + had been -- so on a slow app, a second
    # press on a Cancel already taken landed on the + it had turned back into,
    # and started another. The + stays put now, grayed out, and the run gets a
    # tile of its own where its image will land.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    _reroll_tile(view).add_requested.emit()

    assert not _reroll_tile(view).isEnabled()
    kinds = _tile_kinds_in_order(view)
    assert kinds.index(FolderModifyTile) == kinds.index(RerollTile) + 1
    assert kinds.index(GeneratingTile) == kinds.index(FolderModifyTile) + 1


def _press_at(qtbot, view, spot):
    """A press where a pointer would land: on whatever the pane draws at ``spot``
    now."""
    container = view._scroll.widget()
    target = container.childAt(spot) or container
    qtbot.mouseClick(target, Qt.MouseButton.LeftButton, pos=target.mapFrom(container, spot))


def test_a_second_press_where_the_runs_cancel_was_starts_no_new_run(qtbot, tmp_path):
    # Reported: Origenerator answered a Cancel so slowly that he pressed it again,
    # and the second press landed on the + the run's tile had turned back into.
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    _on_screen(qtbot, view, 1200, 800)
    key = _select_first_leaf(view)
    _reroll_tile(view).add_requested.emit()
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

    assert list(view._live_jobs) == [key]  # the second press found one running
    client.submit_job.assert_called_once()


# --- Modify (all seeds): same seeds, changed words --------------------------


def _request_card(view):
    cards = view._scroll.widget().findChildren(FolderModifyTile)
    return cards[0] if cards else None


def _folder_db(tmp_path, seeds=(7, 8, 9), prompt="a cat on a couch"):
    """A DB holding one settings folder with a completed image per seed — the
    folder a rewrite re-runs."""
    db = Database(tmp_path / "folder.db")
    for seed in seeds:
        db.insert_generation(
            prompt_id=f"pic{seed}", workflow_name="sdxl_t2i",
            workflow_version=_SDXL.version, positive_prompt=prompt,
            negative_prompt="blurry", seed=seed,
            params_json=json.dumps(dict(_SDXL.default_params(), seed=seed,
                                        positive_prompt=prompt,
                                        negative_prompt="blurry")),
            workflow_json="{}",
        )
        db.update_generation(
            f"pic{seed}", status="completed",
            output_files=json.dumps([{"filename": f"sdxl_{seed}.png", "subfolder": ""}]),
        )
    return db


def _rewritten(view, key, prompt="a dog on a couch"):
    """Press a rewrite of the folder ``key`` names, saying ``prompt`` instead."""
    params = dict(_SDXL.default_params(), seed=7, positive_prompt=prompt,
                  negative_prompt="blurry")
    view._on_modify_requested(key, "sdxl_t2i", params)


def test_a_folder_offers_a_request_card_beside_its_reroll_tile(qtbot, tmp_path):
    view = GalleryView(_folder_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    assert _request_card(view) is not None
    assert _reroll_tile(view) is not None  # the pair: new seed, and new words


def test_a_folder_with_nothing_finished_in_it_has_nothing_to_request(qtbot):
    # The rewrite reproduces the folder seed for seed, so a folder whose only row
    # is still in flight has no image to say differently yet.
    rows = [_row("run1", "sdxl_t2i", {"positive_prompt": "a cat", "seed": 1}, "x.png",
                 status="running", output_files=json.dumps([]))]
    view = GalleryView(FakeDB(rows), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    assert _request_card(view) is None


def test_the_card_opens_the_folders_prompt_in_a_tab_rather_than_launching(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_folder_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    _request_card(view).clicked.emit()

    panel = view._info_tabs.current_config_panel()
    assert panel._folder_modify.folder_key == key
    assert panel._preview._stack.currentWidget() is panel._preview._sheet
    client.submit_job.assert_not_called()  # an edit to make, not a run to start


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
    assert len(landing) == 1                 # the seeds don't split it
    assert landing != {key}                  # ...and it isn't the folder it came from


def test_each_rewritten_image_is_linked_to_the_one_it_came_from(qtbot, tmp_path):
    # Individually, not folder to folder: the link is what says which image
    # this one is the rewrite of, and it shows on the item itself.
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
    assert one["heard"] == ""  # typed, so there is nothing it was heard as


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

    # The batch's folder is on screen now; its live tile has no frame of its own
    # yet, so it shows the image the request was made of.
    assert not _generating_tile(view)._image.pixmap().isNull()


def test_the_whole_batch_shows_in_the_new_folder_at_once(qtbot, tmp_path):
    # Every run is being made, so the folder shows every run — not one card the
    # images then arrive through one at a time.
    view = GalleryView(_folder_db(tmp_path, seeds=(7, 8, 9)), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    _rewritten(view, key)

    queued = [job.prompt_id for job in view._jobs.all_jobs]
    # The one in front -- the last asked for, since each image takes the
    # machine from the one before -- is the folder's generating tile; the rest
    # each get their own card.
    assert _generating_tile(view) is not None
    in_front = view._jobs.queue_order[0]
    assert set(view._browser._inflight_cards) == set(queued) - {in_front}
    assert len(queued) == 3


def test_the_new_folder_lists_its_images_in_the_order_the_old_one_reads(qtbot, tmp_path):
    # Not merely "in some consistent order" — the same order, so laying the two
    # folders side by side is what tells you at a glance that it worked.
    db = _folder_db(tmp_path, seeds=(7, 8, 9))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    # _tree_item_for: a folder has a row per side now, and this key has no
    # side on it.
    was = [row["seed"] for row in view._tree_item_for(key).data(0, _GROUP_ROLE).rows]

    _rewritten(view, key)

    made = {job.prompt_id for job in view._jobs.all_jobs}
    # The gallery lists rows newest first, which is the order they were written in
    # reversed — so this is the order the new folder will draw them in.
    now = [row["seed"] for row in db.list_generations() if row["prompt_id"] in made]
    assert was == [9, 8, 7]
    assert now == was


# --- Auto-Generate: the folder re-roll, again and again until stopped -------


def test_toggling_auto_starts_auto_generate(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    view._bank.auto.click()  # the header's Auto toggle, switched on

    assert view._auto.is_active(key)
    assert key in view._live_jobs          # a first variation is running
    client.submit_job.assert_called_once()
    assert view._bank.auto.isChecked()


def test_auto_generating_in_a_folder_favorites_it(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    view._bank.auto.click()

    assert db.folder_meta_map()[key]["starred"] is True
    assert view.group_for_key(key).favorite


def test_auto_generating_in_a_favorite_folder_leaves_it_a_favorite(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_favorite(key)

    view._bank.auto.click()

    assert db.folder_meta_map()[key]["starred"] is True
    assert view.group_for_key(key).favorite


def test_auto_relaunches_when_a_variation_finishes(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_auto(True)
    job = view._live_jobs[key]

    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)  # the variation finishes

    assert client.submit_job.call_count == 2   # the next one was launched
    assert view._auto.is_active(key)
    assert key in view._live_jobs            # a fresh variation is running


def test_turning_auto_on_in_a_second_folder_ends_it_in_the_first(qtbot, tmp_path):
    # One folder at a time: Auto-Generate in two would take turns on the
    # machine, each waiting out the other's render.
    client = _reroll_client()
    db = _seeded_db(tmp_path)
    db.insert_generation(
        prompt_id="other", workflow_name="sdxl_t2i", workflow_version=_SDXL.version,
        positive_prompt="a dog", negative_prompt="", seed=9,
        params_json=json.dumps(dict(_SDXL.default_params(), seed=9,
                                    positive_prompt="a dog")),
        workflow_json="{}",
    )
    db.update_generation("other", status="completed",
                         output_files=json.dumps([{"filename": "b.png", "subfolder": ""}]))
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    settings = _at(_image_workflow(view._tree), 0, 0)
    first = _at(settings, 0).data(0, _GROUP_ROLE).key
    view._tree.setCurrentItem(_at(settings, 0))
    view._toggle_auto(True)

    view._tree.setCurrentItem(_at(settings, 1))
    view._toggle_auto(True)
    second = _selected_folder(view)

    assert view._auto.is_active(second)
    assert not view._auto.is_active(first)
    assert view._bank.auto.isChecked()  # the switch follows the folder in front


def test_toggling_auto_off_stops_auto_generate(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_auto(True)
    job = view._live_jobs[key]

    view._toggle_auto(False)
    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)

    assert client.submit_job.call_count == 1   # not relaunched after stop
    assert not view._auto.is_active(key)


def test_auto_stops_when_a_variation_fails(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_auto(True)
    job = view._live_jobs[key]

    client.job_error.emit(job.prompt_id, "boom")   # ComfyUI rejected it

    assert not view._auto.is_active(key)
    assert client.submit_job.call_count == 1       # did not spin on the failure


def test_cancelling_a_reroll_keeps_auto_generate_on_and_tries_another_seed(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_auto(True)
    canceled = view._live_jobs[key].prompt_id

    view._cancel_reroll(key)  # the live tile's Cancel: "not this seed", not "stop"

    assert view._auto.is_active(key)          # Auto-Generate is still on
    assert view._bank.auto.isChecked()         # and the toggle still says so
    assert client.submit_job.call_count == 2  # a fresh seed went out at once
    assert view._live_jobs[key].prompt_id != canceled


def test_cancelling_an_auto_folders_job_by_name_keeps_auto_generate_going(qtbot, tmp_path):
    # The queue row's Cancel and a config tab's, which name the run to stop.
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_auto(True)
    canceled = view._live_jobs[key].prompt_id

    view._cancel_job(canceled)

    assert view._auto.is_active(key)
    assert client.submit_job.call_count == 2
    assert view._live_jobs[key].prompt_id != canceled


def test_a_tab_watching_auto_generate_follows_it_onto_the_next_seed(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_auto(True)
    _generating_tile(view).selected.emit()
    panel = view._info_tabs.current_config_panel()

    panel._cancel_btn.click()
    client.preview_image.emit(view._live_jobs[key].prompt_id, _png_bytes())

    assert panel.watched_key() == key
    assert _frame_shown(panel._preview, _png_bytes())


def test_only_the_auto_toggle_ends_auto_generate_not_a_string_of_cancels(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_auto(True)

    for _ in range(3):  # discard seed after seed — Auto-Generate keeps offering more
        view._cancel_reroll(key)
    assert view._auto.is_active(key)
    assert client.submit_job.call_count == 4

    view._toggle_auto(False)  # the user's own word is what stops it

    assert not view._auto.is_active(key)


def _folder_tab(view, db):
    """Put the front config tab on the seeded folder's settings, as clicking that
    folder's thumbnail does — where the user is when they press the tile or Auto."""
    row = db.get_generation("orig")
    view._info_tabs.load_selection(row, [row])
    return view._info_tabs.current_config_panel()


def test_auto_rewords_the_cancel_hover_in_all_three_panes(qtbot, tmp_path):
    # Center (the folder's live tile), foot (the queue row) and right (the config
    # tab) each draw a Cancel for the run in flight. While the folder
    # auto-generates, the press throws away a seed and Auto-Generate starts
    # another, so all three hovers say so.
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    _folder_tab(view, db)

    view._toggle_auto(True)

    next_seed = "Throw away this seed and start the next"
    assert _generating_tile(view)._cancel.text() == "Cancel"
    assert _generating_tile(view)._cancel.toolTip() == next_seed
    assert [row._cancel.text() for row in view._queue.rows()] == ["Cancel"]
    assert [row._cancel.toolTip() for row in view._queue.rows()] == [next_seed]
    assert view._info_tabs.current_config_panel()._cancel_btn.toolTip() == next_seed


def test_turning_auto_off_hovers_a_plain_cancel_again_with_the_run_still_in_flight(
        qtbot, tmp_path):
    # Auto off leaves the variation in flight (it still lands), and from then on
    # that button really does stop it — so its hover must stop promising a next seed.
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _folder_tab(view, db)
    view._toggle_auto(True)

    view._toggle_auto(False)

    assert key in view._live_jobs  # the in-flight variation was left alone
    plain = "Cancel this generation"
    assert _generating_tile(view)._cancel.toolTip() == plain
    assert [row._cancel.toolTip() for row in view._queue.rows()] == [plain]
    assert view._info_tabs.current_config_panel()._cancel_btn.toolTip() == plain


def test_the_tiles_new_seed_lights_the_tab_showing_that_folder(qtbot, tmp_path):
    # Reported: pressing the tile's "New (random seed)" left the tab looking at that
    # very folder with no button to discard the run, while the pane beside it
    # streamed the frames of the run it had just started. Nothing had claimed a
    # launch that came from outside a tab.
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    _folder_tab(view, db)

    _reroll_tile(view).add_requested.emit()

    panel = view._info_tabs.current_config_panel()
    job = next(iter(view._live_jobs.values()))
    assert panel._cancel_btn.isHidden() is False
    assert panel.launched_runs() == [job.origin]


def test_auto_lights_the_tab_showing_that_folder_too(qtbot, tmp_path):
    # Same gap for the Auto toggle's own launches, and it recurs on every relaunch:
    # each new variation is claimed by the tab on that folder.
    db = _seeded_db(tmp_path)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _folder_tab(view, db)

    view._toggle_auto(True)
    first = view._live_jobs[key]
    assert view._info_tabs.current_config_panel().launched_runs() == [first.origin]

    client.job_completed.emit(first.prompt_id, _REROLL_HISTORY)  # Auto-Generate moves on

    panel = view._info_tabs.current_config_panel()
    assert panel._cancel_btn.isHidden() is False
    assert panel.launched_runs() == [view._live_jobs[key].origin]


def test_auto_generate_opens_no_tabs(qtbot, tmp_path):
    # The reported bug: Auto-Generate left running while the user browsed grew a row of
    # tabs, one per image it made. Each finished variation was loaded into whatever
    # tab was in front — the pane's resting tab, which nothing in it had asked for
    # the image, and which then stopped being blank, so the next clicked
    # generation opened a tab beside it rather than loading into it.
    db = _seeded_db(tmp_path)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    view._toggle_auto(True)
    for _ in range(3):  # three variations land while the user watches
        client.job_completed.emit(view._live_jobs[key].prompt_id, _REROLL_HISTORY)

    assert view._info_tabs.count() == 1
    panel = view._info_tabs.current_config_panel()
    # Still holding the item the folder opened on, not a variation Auto-Generate made.
    assert panel.displayed_row()["prompt_id"] == "orig"

    landed = next(r for r in db.list_generations() if r["status"] == "completed")
    view._on_thumbnail_clicked(landed["prompt_id"])

    assert view._info_tabs.count() == 1  # it filled that tab instead of forking one


def test_auto_generate_leaves_the_open_tabs_preview_alone(qtbot, tmp_path):
    # The reported bug: Auto-Generate's live frames filled the preview of whichever
    # tab was open, over the image the user had put there, and its results landed
    # there too. Auto-Generate runs while the user works on something else; the
    # folder's own live tile is where it can be watched. Even a tab on the folder
    # it runs in —
    # which does light up with its progress and Next-seed button — keeps showing
    # what the user opened it on.
    db = _seeded_db(tmp_path)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    panel = _folder_tab(view, db)
    showing = panel._displayed_row
    panel._preview.show_frame = MagicMock()
    panel._preview.show_media = MagicMock()

    view._toggle_auto(True)
    job = view._live_jobs[key]
    client.preview_image.emit(job.prompt_id, b"a frame")   # the run streams
    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)  # ...and lands

    panel._preview.show_frame.assert_not_called()
    panel._preview.show_media.assert_not_called()
    assert panel._displayed_row is showing  # still the user's own generation
    assert view._selected_reroll_key is None  # the pane was never taken over


def test_watching_auto_generate_in_the_pane_carries_on_to_the_next_variation(qtbot, tmp_path):
    # Clicking the folder's live tile is how Auto-Generate is watched full size, and
    # it is the one thing that gives the pane to Auto-Generate. Watching one variation
    # is watching what Auto-Generate does next, so the tile picked once keeps mirroring
    # across the hand-off rather than going dark after one.
    db = _seeded_db(tmp_path)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_auto(True)
    _generating_tile(view).selected.emit()  # the user points the pane at Auto-Generate
    panel = view._info_tabs.current_config_panel()
    panel._preview.show_frame = MagicMock()

    client.job_completed.emit(view._live_jobs[key].prompt_id, _REROLL_HISTORY)
    client.preview_image.emit(view._live_jobs[key].prompt_id, b"the next one")

    assert view._selected_reroll_key == key
    panel._preview.show_frame.assert_called_with(b"the next one")


def test_auto_generate_ending_lets_the_pane_go(qtbot, tmp_path):
    # The key stands for Auto-Generate while it runs, so the switch going off is what
    # ends the pane's watch — nothing else is coming to take it.
    db = _seeded_db(tmp_path)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_auto(True)
    _generating_tile(view).selected.emit()
    client.job_completed.emit(view._live_jobs[key].prompt_id, _REROLL_HISTORY)

    view._toggle_auto(False)
    view._cancel_reroll(key)  # and the variation in flight is thrown away

    assert view._selected_reroll_key is None


def test_a_tab_on_other_settings_does_not_claim_the_tiles_launch(qtbot, tmp_path):
    # The claim is by folder, so a tab parked on different settings stays idle
    # rather than showing progress for a run that has nothing to do with it.
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    panel = _folder_tab(view, db)
    panel._param_form.set_values({"positive_prompt": "an entirely different subject"})

    _reroll_tile(view).add_requested.emit()

    assert view._live_jobs                       # the run started
    assert panel._cancel_btn.isHidden() is True    # but this tab isn't its home
    assert panel._generating is False


def test_a_run_no_open_tab_is_for_opens_one_of_its_own(qtbot, tmp_path):
    # And it still ends up on screen: the press was a press for an image, so a
    # tab opens on the run rather than the pane going on showing work the press
    # had nothing to do with. The tab that was up keeps what it was holding.
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    parked = _folder_tab(view, db)
    parked._param_form.set_values({"positive_prompt": "an entirely different subject"})

    _reroll_tile(view).add_requested.emit()

    opened = view._info_tabs.current_config_panel()
    assert opened is not parked
    assert opened.watched_key() == key
    assert parked.watched_key() is None


def test_the_tab_opened_on_the_tiles_run_is_kept(qtbot, tmp_path):
    # That run's Cancel and its filling bar are in the opened tab, so it is no
    # longer one a later click may replace — the rule a tab that claimed the
    # same press already follows.
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    parked = _folder_tab(view, db)
    parked._param_form.set_values({"positive_prompt": "an entirely different subject"})

    _reroll_tile(view).add_requested.emit()

    assert view._info_tabs._preview_panel is None


def test_auto_toggle_greys_off_a_settings_leaf_but_stays_on_screen(qtbot, tmp_path):
    # Never hidden: Auto-Generate runs until it is stopped, and a switch that went away
    # with its folder would leave one running with nothing on screen to say so.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert not view._bank.auto.isHidden() and view._bank.auto.isEnabled()

    view._tree.setCurrentItem(_image_workflow(view._tree))  # a workflow, not a leaf

    assert not view._bank.auto.isHidden()   # still there
    assert not view._bank.auto.isEnabled()  # with nothing to do from here
    assert "open a settings folder" in view._bank.auto.toolTip()


def test_the_switchs_tip_takes_you_to_whichever_folder_auto_generate_runs_in(qtbot, tmp_path):
    # The tip is only offered while Auto-Generate is somewhere other than the folder on
    # screen, and being taken there is the whole of what it is for — naming the
    # folder would be no help, since the names are long and alike.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_auto(True)
    view._tree.setCurrentItem(_image_workflow(view._tree))  # look somewhere else
    assert _selected_folder(view) != key

    view._bank.auto_tip.link_activated.emit("auto")

    assert _selected_folder(view) == key


# --- a tab's Generate is a re-roll of its folder, navigated to at once ---------


def test_generate_launches_a_reroll_in_the_configs_existing_folder(qtbot, tmp_path):
    # Change 1: Generate in a tab whose settings match an existing folder launches a
    # re-roll there and lands the browser in that folder, its live tile selected.
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    orig_folder = _select_first_leaf(view)      # the folder 'orig' already lives in
    view._tree.setCurrentItem(_image_workflow(view._tree))  # navigate away first

    folder = _generate_in_current_tab(view, positive_prompt="a cat", seed=123)

    assert folder == orig_folder                    # same settings folder as 'orig'
    assert folder in view._live_jobs              # a re-roll now runs in it
    assert _selected_folder(view) == folder    # and the view jumped there
    assert view._selected_reroll_key == folder      # its live tile drives the info pane


def test_generate_navigates_to_a_brand_new_folder_immediately(qtbot, tmp_path):
    # Change 3: edited params make a settings folder with no finished result yet, but
    # the re-roll's running row gives it a tree node at once — so the view navigates
    # there DURING generation, not only when it finishes.
    db = _seeded_db(tmp_path, seed=7)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    before = {base_of(key) for key in view._item_by_key}

    folder = _generate_in_current_tab(view, positive_prompt="a totally new prompt", seed=5)

    assert folder not in before                     # a brand-new folder...
    assert view._tree_item_for(folder) is not None  # ...that now has a node (its running row)
    assert folder in view._live_jobs              # the re-roll is in flight
    assert _selected_folder(view) == folder    # navigated to at once, mid-generation


# --- a tab's right-click: across to the folder its settings generate into -----


def test_a_tabs_go_to_folder_opens_the_folder_its_settings_have_made(qtbot, tmp_path):
    # The way across from an open generate tab to the images it has made.
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    folder = _select_first_leaf(view)            # the folder 'orig' lives in
    panel = view._info_tabs.current_config_panel()
    panel.prefill("sdxl_t2i",
                  dict(_SDXL.default_params(), seed=7, positive_prompt="a cat"))
    view._tree.setCurrentItem(_image_workflow(view._tree))  # navigate away first

    view._info_tabs.folder_requested.emit(panel.settings_folder_key())

    assert _selected_folder(view) == folder


def test_a_tabs_go_to_folder_puts_a_running_search_away(qtbot, tmp_path):
    # It is a decision to go somewhere, so the hits it was raised over stop
    # standing over the folder it opens.
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel = view._info_tabs.current_config_panel()
    panel.prefill("sdxl_t2i",
                  dict(_SDXL.default_params(), seed=7, positive_prompt="a cat"))
    _search_for(view, "cat")

    view._info_tabs.folder_requested.emit(panel.settings_folder_key())

    assert view._search.field.text() == ""


def test_a_run_generated_with_a_request_typed_on_its_tab_is_recorded_as_one(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view._on_thumbnail_clicked("orig")
    panel = view._info_tabs.current_config_panel()
    panel._param_form.request_field()._words.setText("two cats")

    view._on_generate_requested("sdxl_t2i", [{"seed": 9, "positive_prompt": "two cats"}])

    (job,) = view._live_jobs.values()
    record = db.get_request(job.prompt_id)
    assert (record["asked"], record["heard"], record["source_prompt_id"]) == ("two cats", "", "orig")
    assert (record["old_positive"], record["new_positive"]) == ("a cat", "two cats")


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
    assert job.params["seed"] != 42            # a fresh seed, not the duplicate's


def test_generate_from_a_tab_back_on_its_videos_own_seeds_draws_a_fresh_one(qtbot, tmp_path):
    # Saved before its workflow gained its later settings, this video matches no
    # saved row key for key; the tab showing it on its own seeds still says
    # "Generate with Random seed", and the press keeps that promise.
    db = Database(tmp_path / "t.db")
    db.insert_generation(
        prompt_id="vid", workflow_name="wan22_i2v", workflow_version="v002",
        params_json=json.dumps({"positive_prompt": "dance", "input_image": "frame.png",
                                "noise_seed": 22, "audio_seed": 33}),
        workflow_json="{}")
    db.update_generation("vid", status="completed", output_files=json.dumps(
        [{"filename": "vid.mp4", "subfolder": "video"}]))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel = _front_panel(view)
    panel._preview.show_media = MagicMock()
    panel.show_saved_generation(db.get_generation("vid"), [])
    panel._param_form.set_seed_random(False)

    panel._on_generate()

    job = next(iter(view._live_jobs.values()))
    assert job.params["noise_seed"] != 22


def test_generate_request_without_a_duplicate_launches_straight_away(qtbot, tmp_path):
    db = _seeded_db(tmp_path, seed=42)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._on_generate_requested("sdxl_t2i", [{"seed": 999, "positive_prompt": "a novel prompt"}])

    job = next(iter(view._live_jobs.values()))
    assert job.params["seed"] == 999           # launched exactly as asked, unprompted


def test_a_press_for_several_puts_every_one_in_its_folder_at_once(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    panel = view._info_tabs.current_config_panel()
    panel._workflow_combo.setCurrentIndex(panel._workflow_combo.findData("sdxl_t2i"))
    panel._how_many.set_how_many(4)

    panel._on_generate()

    (folder,) = view._jobs.jobs_by_folder.values()
    assert len({job.params["seed"] for job in folder}) == 4
    client.interrupt.assert_not_called()
    assert len(panel.launched_runs()) == 4
    assert panel._generate_btn.isEnabled() is False


# --- the Genau lane: a looping clip, made but not sent anywhere ---------------


def test_the_genau_lane_runs_looping_settings(qtbot, tmp_path, monkeypatch):
    view = _genau_view(qtbot, tmp_path)

    view._combine.generate_category("img", "alpha", act_settings.GENAU)

    job = next(iter(view._live_jobs.values()))
    # The act has a long-form video too; the Genau lane can only use the loop.
    assert job.workflow.name == "wan22_flf2v_loop"
    assert job.params["input_image"] == "sdxl_pick.png [output]"


def test_the_view_asks_the_video_lane_unless_told_otherwise(qtbot, tmp_path, monkeypatch):
    view = _genau_view(qtbot, tmp_path)
    asked = []

    def spy(category, candidates, intent=act_settings.VIDEO):
        asked.append(intent)
        return "vid"

    monkeypatch.setattr(combine_controller.act_settings, "most_used_video", spy)

    view._combine.generate_category("img", "dancing")
    view._combine.generate_category("img", "dancing", act_settings.GENAU)

    assert asked == [act_settings.VIDEO, act_settings.GENAU]


def test_a_pressed_generate_leaves_its_clip_in_the_gallery(qtbot, tmp_path, monkeypatch):
    # Someone at the keyboard can look at the loop first, so nothing leaves for
    # Evolver until Send-to-Genau is pressed.
    view = _genau_view(qtbot, tmp_path)
    monkeypatch.setattr(gallery_view_module.gallery, "resolve_preview",
                        lambda row, out: (Path("C:/out/flf2v_loop_1.mp4"), "video"))
    sent = []
    monkeypatch.setattr(evolver_export, "export_video",
                        lambda src, dest, funscript=None: sent.append(src))

    view._combine.generate_category("img", "alpha", act_settings.GENAU)
    job = next(iter(view._live_jobs.values()))
    assert view._db.get_generation(job.prompt_id)["genau_requested_at"] is None

    view._on_reroll_finished("k", "loop")
    assert sent == []
    assert view._db.get_generation("loop")["genau_exported_at"] is None


def test_a_tabs_generate_goes_off_the_moment_its_folder_is_making_one(qtbot, tmp_path):
    # His rule: one item at a time per folder. The press that starts a run takes
    # the button with it, so the second half of a double-click lands on nothing.
    db = _seeded_db(tmp_path, seed=42)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel = view._info_tabs.current_config_panel()
    panel._workflow_combo.setCurrentIndex(panel._workflow_combo.findData("sdxl_t2i"))
    assert panel._generate_btn.isEnabled() is True
    config = panel.current_config()

    view._on_generate_requested(config.workflow_name, [config.params])

    assert panel._generate_btn.isEnabled() is False


def test_a_second_press_into_a_folder_already_making_one_makes_nothing(qtbot, tmp_path):
    # The double-click he describes: the app has been slow enough that he presses
    # Generate twice to be sure it took, and the second press used to draw its own
    # seed and make an image he never asked for.
    db = _seeded_db(tmp_path, seed=42)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel = view._info_tabs.current_config_panel()
    panel._workflow_combo.setCurrentIndex(panel._workflow_combo.findData("sdxl_t2i"))
    config = panel.current_config()

    view._on_generate_requested(config.workflow_name, [config.params])
    view._on_generate_requested(config.workflow_name, [config.params])

    assert len(view._jobs.all_jobs) == 1
