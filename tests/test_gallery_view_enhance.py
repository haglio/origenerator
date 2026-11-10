from __future__ import annotations

import json

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
    QPushButton,
)

from origenerator import (
    gallery,
)
from origenerator.db import Database, NewGeneration
from origenerator.gallery.collection import (
    EXPERIMENTS_KEY,
    FAVORITES_KEY,
    LATEST_KEY,
    TRASH_KEY,
)
from origenerator.gui import gallery_view as gallery_view_module
from origenerator.gui import generate_tab as generate_tab_module
from origenerator.gui.enhance_controller import NOTHING_LEFT_TO_ENHANCE
from origenerator.gui.enhance_versions import _AddRow, _PendingRow, _VersionRow
from origenerator.gui.gallery_view import GalleryView
from origenerator.output_places import OutputPlaces
from tests.gallery_view_support import (
    _ENHANCE_HISTORY,
    _NO_MOD,
    _SDXL,
    FakeActions,
    _click_off,
    _collection,
    _enhanceable_db,
    _enhanced_in_place,
    _image_workflow,
    _menu_offering,
    _open_latest,
    _png_bytes,
    _reroll_client,
    _resolve_by_id,
    _select_first_leaf,
    _set_enhance,
)
from tests.slideshow_hud_support import funestra_of

pytestmark = pytest.mark.usefixtures("_stub_preview_resolution")


def test_enhance_button_lives_on_but_goes_dark_with_nothing_awaiting(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    _click_off(view)
    assert not view._buttons.enhance.isHidden()
    assert view._buttons.enhance.isEnabled()
    assert "1 not-yet-enhanced image" in view._buttons.enhance.toolTip()

    db.insert_generation(NewGeneration(
        prompt_id="e0", workflow_name="image_enhance", workflow_version="v001",
        params_json=json.dumps({"input_image": "image/sdxl_t2i_g0.png [output]"}),
        workflow_json="{}",
    ))
    db.update_generation("e0", status="completed",
                         output_files=json.dumps([{"filename": "image_enhance_e0.png"}]))
    view.refresh()
    key = gallery.settings_folder_key(db.get_generation("g0"))
    view._tree.setCurrentItem(view._tree_item_for(key))
    assert not view._buttons.enhance.isHidden(), (
        "a button that vanishes is one the user has to go looking for")
    assert not view._buttons.enhance.isEnabled()
    assert view._buttons.enhance.toolTip() == NOTHING_LEFT_TO_ENHANCE


def test_enhance_all_never_stops_one_of_its_own_images_for_the_next(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_enhanceable_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    view._enhance._enhance_all()

    client.interrupt.assert_not_called()
    client.submit_job.assert_called_once()


def test_enhance_all_queues_every_image_in_the_folder(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_enhanceable_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    view._enhance._enhance_all()

    jobs = view._jobs.all_jobs
    assert len(jobs) == 2
    assert {j.workflow.name for j in jobs} == {"image_enhance"}
    assert all(j.params["input_image"].startswith("image/sdxl_t2i_g") for j in jobs)
    assert {j.params["positive_prompt"] for j in jobs} == {"a cat"}

    running = next(j for j in jobs if j.prompt_id == view._jobs.queue_order[0])
    waiting = next(j for j in jobs if j is not running)
    client.job_completed.emit(running.prompt_id, _ENHANCE_HISTORY)

    assert [j.prompt_id for j in view._jobs.all_jobs] == [waiting.prompt_id]
    assert view._db.get_generation(running.prompt_id) is None
    (upgraded,) = [r for r in view._db.list_generations() if r.get("original_files")]
    files = gallery.row_output_files(upgraded)
    assert files[0]["filename"] == "image_enhance_00001_.png"
    assert files[1]["filename"] == f"sdxl_t2i_{upgraded['prompt_id']}.png"
    assert gallery.is_enhanced_row(upgraded)


def test_a_finished_enhancement_reaches_the_open_tabs_version_list(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_enhanceable_db(tmp_path, count=1), client=client)
    qtbot.addWidget(view)
    view.refresh()
    view._on_thumbnail_clicked("g0")
    tab = view._generate_pane.current_generate_tab()
    assert len(tab._versions._host.findChildren(_VersionRow)) == 1
    view.enhance_items(["g0"])
    (job,) = view._jobs.all_jobs

    client.job_completed.emit(job.prompt_id, _ENHANCE_HISTORY)

    rows = tab._versions._host.findChildren(_VersionRow)
    assert len(rows) == 2
    assert not tab._versions._host.findChildren(_PendingRow)
    assert tab.displayed_row()["prompt_id"] == "g0"


def test_a_finished_enhancement_leaves_a_tab_on_another_image_alone(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_enhanceable_db(tmp_path, count=2), client=client)
    qtbot.addWidget(view)
    view.refresh()
    view._on_thumbnail_clicked("g1")
    tab = view._generate_pane.current_generate_tab()
    view.enhance_items(["g0"])
    (job,) = view._jobs.all_jobs

    client.job_completed.emit(job.prompt_id, _ENHANCE_HISTORY)

    assert tab.displayed_row()["prompt_id"] == "g1"
    assert len(tab._versions._host.findChildren(_VersionRow)) == 1


def test_a_queue_rows_shield_keeps_its_run_going_for_the_image_asked_for_after_it(
        qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_enhanceable_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    view.enhance_items(["g0"])
    (first,) = view._jobs.all_jobs
    client.progress.emit(first.prompt_id, "s", 1, 10)
    view._update_queue()

    view._queue.rows()[0]._shield.click()
    view.enhance_items(["g1"])

    client.interrupt.assert_not_called()
    assert view._jobs.queue_order[0] == first.prompt_id


def _cancel_from_the_queue(view, job):
    view._update_queue()
    (queued,) = view._queue.rows()
    queued._cancel.click()


def _cancel_from_the_images_menu(view, job):
    view._enhance.cancel_for([view._db.get_generation("g0")])


def _fail_on_comfyui(view, job):
    view._client.job_error.emit(job.prompt_id, "boom")


@pytest.mark.parametrize("end_unfinished", [
    _cancel_from_the_queue, _cancel_from_the_images_menu, _fail_on_comfyui])
def test_an_enhancement_that_ends_unfinished_leaves_its_tab_as_before_the_press(
        qtbot, tmp_path, monkeypatch, end_unfinished):
    output_dir = tmp_path / "output"
    (output_dir / "image").mkdir(parents=True)
    image = output_dir / "image" / "sdxl_t2i_g0.png"
    image.write_bytes(_png_bytes())
    monkeypatch.setattr(generate_tab_module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output_dir))
    client = _reroll_client()
    view = GalleryView(_enhanceable_db(tmp_path, count=1), client=client)
    qtbot.addWidget(view)
    view.refresh()
    view._on_thumbnail_clicked("g0")
    tab = view._generate_pane.current_generate_tab()
    (plus,) = tab._versions._host.findChildren(_AddRow)
    qtbot.mouseClick(plus, Qt.MouseButton.LeftButton)
    (job,) = view._jobs.all_jobs
    client.preview_image.emit(job.prompt_id, _png_bytes())

    end_unfinished(view, job)

    assert not tab._versions._host.findChildren(_PendingRow)
    assert tab._versions._host.findChildren(_AddRow)
    assert not tab._viewport._live
    assert tab._viewport.is_showing_any([image])


def test_binning_a_version_reaches_a_tab_on_that_image_that_is_not_in_front(qtbot, tmp_path):
    client = _reroll_client()
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=client, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    view._on_thumbnail_clicked("g0")
    first_tab = view._generate_pane.current_generate_tab()
    view.enhance_items(["g0"])
    (job,) = view._jobs.all_jobs
    client.job_completed.emit(job.prompt_id, _ENHANCE_HISTORY)
    assert len(first_tab._versions._host.findChildren(_VersionRow)) == 2
    view._generate_pane.pin_current_tab()
    view._generate_pane.open_config("sdxl_t2i", {"positive_prompt": "a dog"})
    assert view._generate_pane.current_generate_tab() is not first_tab
    db.update_generation("g0", output_files=json.dumps(
        [{"filename": "sdxl_t2i_g0.png", "subfolder": "image", "type": "output"}]))

    view.delete_enhance_versions("g0", ["image_enhance_00001_.png"])

    assert len(first_tab._versions._host.findChildren(_VersionRow)) == 1


def test_binning_a_version_tells_the_slideshows_what_the_image_has_left(qtbot, tmp_path):
    client = _reroll_client()
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=client, actions=FakeActions())
    qtbot.addWidget(view)
    view.refresh()
    view.enhance_items(["g0"])
    (job,) = view._jobs.all_jobs
    client.job_completed.emit(job.prompt_id, _ENHANCE_HISTORY)
    told = []
    view._slideshows.note_versions_deleted = told.append

    view.delete_enhance_versions("g0", ["image_enhance_00001_.png"])

    assert [row["prompt_id"] for row in told] == ["g0"]


def test_enhance_items_queues_the_picked_images(qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view.enhance_items(["g0", "g1"])

    jobs = view._jobs.all_jobs
    assert len(jobs) == 2
    assert {j.workflow.name for j in jobs} == {"image_enhance"}


def test_the_enhance_panes_button_is_aimed_and_pressed_like_the_banks(qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    button = view._enhance.pane._enhance_button

    assert button.isEnabled()
    assert view._buttons.enhance.isEnabled()
    assert button.toolTip() == view._buttons.enhance.toolTip()

    button.click()

    assert view._jobs.all_jobs
    assert {job.workflow.name for job in view._jobs.all_jobs} == {"image_enhance"}


def test_enhance_pane_stays_up_wherever_you_are(qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert not view._enhance.pane.isHidden()

    for item in (_image_workflow(view._tree), _collection(view, LATEST_KEY),
                 _collection(view, FAVORITES_KEY), _collection(view, EXPERIMENTS_KEY),
                 _collection(view, TRASH_KEY)):
        view._tree.setCurrentItem(item)
        assert not view._enhance.pane.isHidden()


def test_the_panel_opens_on_the_settings_the_session_left(qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    _set_enhance(view, auto=True, params={"enhance_scale": 3.0, "enhance_steps": 42,
                                          "enhance_denoise": 0.4})

    shown = view._enhance.pane.settings()
    assert shown.auto is True
    assert shown.params["enhance_scale"] == 3.0
    assert shown.params["enhance_steps"] == 42
    assert gallery.EnhanceSettings.parse(view.enhance_settings()).auto is True


def test_editing_the_panel_takes_effect_at_once(qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    view._enhance.pane._steps.setValue(33)

    assert gallery.EnhanceSettings.parse(
        view.enhance_settings()
    ).params["enhance_steps"] == 33


def test_enhance_all_runs_at_the_panels_settings(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _set_enhance(view, params={"enhance_scale": 1.5, "enhance_steps": 44,
                               "enhance_denoise": 0.3})
    _select_first_leaf(view)

    view._enhance._enhance_all()

    (job,) = view._live_jobs.values()
    assert job.params["enhance_scale"] == 1.5
    assert job.params["enhance_steps"] == 44
    assert job.params["enhance_denoise"] == 0.3


def test_a_single_enhance_runs_at_the_same_settings_from_anywhere(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _set_enhance(view, params={"enhance_steps": 51})

    view.enhance_items(["g0"])

    (job,) = view._live_jobs.values()
    assert job.params["enhance_steps"] == 51


def test_auto_enhance_claims_a_newly_generated_image(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _set_enhance(view, auto=True, params={"enhance_steps": 27})

    view._on_reroll_finished(gallery.settings_folder_key(db.get_generation("g0")), "g0")

    (job,) = view._live_jobs.values()
    assert job.workflow.name == "image_enhance"
    assert job.params["enhance_steps"] == 27


def test_auto_enhance_leaves_a_new_image_alone_with_the_tick_off(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._on_reroll_finished(gallery.settings_folder_key(db.get_generation("g0")), "g0")

    assert view._live_jobs == {}


def test_a_reroll_never_inherits_the_enhancement_of_what_it_varies(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    db.set_params_json("g0", json.dumps(dict(
        _SDXL.default_params(), positive_prompt="a cat", seed=0, enhance=True)))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    view._start_reroll(key)

    (job,) = view._live_jobs.values()
    assert job.params["enhance"] is False


def test_a_running_enhance_shows_in_the_strip_of_the_tab_showing_that_image(qtbot,
                                                                            tmp_path):
    db = _enhanceable_db(tmp_path, count=2)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    tab = view._generate_pane.current_generate_tab()
    row = db.get_generation("g0")
    tab.show_saved_generation(row, view._image_rows)

    view.enhance_items(["g0"])

    assert tab._versions._host.findChildren(_PendingRow)
    (job,) = view._live_jobs.values()
    view._client.preview_image.emit(job.prompt_id, b"a frame")
    status, frame, settings = tab._pending_enhancement
    assert (status, frame) == ("running", b"a frame")
    assert settings.startswith("2x · 20 steps · 0.15 redraw")

    view.enhance_items(["g1"])
    assert tab._pending_enhancement == ("queued", None, settings)


def test_each_tab_reads_its_own_image_out_of_a_batch_of_enhances(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=2)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    first = view._generate_pane.current_generate_tab()
    first.show_saved_generation(db.get_generation("g0"), view._image_rows)
    second = view._generate_pane._add_subtab()
    second.show_saved_generation(db.get_generation("g1"), view._image_rows)

    view.enhance_items(["g0", "g1"])

    leader, follower = view._jobs.all_jobs
    assert [j.workflow.name for j in (leader, follower)] == \
        ["image_enhance", "image_enhance"]
    assert len(view._jobs.jobs) == 1
    assert view._enhance.run_of(db.get_generation("g1")).status == "queued"

    view._client.preview_image.emit(leader.prompt_id, b"a frame")
    assert first._pending_enhancement == (
        "running", b"a frame", gallery.describe_enhance_params(leader.params))
    assert second._pending_enhancement == (
        "queued", None, gallery.describe_enhance_params(follower.params))


def test_a_running_enhance_also_streams_onto_the_images_own_tile(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=2)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    assert view._gallery_pane._thumb_widgets["g0"]._enhancing is None

    view.enhance_items(["g0"])

    tile = view._gallery_pane._thumb_widgets["g0"]
    assert tile._enhancing is not None
    assert view._gallery_pane._thumb_widgets["g1"]._enhancing is None

    (job,) = view._jobs.all_jobs
    view._client.preview_image.emit(job.prompt_id, _png_bytes())
    tile = view._gallery_pane._thumb_widgets["g0"]
    assert tile._image_label.pixmap() is not None
    assert not tile._image_label.pixmap().isNull()

    view._jobs._jobs.clear()
    view._enhance.reconcile()
    assert tile._enhancing is None


def test_right_clicking_an_enhancing_tile_offers_to_cancel_the_enhancement(
        qtbot, tmp_path, monkeypatch):
    db = _enhanceable_db(tmp_path, count=2)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view.enhance_items(["g0"])
    (_job,) = view._jobs.all_jobs
    assert view._gallery_pane._thumb_widgets["g0"]._enhancing is not None
    labels = _menu_offering(monkeypatch, "gallery_view", pick="Cancel")

    view._gallery_pane._thumbnail_context_menu("g0", QPoint(0, 0))

    assert "Cancel 1 enhancement" in labels[0]
    assert view._jobs.all_jobs == []
    assert db.get_generation("g0") is not None
    assert view._gallery_pane._thumb_widgets["g0"]._enhancing is None


def test_canceling_one_enhancement_leaves_the_others_alone(
        qtbot, tmp_path, monkeypatch):
    db = _enhanceable_db(tmp_path, count=2)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view.enhance_items(["g0", "g1"])
    leader, follower = view._jobs.all_jobs
    _menu_offering(monkeypatch, "gallery_view", pick="Cancel")

    view._gallery_pane._thumbnail_context_menu("g1", QPoint(0, 0))

    assert view._jobs.all_jobs == [leader]
    assert follower not in view._jobs.all_jobs


def test_a_tile_with_nothing_in_flight_offers_no_cancel(qtbot, tmp_path, monkeypatch):
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    labels = _menu_offering(monkeypatch, "gallery_view")

    view._gallery_pane._thumbnail_context_menu("g0", QPoint(0, 0))

    assert not any(label.startswith("Cancel") for label in labels[0])


def test_a_running_enhance_gets_no_tile_of_its_own_on_latest(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view.enhance_items(["g0"])
    (job,) = view._jobs.all_jobs
    view.refresh()
    _open_latest(view)

    assert job.prompt_id not in view._gallery_pane._inflight_tiles
    assert view._gallery_pane._thumb_widgets["g0"]._enhancing is not None
    assert view._queue.keys() == [job.prompt_id]


def test_enhancing_an_image_lifts_its_tile_to_the_top_of_latest(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=3)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _open_latest(view)
    assert view.listed_prompt_ids() == ["g2", "g1", "g0"]

    view.enhance_items(["g0"])
    view.refresh()

    assert view.listed_prompt_ids() == ["g0", "g2", "g1"], (
        "the run shows only on the tile of the image it improves, which can have been made a "
        "thousand tiles ago; what is being done to an image is the newest thing about it")
    assert view._gallery_pane._thumb_widgets["g0"]._enhancing is not None


def test_an_enhance_still_queued_lends_its_tile_no_frame(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=2)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    view.enhance_items(["g0", "g1"])
    leader, follower = view._jobs.all_jobs
    view._client.preview_image.emit(leader.prompt_id, _png_bytes())

    tiles = view._gallery_pane._thumb_widgets
    assert tiles["g0"]._enhancing is not None
    assert tiles["g1"]._enhancing is not None
    assert not tiles["g0"]._image_label.pixmap().isNull()
    assert follower.state == "idle"
    assert tiles["g1"]._resting_pixmap is None, (
        "a tile keeps its own thumbnail until a frame of its run arrives: the image as it stands "
        "is worth looking at while it waits")


def test_a_locked_slide_says_queued_until_comfyui_picks_its_run_up(qtbot, tmp_path,
                                                                 monkeypatch):
    monkeypatch.setattr(gallery, "resolve_preview",
                        lambda row, places: (f"{row['prompt_id']}.png", "image"))
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view._slideshows.start()
    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    funestra_of(slideshow.shown)

    slideshow.shown.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, _NO_MOD))

    (job,) = view._jobs.all_jobs
    assert slideshow.hud_item_note == "Enhancement queued"

    view._client.preview_image.emit(job.prompt_id, _png_bytes())

    assert slideshow.hud_item_note == "Enhancing…"
    slideshow.close()


def test_deleting_an_image_cancels_the_enhance_being_made_of_it(qtbot, monkeypatch,
                                                                tmp_path):
    monkeypatch.setattr(gallery_view_module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(tmp_path / "output"))
    monkeypatch.setattr(gallery_view_module, "TRASH_DIR", tmp_path / "state" / "trash")
    db = _enhanceable_db(tmp_path, count=2)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view.enhance_items(["g0", "g1"])
    doomed, kept = view._jobs.all_jobs

    view._delete_rows([db.get_generation("g0")])

    assert doomed.state == "canceled"
    assert db.get_generation(doomed.prompt_id) is None
    assert view._jobs.all_jobs == [kept]


def test_a_re_enhance_is_cancelled_by_deleting_its_image_too(qtbot, monkeypatch,
                                                             tmp_path):
    monkeypatch.setattr(gallery_view_module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(tmp_path / "output"))
    monkeypatch.setattr(gallery_view_module, "TRASH_DIR", tmp_path / "state" / "trash")
    db = _enhanceable_db(tmp_path, count=1)
    db.update_generation(
        "g0",
        output_files=json.dumps([
            {"filename": "image_enhance_e0.png", "subfolder": "image", "type": "output"},
            {"filename": "sdxl_t2i_g0.png", "subfolder": "image", "type": "output"},
        ]),
        original_files=json.dumps([{"filename": "sdxl_t2i_g0.png",
                                    "subfolder": "image", "type": "output"}]),
    )
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view.enhance_items(["g0"])
    (job,) = view._jobs.all_jobs
    assert "sdxl_t2i_g0.png" in job.params["input_image"]

    view._delete_rows([db.get_generation("g0")])

    assert job.state == "canceled"
    assert view._jobs.all_jobs == []


def test_rejecting_an_experiment_cancels_the_enhance_being_made_of_it(qtbot, monkeypatch,
                                                                      tmp_path):
    monkeypatch.setattr(gallery_view_module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(tmp_path / "output"))
    monkeypatch.setattr(gallery_view_module, "TRASH_DIR", tmp_path / "state" / "trash")
    db = Database(tmp_path / "test.db")
    db.insert_generation(NewGeneration(
        prompt_id="g0", workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt="a cat", seed=0, workflow_json="{}", source="experiment",
        params_json=json.dumps({"positive_prompt": "a cat", "steps": 30, "seed": 0}),
    ))
    db.update_generation("g0", status="completed",
                         output_files=json.dumps([{"filename": "sdxl_t2i_g0.png",
                                                   "subfolder": "image",
                                                   "type": "output"}]))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view.enhance_items(["g0"])
    (job,) = view._jobs.all_jobs

    view.trash_generation("g0")

    assert job.state == "canceled", (
        "a rejection keeps the row but takes its files, and an enhancement that landed after would "
        "bring a rejected experiment back as an enhanced image")
    assert view._jobs.all_jobs == []


def test_the_version_lists_delete_trashes_that_level_and_keeps_the_image(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    row = _enhanced_in_place(db)
    view.refresh()
    tab = view._generate_pane.current_generate_tab()
    tab.show_saved_generation(row, view._image_rows)

    tab._versions.delete_requested.emit([0])

    updated = db.get_generation("g0")
    assert json.loads(updated["output_files"]) == [
        {"filename": "sdxl_t2i_g0.png", "subfolder": "image"}
    ]
    assert not gallery.is_enhanced_row(updated)
    assert view._edits.can_undo()
    assert not view._buttons.undo.isHidden()


def test_pressing_a_versions_trash_can_trashes_that_level_and_the_last_one_has_none(qtbot,
                                                                                tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    row = _enhanced_in_place(db)
    view.refresh()
    tab = view._generate_pane.current_generate_tab()
    tab.show_saved_generation(row, view._image_rows)
    enhancement = tab._versions._host.findChildren(_VersionRow)[0]

    enhancement.findChild(QPushButton, "deleteButton").click()

    updated = db.get_generation("g0")
    assert json.loads(updated["output_files"]) == [
        {"filename": "sdxl_t2i_g0.png", "subfolder": "image"}
    ]
    assert view._edits.can_undo()
    (original,) = tab._versions._host.findChildren(_VersionRow)
    assert original.findChild(QPushButton, "deleteButton") is None


def test_auto_enhance_stops_after_one_pass_rather_than_looping(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    _set_enhance(view, auto=True)

    view._on_reroll_finished(gallery.settings_folder_key(db.get_generation("g0")), "g0")
    (job,) = view._live_jobs.values()
    client.job_completed.emit(job.prompt_id, _ENHANCE_HISTORY)

    assert view._live_jobs == {}
    upgraded = db.get_generation("g0")
    assert gallery.is_enhanced_row(upgraded)
    assert [lvl.label for lvl in gallery.enhancement_versions(upgraded)] == \
        ["Enhancement 1/1", "Original"]


def test_a_tile_wears_an_enhancing_scrim_while_its_run_is_in_flight(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    tile = view._gallery_pane._thumb_widgets["g0"]
    assert tile._enhancing is None

    view.enhance_items(["g0"])
    view._rerender_current_leaf()

    assert view._gallery_pane._thumb_widgets["g0"]._enhancing is not None, (
        "without it a folder generating with auto-enhance on looks like it is turning out plain "
        "images and ignoring the switch")


def test_the_add_tile_enhances_the_image_the_tab_is_showing(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    tab = view._generate_pane.current_generate_tab()
    tab.show_saved_generation(db.get_generation("g0"), view._image_rows)
    _set_enhance(view, params={"enhance_steps": 29})

    tab._versions.enhance_requested.emit()

    (job,) = view._live_jobs.values()
    assert job.workflow.name == "image_enhance"
    assert job.params["enhance_steps"] == 29


def test_a_tab_turned_to_an_image_being_enhanced_shows_that_run(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=2)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    tab = view._generate_pane.current_generate_tab()
    tab.show_saved_generation(db.get_generation("g1"), view._image_rows)
    view.enhance_items(["g0"])
    assert not tab._versions._host.findChildren(_PendingRow)

    tab.show_saved_generation(db.get_generation("g0"), view._image_rows)

    assert tab._versions._host.findChildren(_PendingRow)


def test_a_tick_tells_a_locked_slide_its_run_began_though_no_frame_has_come(qtbot, tmp_path,
                                                                            monkeypatch):
    _resolve_by_id(monkeypatch)
    db = _enhanceable_db(tmp_path, count=1)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view._slideshows.start()
    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    funestra_of(slideshow.shown)
    slideshow.shown.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, _NO_MOD))
    (job,) = view._jobs.all_jobs
    assert slideshow.hud_item_note == "Enhancement queued"

    client.executing_prompts = lambda: [job.prompt_id]
    view._poll()

    assert slideshow.hud_item_note == "Enhancing…"
    slideshow.close()


def test_a_landed_enhancement_retires_the_enhance_button_and_the_tabs_live_row(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_enhanceable_db(tmp_path, count=1), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    tab = view._generate_pane.current_generate_tab()
    assert view._buttons.enhance.isEnabled()
    view.enhance_items(["g0"])
    (job,) = view._jobs.all_jobs

    client.job_completed.emit(job.prompt_id, _ENHANCE_HISTORY)

    assert not view._buttons.enhance.isEnabled()
    assert tab._pending_enhancement is None


def test_pressing_enhance_leaves_the_image_picked_and_new_settings_offer_another(qtbot, tmp_path):
    db = _enhanceable_db(tmp_path, count=1)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    pane = view._gallery_pane
    pane.apply_selection("g0", Qt.KeyboardModifier.NoModifier)

    view._enhance.enhance_the_selection()

    assert pane.selected_prompt_ids() == ["g0"]
    enhance_pane = view._enhance.pane
    enhance_pane._denoise.setValue(enhance_pane._denoise.value() + 0.1)
    assert enhance_pane._enhance_button.isEnabled()
