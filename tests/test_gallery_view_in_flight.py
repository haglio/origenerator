from __future__ import annotations

import json
import time
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PIL import Image
from PyQt6 import sip
from PyQt6.QtCore import (
    QPoint,
    Qt,
)
from PyQt6.QtWidgets import (
    QMessageBox,
)

from origenerator import (
    action_settings,
    fix_training,
    gallery,
    look_training,
    lora_training,
)
from origenerator.comfyui_api import ForeignQueue
from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database, NewGeneration, NewRequest
from origenerator.gallery.collection import (
    LATEST_KEY,
)
from origenerator.gallery_edits import GalleryEdits
from origenerator.generation_state import GenerationSource
from origenerator.gui import gallery_view as gallery_view_module
from origenerator.gui import generate_tab as generate_tab_module
from origenerator.gui.combine import CombineRequest
from origenerator.gui.gallery_view import _GROUP_ROLE, GalleryView
from origenerator.gui.hud_queue import queue_section
from origenerator.gui.inflight import InFlightItem, RunReading, cancel_tooltip
from origenerator.item_shape import base_of
from origenerator.media import MediaType
from origenerator.output_places import OutputPlaces
from origenerator.trash import Trash
from tests.comfyui_folders import SUITE_FOLDERS
from tests.gallery_view_support import (
    _NO_MOD,
    _REROLL_HISTORY,
    _SDXL,
    _VID_REROLL_HISTORY,
    _WAN_I2V,
    FakeDB,
    _alls,
    _answer_confirmation,
    _at,
    _collection,
    _combine_db,
    _double_click_slideshow,
    _enhanceable_db,
    _FakeRerollJob,
    _finish_reroll,
    _frame_shown,
    _front_panel,
    _generate_in_current_tab,
    _generating_tile,
    _image,
    _image_workflow,
    _key,
    _menu_offering,
    _new_tile,
    _open_latest,
    _png_bytes,
    _reroll_client,
    _resolve_by_id,
    _row,
    _running_reroll,
    _running_row,
    _search_for,
    _seeded_db,
    _select_first_leaf,
    _selected_folder,
    _single_i2v_db,
    _struck_and_lit,
    _tab_with_prompts,
    _viewport_of,
)
from tests.slideshow_hud_support import engine_of, funestra_of

pytestmark = pytest.mark.usefixtures("_stub_preview_resolution")


_IMG_REROLL_HISTORY = {"outputs": {"7": {"images": [
    {"filename": "sdxl_new.png", "subfolder": "image", "type": "output"}]}}}


def _insert_running_reroll(db, prompt_id="rr", seed=99):
    params = dict(_SDXL.default_params(), seed=seed, positive_prompt="a cat")
    db.insert_generation(NewGeneration(
        prompt_id=prompt_id, workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt="a cat", seed=seed,
        params_json=json.dumps(params), workflow_json="{}",
    ))
    db.update_generation(prompt_id, status="running")


def test_reconnect_running_rerolls_rebinds_a_live_job(qtbot, tmp_path):
    db = _seeded_db(tmp_path, seed=7)
    _insert_running_reroll(db, "rr")
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)

    view.reconnect_running_jobs()

    key = gallery.settings_folder_key(db.get_generation("rr"))
    assert key in view._live_jobs
    assert view._live_jobs[key].prompt_id == "rr"
    client.submit_job.assert_not_called()


@pytest.mark.parametrize("kind", [fix_training, look_training])
def test_a_training_left_running_of_either_kind_is_taken_up_without_holding_the_line(
        qtbot, tmp_path, monkeypatch, kind):
    db = _seeded_db(tmp_path, seed=7)
    _insert_running_reroll(db, "waiting")
    db.update_generation("waiting", status="pending")
    trainer = SimpleNamespace(running=lambda: True, began=0.0)
    job = {"part": "hands", "base": "Example Look", "display_name": "Example 1.0",
           "status": str(tmp_path / "status.json"), "log": str(tmp_path / "training.log")}
    monkeypatch.setattr(kind, "trainings", lambda: [job])
    monkeypatch.setattr(lora_training, "trainer_of", lambda kept: trainer)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)

    view.reconnect_running_jobs()

    assert view._jobs.training is not None
    client.submit_job.assert_called_once()


@pytest.mark.parametrize("kind", [fix_training, look_training])
def test_a_training_being_watched_stops_with_the_gallery_that_watches_it(
        qtbot, tmp_path, monkeypatch, kind):
    trainer = SimpleNamespace(running=lambda: True, began=0.0)
    job = {"part": "hands", "base": "Example Look", "display_name": "Example 1.0",
           "status": str(tmp_path / "status.json"), "log": str(tmp_path / "training.log")}
    monkeypatch.setattr(kind, "trainings", lambda: [job])
    monkeypatch.setattr(lora_training, "trainer_of", lambda kept: trainer)
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=_reroll_client())
    view.reconnect_running_jobs()
    run = view._jobs.training

    sip.delete(view)

    assert sip.isdeleted(run)


def test_reconnected_reroll_shows_live_tile_then_finalizes(qtbot, tmp_path):
    db = _seeded_db(tmp_path, seed=7)
    _insert_running_reroll(db, "rr")
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.reconnect_running_jobs()
    view.refresh()
    _select_first_leaf(view)
    assert _generating_tile(view) is not None

    client.job_completed.emit("rr", _REROLL_HISTORY)

    row = db.get_generation("rr")
    assert row["status"] == "completed"
    assert "a.png" in row["output_files"]
    assert view._live_jobs == {}


def test_starting_a_reroll_records_a_running_row(qtbot, tmp_path):
    db = _seeded_db(tmp_path, seed=7)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    _new_tile(view).add_requested.emit()

    job = view._live_jobs[key]
    row = db.get_generation(job.prompt_id)
    assert row is not None
    assert row["status"] == "running"
    assert row["workflow_name"] == "sdxl_t2i"
    assert gallery.row_output_files(row) == []


def test_reroll_completion_finalizes_the_running_row(qtbot, tmp_path):
    client = _reroll_client()
    db = _seeded_db(tmp_path, seed=7)
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _new_tile(view).add_requested.emit()
    prompt_id = view._live_jobs[key].prompt_id

    client.job_completed.emit(prompt_id, _REROLL_HISTORY)

    rows = db.list_generations()
    assert len(rows) == 2
    new = db.get_generation(prompt_id)
    assert new["status"] == "completed"
    assert "a.png" in new["output_files"]
    assert new["seed"] != 7
    assert view._live_jobs == {}


def test_canceling_a_reroll_removes_its_running_row(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _new_tile(view).add_requested.emit()
    prompt_id = view._live_jobs[key].prompt_id
    assert db.get_generation(prompt_id) is not None

    _generating_tile(view).cancel_requested.emit()

    assert db.get_generation(prompt_id) is None


def test_failed_reroll_marks_its_running_row_error(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _new_tile(view).add_requested.emit()
    job = view._live_jobs[key]

    view._client.job_error.emit(job.prompt_id, "boom")

    assert db.get_generation(job.prompt_id)["status"] == "error"
    assert key not in view._live_jobs


def _generation_failed_dialog(view):
    (dialog,) = view.findChildren(gallery_view_module.QMessageBox)
    assert dialog.windowTitle() == "Generation failed"
    return dialog


def test_a_failed_run_says_so_instead_of_vanishing(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _new_tile(view).add_requested.emit()
    job = view._live_jobs[key]

    view._client.job_error.emit(job.prompt_id, json.dumps(
        {"node_type": "RIFE VFI",
         "exception_message": "Tried all base urls but no success"
         + chr(10) * 2 + "long log"}))

    assert _generation_failed_dialog(view).text() == (
        "RIFE VFI failed: Tried all base urls but no success")


def _refusing_client(reason):
    client = _reroll_client()
    client.submit_job = MagicMock(side_effect=RuntimeError(reason))
    return client


def test_a_generate_comfyui_refuses_to_start_says_so_too(qtbot, tmp_path):
    view = GalleryView(Database(tmp_path / "test.db"), client=_refusing_client(
        "UNETLoader: unet_name: 'example_high.safetensors' not in (list of length 38)"))
    qtbot.addWidget(view)

    view._on_generate_requested("wan22_t2i", [{
        "positive_prompt": "a lighthouse", "width": 1088, "height": 1920,
        "unet_high": "example_high.safetensors", "unet_low": "example_low.safetensors"}])

    assert "example_high.safetensors" in _generation_failed_dialog(view).text()


def test_a_burst_of_refused_generations_is_one_dialog_saying_the_reason_once(
        qtbot, tmp_path):
    view = GalleryView(Database(tmp_path / "test.db"), client=_refusing_client(
        "UNETLoader: unet_name: 'example_high.safetensors' not in (list of length 38)"))
    qtbot.addWidget(view)

    for seed in (1, 2, 3):
        view._on_generate_requested("wan22_t2i", [{"positive_prompt": "a lighthouse",
                                                   "noise_seed": seed, "seed": seed}])

    said = _generation_failed_dialog(view).text()
    assert said.count("example_high.safetensors") == 1
    assert "3 generations" in said


def test_a_press_for_several_that_comfyui_refuses_is_one_dialog(qtbot, tmp_path):
    view = GalleryView(Database(tmp_path / "test.db"), client=_refusing_client(
        "UNETLoader: unet_name: 'example_high.safetensors' not in (list of length 38)"))
    qtbot.addWidget(view)

    view._on_generate_requested("wan22_t2i", [
        {"positive_prompt": "a lighthouse", "noise_seed": seed, "seed": seed}
        for seed in (1, 2, 3)])

    said = _generation_failed_dialog(view).text()
    assert said.count("example_high.safetensors") == 1
    assert "3 generations" in said


def test_cancel_from_the_tile_dequeues_and_stops_the_run_by_name(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _new_tile(view).add_requested.emit()
    prompt_id = view._live_jobs[key].prompt_id

    client.node_executing.emit(prompt_id, "5")
    _generating_tile(view).cancel_requested.emit()

    client.cancel_prompt.assert_called_once_with(prompt_id)
    client.interrupt.assert_called_once_with(prompt_id)
    assert key not in view._live_jobs
    assert _generating_tile(view) is None
    assert _new_tile(view).isEnabled()


def test_active_reroll_survives_a_refresh(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _new_tile(view).add_requested.emit()

    view.refresh()

    assert key in view._live_jobs
    assert _generating_tile(view) is not None



def test_selecting_a_running_reroll_shows_its_live_preview_in_the_generate_pane(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)
    frame = _png_bytes()
    client.preview_image.emit(job.prompt_id, frame)
    _viewport_of(view).show_frame = MagicMock()

    _generating_tile(view).selected.emit()

    _viewport_of(view).show_frame.assert_called_once_with(frame)


def test_new_frames_route_to_the_generate_pane_while_the_reroll_is_selected(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)
    _generating_tile(view).selected.emit()
    _viewport_of(view).show_frame = MagicMock()

    client.preview_image.emit(job.prompt_id, _png_bytes())

    _viewport_of(view).show_frame.assert_called_once_with(_png_bytes())


def test_selecting_a_thumbnail_stops_the_reroll_from_driving_the_generate_pane(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)
    view._on_thumbnail_clicked("orig")

    _viewport_of(view).show_frame = MagicMock()
    client.preview_image.emit(job.prompt_id, _png_bytes())

    _viewport_of(view).show_frame.assert_not_called()
    assert view._selected_reroll_key is None


def test_a_selected_runs_tile_drawn_over_by_another_pane_is_let_go_of_quietly(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _running_reroll(view)
    tile = _generating_tile(view)
    tile.selected.emit()
    view._gallery_pane.show_empty()
    assert sip.isdeleted(tile)

    try:
        view._on_thumbnail_clicked("orig")
    except RuntimeError as error:
        raise AssertionError(
            "the run's tile is drawn inside the pane and is deleted with it, so the view must "
            "not go on unselecting the tile it held") from error


def test_selecting_the_reroll_highlights_its_tile_and_drops_thumbnail_picks(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _running_reroll(view)
    view._gallery_pane.apply_selection("orig", _NO_MOD)
    assert view.selected_prompt_ids() == ["orig"]

    _generating_tile(view).selected.emit()

    assert _generating_tile(view)._selected
    assert view.selected_prompt_ids() == []


def test_finishing_a_selected_reroll_clears_the_reroll_selection(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)
    _generating_tile(view).selected.emit()

    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)

    assert view._selected_reroll_key is None


def test_finishing_a_reroll_loads_its_result_into_the_tab_that_launched_it(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=client)
    qtbot.addWidget(view)
    view.refresh()
    tab = view._generate_pane.current_generate_tab()
    key = _generate_in_current_tab(view, positive_prompt="a cat", seed=9)
    job = view._live_jobs[key]

    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)

    assert tab._displayed_row is not None, (
        "the tab that asked for the run is found before the finish is settled, because a tab "
        "lets go of its runs as they end")
    assert tab._displayed_row["prompt_id"] == job.prompt_id


def test_the_tiles_run_lands_in_the_tab_standing_on_its_folder(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)

    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)

    assert view._generate_pane.count() == 1
    tab = view._generate_pane.current_generate_tab()
    assert tab.displayed_row()["prompt_id"] == job.prompt_id


def test_the_tab_claiming_the_tiles_run_is_kept(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    tabs = view._generate_pane
    assert tabs._preview_tab is tabs.current_generate_tab()

    _new_tile(view).add_requested.emit()

    assert tabs._preview_tab is None, (
        "that run's Cancel and its filling bar are in this tab now, so it is no longer one a "
        "later click may replace")


def test_opening_a_runs_folder_from_its_tile_loads_no_saved_item(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key, _job = _running_reroll(view)
    view._tree.setCurrentItem(_image_workflow(view._tree))
    view._generate_pane.load_selection = MagicMock()

    view._reveal_reroll(key)

    assert view._generate_pane.load_selection.call_count == 0, (
        "the open is a step on the way to that run's tile rather than somewhere browsed to, so "
        "it lands on no saved item of its own: one would paint an item nobody asked for over the "
        "very tab the run belongs to, and re-seed that tab's form from a saved row mid-run")
    assert view._generate_pane.current_generate_tab().watched_key() == key


def test_finishing_a_reroll_keeps_a_prompt_typed_while_it_ran(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=client)
    qtbot.addWidget(view)
    view.refresh()
    tab = view._generate_pane.current_generate_tab()
    key = _generate_in_current_tab(view, positive_prompt="a cat", seed=9)
    job = view._live_jobs[key]
    tab._param_form.set_values({"positive_prompt": "a wizard mid-edit"})

    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)

    assert tab._param_form.get_values()["positive_prompt"] == "a wizard mid-edit"


def test_canceling_a_selected_reroll_releases_the_generate_pane(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key, _job = _running_reroll(view)
    _generating_tile(view).selected.emit()
    tab = view._generate_pane.current_generate_tab()
    assert tab.watched_key() == key

    view._cancel_reroll(key)

    assert view._selected_reroll_key is None
    assert tab.watched_key() is None, (
        "once the folder has no run left, the tabs following it stop following it")


def test_a_generation_can_be_watched_fullscreen_while_it_is_still_being_made(
        qtbot, tmp_path, monkeypatch):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)
    _generating_tile(view).selected.emit()
    client.preview_image.emit(job.prompt_id, _png_bytes())
    view._poll()

    win = _viewport_of(view).open_fullscreen()
    qtbot.addWidget(win.shown)
    assert win._set.current_prompt_id() == job.prompt_id
    assert engine_of(win.shown).on_screen.read_bytes() == _png_bytes()
    win.tick()

    buf = BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, format="PNG")
    client.preview_image.emit(job.prompt_id, buf.getvalue())
    assert engine_of(win.shown).on_screen.read_bytes() == buf.getvalue()

    done = tmp_path / "done.png"
    Image.new("RGB", (8, 8), (10, 120, 200)).save(done, "PNG")
    def landed(row, places):
        return (done, "image") if row["prompt_id"] == job.prompt_id else None
    monkeypatch.setattr(generate_tab_module, "resolve_preview", landed)
    monkeypatch.setattr(gallery, "resolve_preview", landed)

    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)
    win.tick()
    win.tick()

    assert engine_of(win.shown).on_screen == done
    assert not win._set.playlist.current().is_live
    win.close()


def test_a_run_watched_fullscreen_lands_as_its_generation_among_its_folder(
        qtbot, tmp_path, monkeypatch):
    def by_id(row, places):
        return (f"{row['prompt_id']}.png", "image")
    monkeypatch.setattr(gallery, "resolve_preview", by_id)
    monkeypatch.setattr(generate_tab_module, "resolve_preview", by_id)
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)
    _generating_tile(view).selected.emit()
    client.preview_image.emit(job.prompt_id, _png_bytes())
    view._poll()
    slideshow = _viewport_of(view).open_fullscreen()
    qtbot.addWidget(slideshow.shown)
    funestra_of(slideshow.shown)

    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)

    assert [slide.prompt_id for slide in slideshow._set.playlist.in_play_order()] == \
        view.listed_prompt_ids()
    assert slideshow._set.playlist.current().prompt_id == job.prompt_id
    qtbot.keyClick(slideshow.shown, Qt.Key.Key_Down)
    assert view._enhance.run_of(view.row_for(job.prompt_id)) is not None
    slideshow.close()


def test_a_cancelled_generation_is_taken_out_of_the_slideshow_watching_it(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key, job = _running_reroll(view)
    _generating_tile(view).selected.emit()
    client.preview_image.emit(job.prompt_id, _png_bytes())
    view._poll()
    slideshow = _double_click_slideshow(view, qtbot, media=None)
    slideshow.shown.show()

    view._cancel_reroll(key)
    view._poll()

    assert job.prompt_id not in [slide.prompt_id
                                 for slide in slideshow._set.playlist.in_play_order()]


def test_a_cancelled_generation_leaves_a_slideshow_of_a_saved_file_alone(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key, _job = _running_reroll(view)
    _generating_tile(view).selected.emit()
    slideshow = _double_click_slideshow(view, qtbot)
    slideshow.shown.show()

    view._cancel_reroll(key)

    assert slideshow.shown.isVisible()
    slideshow.close()


def test_clicking_add_opens_a_tab_on_the_run_it_started(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    _new_tile(view).add_requested.emit()

    assert view._generate_pane.current_generate_tab().watched_key() == key
    assert view._selected_reroll_key == key
    assert _generating_tile(view)._selected


def test_selecting_a_reroll_before_any_frame_avoids_the_idle_placeholder(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _running_reroll(view)
    painted = []
    _viewport_of(view).clear = MagicMock(side_effect=lambda: painted.append("(placeholder)"))
    _viewport_of(view).show_message = MagicMock(
        side_effect=lambda text, **kwargs: painted.append(text))

    _generating_tile(view).selected.emit()

    assert painted[-1] == "Waiting for preview…", (
        "seeding the landing tab from the run's settings may pass through the placeholder; what "
        "the pane ends on is the point")
    assert _viewport_of(view).show_message.call_args == (("Waiting for preview…",), {"live": True})


def _waiting_view(qtbot, tmp_path, backlog):
    client = _reroll_client()
    client.fetch_history = MagicMock(return_value={})
    client.foreign_backlog = MagicMock(return_value=backlog)
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _running_reroll(view)
    _viewport_of(view).show_message = MagicMock()
    _generating_tile(view).selected.emit()
    return view, client


def test_a_run_stuck_behind_another_app_says_how_much_is_ahead(qtbot, tmp_path):
    view, _client = _waiting_view(qtbot, tmp_path, backlog=3)

    view._poll()

    assert _viewport_of(view).show_message.call_args.args[0] == "Waiting on 3 jobs from another app"


def test_the_wait_text_follows_the_queue_as_it_drains(qtbot, tmp_path):
    view, client = _waiting_view(qtbot, tmp_path, backlog=3)
    view._poll()

    client.foreign_backlog = MagicMock(return_value=1)
    view._poll()

    assert _viewport_of(view).show_message.call_args.args[0] == "Waiting on 1 job from another app"


def test_a_queue_of_the_users_own_jobs_leaves_the_plain_waiting_note(qtbot, tmp_path):
    view, _client = _waiting_view(qtbot, tmp_path, backlog=0)

    view._poll()

    assert _viewport_of(view).show_message.call_args.args[0] == "Waiting for preview…", (
        "waiting on the user's own queue means ComfyUI is generating something the user asked "
        "for, which is no mystery at all")


def test_a_run_waiting_out_the_minute_after_an_image_says_when_it_starts(
        qtbot, tmp_path, monkeypatch):
    clear_of_a_rollover = 0.5
    view, _client = _waiting_view(qtbot, tmp_path, backlog=0)
    waiting, = view._live_jobs.values()
    monkeypatch.setattr(view._jobs, "starts_at",
                        lambda prompt_id: time.monotonic() + 42 + clear_of_a_rollover
                        if prompt_id == waiting.prompt_id else None)

    view._poll()

    assert _viewport_of(view).show_message.call_args.args[0] == "Starts in 0:43"


def test_start_now_on_the_job_queue_starts_the_video_waiting_out_the_minute(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _key, image = _running_reroll(view)
    view._jobs.start_prepared("video/k", _WAN_I2V, dict(_WAN_I2V.default_params(), seed=3))
    video = view._jobs.newest_job_for("video/k")
    view._jobs.cancel_job(image.prompt_id)
    view._update_queue()
    assert view._queue._running.status_text().startswith("Starts in")

    view._queue._running._start_now.click()

    assert client.submit_job.call_args_list[-1].args[1] == video.prompt_id
    assert not view._queue._running.status_text().startswith("Starts in")


def test_a_streamed_frame_ends_the_wait_text(qtbot, tmp_path):
    view, client = _waiting_view(qtbot, tmp_path, backlog=3)
    view._poll()
    job = next(iter(view._live_jobs.values()))
    client.preview_image.emit(job.prompt_id, _png_bytes())
    _viewport_of(view).show_message = MagicMock()

    view._poll()

    _viewport_of(view).show_message.assert_not_called()


def test_selected_reroll_survives_the_rebuild_its_running_row_triggers(qtbot, tmp_path):
    client = _reroll_client()
    client.fetch_history = MagicMock(return_value={})
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key, job = _running_reroll(view)
    frame = _png_bytes()
    client.preview_image.emit(job.prompt_id, frame)
    _generating_tile(view).selected.emit()
    tab = view._generate_pane.current_generate_tab()
    assert tab.watched_key() == key
    assert _frame_shown(tab._viewport, frame)

    view._poll()

    assert view._selected_reroll_key == key
    assert _generating_tile(view)._selected
    assert view._generate_pane.current_generate_tab() is tab
    assert tab.watched_key() == key
    assert _frame_shown(tab._viewport, frame)


def test_i2v_video_stage_keeps_the_last_image_frame_until_it_previews(qtbot, tmp_path):
    client = _reroll_client()
    client.fetch_history = MagicMock(return_value={})
    view = GalleryView(_seeded_i2v_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_leaf_of(view, "vid")
    _new_tile(view).add_requested.emit()
    img_job = view._live_jobs[key]
    _generating_tile(view).selected.emit()
    image_frame = _png_bytes()
    client.preview_image.emit(img_job.prompt_id, image_frame)

    client.job_completed.emit(img_job.prompt_id, _IMG_REROLL_HISTORY)
    assert view._live_jobs[key].workflow.name == "wan22_i2v"

    view._poll()

    assert view._selected_reroll_key == key
    tab = view._generate_pane.current_generate_tab()
    assert tab.watched_key() == key
    assert _frame_shown(tab._viewport, image_frame)


def _seeded_i2v_db(tmp_path):
    db = Database(tmp_path / "i2v.db")
    db.insert_generation(NewGeneration(
        prompt_id="img", workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt="a cat", negative_prompt="", seed=7,
        params_json=json.dumps(dict(_SDXL.default_params(), seed=7, positive_prompt="a cat")),
        workflow_json="{}",
    ))
    db.update_generation(
        "img", status="completed",
        output_files=json.dumps([{"filename": "sdxl_src.png", "subfolder": "image"}]),
    )
    db.insert_generation(NewGeneration(
        prompt_id="vid", workflow_name="wan22_i2v", workflow_version="v002",
        positive_prompt="dance", negative_prompt="", seed=3,
        params_json=json.dumps(dict(_WAN_I2V.default_params(), seed=3, noise_seed=9,
                                    positive_prompt="dance", input_image="sdxl_src.png")),
        workflow_json="{}",
    ))
    db.update_generation(
        "vid", status="completed",
        output_files=json.dumps([{"filename": "wan_src.mp4", "subfolder": "video"}]),
    )
    return db


def _select_leaf_of(view, prompt_id):
    item = view._leaf_by_id[prompt_id]
    view._tree.setCurrentItem(item)
    return item.data(0, _GROUP_ROLE).key


def test_i2v_reroll_regenerates_its_input_image_enhances_it_then_makes_the_video(
        qtbot, tmp_path):
    db = _seeded_i2v_db(tmp_path)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_leaf_of(view, "vid")

    _new_tile(view).add_requested.emit()

    img_job = view._live_jobs[key]
    assert img_job.workflow.name == "sdxl_t2i"
    assert img_job.params["seed"] != 7

    client.job_completed.emit(img_job.prompt_id, _IMG_REROLL_HISTORY)

    (enhance_job,) = [job for job in view._jobs.all_jobs if job.enhances]
    assert enhance_job.params["input_image"] == "image/sdxl_new.png [output]"
    enhance_job.finished.emit(
        [{"filename": "image_enhance_new.png", "subfolder": "image", "type": "output"}],
        None, 1.0)
    view._jobs.start_now()

    vid_job = view._live_jobs[key]
    assert vid_job.workflow.name == "wan22_i2v"
    assert vid_job.params["input_image"] == "image/image_enhance_new.png [output]"
    assert vid_job.params["noise_seed"] != 9

    client.job_completed.emit(vid_job.prompt_id, _VID_REROLL_HISTORY)

    assert view._live_jobs == {}
    rows = db.list_generations()
    new_image = next(r for r in rows
                     if r["workflow_name"] == "sdxl_t2i" and r["prompt_id"] != "img")
    new_video = next(r for r in rows
                     if r["workflow_name"] == "wan22_i2v" and r["prompt_id"] != "vid")
    assert "sdxl_new.png" in new_image["output_files"]
    assert "wan_new.mp4" in new_video["output_files"]
    image_rows = [r for r in rows if gallery.media_type_of_row(r) == "image"]
    assert gallery.find_source_image_id(new_video, image_rows) == new_image["prompt_id"]


def _tooltips(view, prompt_id):
    return [b.toolTip() for b in view._gallery_pane._thumb_widgets[prompt_id]._corner_buttons]


def test_i2v_folder_item_carries_both_seed_reroll_hovers(qtbot, tmp_path):
    view = GalleryView(_seeded_i2v_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_leaf_of(view, "vid")

    assert _tooltips(view, "vid") == ["Randomize video seed", "Randomize image seed"], (
        "its start frame is an image that can be made again, so both seeds are offered")


def test_image_folder_item_has_no_seed_reroll_hovers(qtbot, tmp_path):
    view = GalleryView(_seeded_i2v_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_leaf_of(view, "img")

    assert _tooltips(view, "img") == []


def test_a_folder_of_images_made_from_an_image_has_no_seed_reroll_hovers(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(gallery, "is_image_conditioned", lambda workflow_name: True)
    view = GalleryView(_seeded_i2v_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_leaf_of(view, "img")

    assert _tooltips(view, "img") == [], (
        "being made from an image is not enough: an enhanced image starts from one too, and it "
        "has no video seed to offer")


def test_i2v_item_with_a_handpicked_frame_offers_only_the_video_seed(qtbot, tmp_path):
    view = GalleryView(_single_i2v_db(tmp_path, "handpicked.png"), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_leaf_of(view, "vid")

    assert _tooltips(view, "vid") == ["Randomize video seed"], (
        "a hand-picked frame cannot be made again, so only the video's seed is offered")


def test_i2v_item_made_from_a_hidden_starting_frame_offers_only_the_video_seed(qtbot, tmp_path):
    frame = tmp_path / "frames" / "f1.jpg"
    db = _single_i2v_db(tmp_path, str(frame))
    db.insert_rows([{"prompt_id": "f1", "source": GenerationSource.STARTING_FRAME,
                     "workflow_name": "outside:a-site", "workflow_version": "outside",
                     "status": "completed", "params_json": "{}", "workflow_json": "{}",
                     "output_files": json.dumps([{"filename": "f1.jpg", "path": str(frame)}])}])
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_leaf_of(view, "vid")

    assert _tooltips(view, "vid") == ["Randomize video seed"]


def test_an_i2v_item_that_never_named_its_starting_image_offers_no_seed_rerolls(qtbot, tmp_path):
    view = GalleryView(_single_i2v_db(tmp_path, ""), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_leaf_of(view, "vid")

    assert _tooltips(view, "vid") == []


def test_video_seed_hover_rerolls_only_the_item_video_seed(qtbot, tmp_path):
    view = GalleryView(_seeded_i2v_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_leaf_of(view, "vid")
    view._jobs.reroll_video_seed = MagicMock()

    view._gallery_pane._thumb_widgets["vid"]._corner_buttons[0].click()

    view._jobs.reroll_video_seed.assert_called_once()
    _key, row = view._jobs.reroll_video_seed.call_args.args
    assert row["prompt_id"] == "vid"


def test_image_seed_hover_rerolls_only_the_item_image_seed(qtbot, tmp_path):
    view = GalleryView(_seeded_i2v_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_leaf_of(view, "vid")
    view._jobs.reroll_image_seed = MagicMock()

    view._gallery_pane._thumb_widgets["vid"]._corner_buttons[1].click()

    view._jobs.reroll_image_seed.assert_called_once()
    _key, row, _image_rows = view._jobs.reroll_image_seed.call_args.args
    assert row["prompt_id"] == "vid"


def test_poll_reconciles_a_reroll_whose_completion_signal_was_missed(qtbot, tmp_path):
    client = _reroll_client()
    client.fetch_history = MagicMock(return_value=_REROLL_HISTORY)
    db = _seeded_db(tmp_path, seed=7)
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _new_tile(view).add_requested.emit()

    view._poll()

    rows = db.list_generations()
    assert len(rows) == 2
    assert view._live_jobs == {}
    assert key not in view._live_jobs


def test_i2v_reroll_without_a_known_source_image_reuses_the_input(qtbot, tmp_path):
    db = Database(tmp_path / "i2v.db")
    db.insert_generation(NewGeneration(
        prompt_id="vid", workflow_name="wan22_i2v", workflow_version="v002",
        positive_prompt="dance", negative_prompt="", seed=3,
        params_json=json.dumps(dict(_WAN_I2V.default_params(), seed=3, noise_seed=9,
                                    positive_prompt="dance", input_image="outside.png")),
        workflow_json="{}",
    ))
    db.update_generation(
        "vid", status="completed",
        output_files=json.dumps([{"filename": "wan_src.mp4", "subfolder": "video"}]),
    )
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_leaf_of(view, "vid")

    _new_tile(view).add_requested.emit()

    job = view._live_jobs[key]
    assert job.workflow.name == "wan22_i2v"
    assert job.params["input_image"] == "outside.png"
    client.submit_job.assert_called_once()



def test_a_slideshow_is_handed_the_job_queue_worked_out_off_the_listing_in_hand(qtbot):
    db = FakeDB([_image("done", "a cat", 50, 1)])
    db.add(_running_row("gen1", prompt="a dog"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    listings = []
    listing = db.list_generations
    db.list_generations = lambda: listings.append(1) or listing()

    items, _foreign = view.queue_now()

    assert ([item.key for item in items], listings) == (["gen1"], []), (
        "reading both tables again for each slideshow that opened held a double-click up a quarter "
        "of a second more")


def test_latest_shows_an_inflight_tile_above_finished_items(qtbot):
    db = FakeDB([_image("done", "a cat", 50, 1)])
    db.add(_running_row("gen1", prompt="a dog"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    _open_latest(view)

    assert "gen1" in view._gallery_pane._inflight_tiles
    assert view.listed_prompt_ids() == ["done"]


def test_latest_shows_a_live_reroll_as_an_inflight_tile(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.add(_running_row("rr1", prompt="a cat"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    folder_key = _key(_at(_image_workflow(view._tree), 0, 0))
    view._jobs._jobs[folder_key] = [_FakeRerollJob(
        "rr1", "sdxl_t2i", {"positive_prompt": "a cat"}, state="running", frame=_png_bytes()
    )]
    _open_latest(view)

    assert "rr1" in view._gallery_pane._inflight_tiles
    assert not view._gallery_pane._inflight_tiles["rr1"]._image.pixmap().isNull()
    view._gallery_pane._on_inflight_clicked("rr1")
    assert _selected_folder(view) == folder_key


def test_right_clicking_an_inflight_tile_offers_to_cancel_the_run(
        qtbot, tmp_path, monkeypatch):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)
    view.refresh()
    _open_latest(view)
    assert job.prompt_id in view._gallery_pane._inflight_tiles
    labels = _menu_offering(monkeypatch, "gallery_pane", pick="Cancel")

    view._gallery_pane._inflight_context_menu(job.prompt_id, QPoint(0, 0))

    assert labels == [["Cancel"]], (
        "a tile is the whole of what the collection shows of a run being made, and it used to "
        "answer a right-click with nothing at all: stopping the run meant finding it again "
        "among the Job Queue's rows")
    assert view._jobs.all_jobs == []


def test_an_populating_folders_tile_offers_a_cancel_and_a_real_stop(
        qtbot, tmp_path, monkeypatch):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view._toggle_populate(True)
    (job,) = view._jobs.all_jobs
    view.refresh()
    _open_latest(view)
    labels = _menu_offering(monkeypatch, "gallery_pane")

    view._gallery_pane._inflight_context_menu(job.prompt_id, QPoint(0, 0))

    assert labels == [["Cancel", "Cancel and stop populating"]]


def test_canceling_from_an_populating_folders_tile_ends_populate_too(
        qtbot, tmp_path, monkeypatch):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_populate(True)
    (job,) = view._jobs.all_jobs
    view.refresh()
    _open_latest(view)
    _menu_offering(monkeypatch, "gallery_pane", pick="Cancel and stop")

    view._gallery_pane._inflight_context_menu(job.prompt_id, QPoint(0, 0))

    assert not view._populate.is_active(key)
    assert view._jobs.all_jobs == [], (
        "Populate goes off first: a discard while it is still on is the cue for the next seed, "
        "so canceling first would start one")


def test_a_tile_with_no_live_job_behind_it_raises_no_menu(qtbot, monkeypatch):
    db = FakeDB([_image("done", "a cat", 50, 1)])
    db.add(_running_row("gen1"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    _open_latest(view)
    assert "gen1" in view._gallery_pane._inflight_tiles
    labels = _menu_offering(monkeypatch, "gallery_pane")

    view._gallery_pane._inflight_context_menu("gen1", QPoint(0, 0))

    assert labels == []


def test_right_clicking_a_folders_live_tile_offers_to_cancel_the_run(
        qtbot, tmp_path, monkeypatch):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key, _job = _running_reroll(view)
    labels = _menu_offering(monkeypatch, "gallery_view", pick="Cancel")

    view._generating_tile_menu(key, QPoint(0, 0))

    assert labels == [["Cancel"]], (
        "the same act as the button on the tile's face, on the gesture the rest of the Gallery "
        "pane answers")
    assert view._jobs.all_jobs == []


def test_an_populating_folders_live_tile_offers_the_stop_its_button_cannot(
        qtbot, tmp_path, monkeypatch):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_populate(True)
    labels = _menu_offering(monkeypatch, "gallery_view", pick="Cancel and stop")

    view._generating_tile_menu(key, QPoint(0, 0))

    assert labels == [["Cancel", "Cancel and stop populating"]]
    assert not view._populate.is_active(key)
    assert view._jobs.all_jobs == []


def _running_in_folder(prompt_id, prompt, steps, seed):
    return _row(prompt_id, "sdxl_t2i",
                {"positive_prompt": prompt, "steps": steps, "seed": seed},
                f"{prompt_id}.png", status="running", output_files="[]")


def test_open_folder_shows_a_running_generation_on_its_generating_tile(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)

    assert _generating_tile(view) is not None, (
        "a tab's Generate is a re-roll, so a generation running in a folder is the folder's "
        "generating tile")
    assert job.prompt_id not in view._gallery_pane._inflight_tiles, (
        "its running row must not also appear as a separate in-flight tile in that folder")
    assert job.prompt_id not in view.listed_prompt_ids()
    assert view.listed_prompt_ids() == ["orig"]


def test_open_folder_omits_a_running_row_from_the_static_grid(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.add(_running_in_folder("run1", "a cat", 50, 2))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._leaf_by_id["i1"])

    assert "run1" in view._gallery_pane._inflight_tiles
    assert view.listed_prompt_ids() == ["i1"]


def test_open_folder_does_not_double_show_a_reroll_running_in_it(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)

    view._rerender_current_leaf()

    assert _generating_tile(view) is not None
    assert job.prompt_id not in view._gallery_pane._inflight_tiles


def test_a_reroll_finishing_drops_its_inflight_tile(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.add(_running_row("rr1", prompt="a cat"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    folder_key = _key(_at(_image_workflow(view._tree), 0, 0))
    view._jobs._jobs[folder_key] = [
        _FakeRerollJob("rr1", "sdxl_t2i", {"positive_prompt": "a cat"})]
    _open_latest(view)
    assert "rr1" in view._gallery_pane._inflight_tiles

    view._live_jobs.pop(folder_key)
    db.delete_generation("rr1")
    db.add(_row("rr1", "sdxl_t2i", {"positive_prompt": "a cat"}, "rr1.png"))
    view._poll()
    assert "rr1" not in view._gallery_pane._inflight_tiles


def test_inflight_tile_frame_updates_in_place_without_a_rerender(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.add(_running_row("rr1", prompt="a cat"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    folder_key = _key(_at(_image_workflow(view._tree), 0, 0))
    job = _FakeRerollJob("rr1", "sdxl_t2i", {"positive_prompt": "a cat"}, frame=None)
    view._jobs._jobs[folder_key] = [job]
    _open_latest(view)
    tile = view._gallery_pane._inflight_tiles["rr1"]

    job.last_preview = _png_bytes()
    view._poll()
    assert view._gallery_pane._inflight_tiles["rr1"] is tile
    assert not tile._image.pixmap().isNull()


def test_latest_collection_appears_for_a_running_generation(qtbot):
    view = GalleryView(FakeDB([_running_row("gen1")]))
    qtbot.addWidget(view)
    view.refresh()

    assert "Latest" in _alls(view._tree)
    _open_latest(view)
    assert "gen1" in view._gallery_pane._inflight_tiles


def test_inflight_running_tiles_sort_before_queued(qtbot):
    db = FakeDB([
        _row("waiting", "sdxl_t2i", {"positive_prompt": "w"}, "waiting.png",
             status="pending", output_files="[]"),
        _row("going", "sdxl_t2i", {"positive_prompt": "g"}, "going.png",
             status="running", output_files="[]"),
    ])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    assert [it.key for it in view._inflight_items()] == ["going", "waiting"]


def _queued_job(prompt_id, state="idle"):
    return SimpleNamespace(prompt_id=prompt_id, media_type="image", source="generated",
                           state=state, shielded=False)


def test_inflight_items_follow_the_order_the_queue_will_run_them_in(qtbot):
    db = FakeDB([
        _row("first", "sdxl_t2i", {"positive_prompt": "a"}, "a.png",
             status="pending", output_files="[]"),
        _row("second", "sdxl_t2i", {"positive_prompt": "b"}, "b.png",
             status="pending", output_files="[]"),
    ])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view._jobs._waiting = [_queued_job("second"), _queued_job("first")]
    view.refresh()

    assert [it.key for it in view._inflight_items()] == ["second", "first"]


def test_a_row_the_line_holds_no_job_for_sorts_to_the_back(qtbot):
    db = FakeDB([
        _row("known", "sdxl_t2i", {"positive_prompt": "a"}, "a.png",
             status="pending", output_files="[]"),
        _row("brand-new", "sdxl_t2i", {"positive_prompt": "b"}, "b.png",
             status="pending", output_files="[]"),
    ])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view._jobs._waiting = [_queued_job("known")]
    view.refresh()

    assert [it.key for it in view._inflight_items()] == ["known", "brand-new"], (
        "a row a restart has not taken back has no place in the queue's order; it waits at the end")


def test_the_queue_shows_the_active_job_then_empties_when_idle(qtbot):
    db = FakeDB([_image("done", "a cat", 50, 1)])
    db.add(_running_row("gen1", prompt="a dog"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    with qtbot.waitExposed(view):
        view.show()

    assert view._queue.isVisible()
    assert view._queue.keys() == ["gen1"]
    assert view._queue._running.key == "gen1"

    db.delete_generation("gen1")
    view._poll()
    assert view._queue.isVisible()
    assert view._queue.keys() == []
    assert view._queue._running.key is None


def test_an_open_slideshow_is_fed_the_same_queue_the_strip_shows(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    db = FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)])
    db.add(_running_row("gen1", prompt="a dog"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)

    view._slideshows.start()
    qtbot.addWidget(view._slideshows.showing.shown)
    slideshow = view._slideshows.showing

    assert [item.key for item in slideshow.shown.queue_foot.hud_queue[0]] == view._queue.keys() == ["gen1"]
    assert queue_section(*slideshow.shown.queue_foot.hud_queue).leader.key == "gen1"

    db.delete_generation("gen1")
    view._poll()
    assert queue_section(*slideshow.shown.queue_foot.hud_queue).lines == ()

    slideshow.close()


def test_a_row_dragged_in_the_slideshows_queue_moves_the_job_and_redraws_both_at_once(
        qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.add(_running_row("gen1", prompt="a dog"))
    db.add(_row("w1", "sdxl_t2i", {"positive_prompt": "w"}, "w.png",
                status="pending", output_files="[]"))
    db.add(_row("w2", "sdxl_t2i", {"positive_prompt": "x"}, "x.png",
                status="pending", output_files="[]"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view._jobs._on_server = [_queued_job("gen1", state="running")]
    view._jobs._waiting = [_queued_job("w1"), _queued_job("w2")]
    view.refresh()
    _select_first_leaf(view)
    view._slideshows.start()
    qtbot.addWidget(view._slideshows.showing.shown)
    slideshow = view._slideshows.showing

    slideshow.shown.queue_foot.move("w2", "w1")

    assert [item.key for item in slideshow.shown.queue_foot.hud_queue[0]] == ["gen1", "w2", "w1"], (
        "not a poll later: a row that sits still after the drop reads as one missed")
    assert view._queue.keys() == ["gen1", "w2", "w1"]
    view._slideshows.showing.close()


def test_the_queue_lists_every_waiting_job_not_just_the_running_one(qtbot):
    db = FakeDB([
        _running_row("running-one", prompt="a dog"),
        _row("waiting-one", "sdxl_t2i", {"positive_prompt": "w"}, "w.png",
             status="pending", output_files="[]"),
    ])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    assert view._queue.keys() == ["running-one", "waiting-one"]


def test_a_queue_row_let_go_elsewhere_is_moved_there_and_redrawn_at_once(qtbot):
    db = FakeDB([
        _running_row("running-one", prompt="a dog"),
        _row("w1", "sdxl_t2i", {"positive_prompt": "w"}, "w.png",
             status="pending", output_files="[]"),
        _row("w2", "sdxl_t2i", {"positive_prompt": "x"}, "x.png",
             status="pending", output_files="[]"),
    ])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view._jobs._on_server = [_queued_job("running-one", state="running")]
    view._jobs._waiting = [_queued_job("w1"), _queued_job("w2")]
    view.refresh()

    view._queue.move_requested.emit("w2", "w1")

    assert view._jobs.queue_order == ["running-one", "w2", "w1"]
    assert view._queue.keys() == ["running-one", "w2", "w1"]


def test_clicking_a_queue_row_opens_that_jobs_folder(qtbot):
    db = FakeDB([_running_row("gen1", prompt="a dog")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    folder = gallery.settings_folder_key(
        db.get_generation("gen1"), gallery.build_image_config_index(view._image_rows))
    view._select_reroll = MagicMock()

    view._inflight_items()[0].reveal()

    assert _selected_folder(view) == folder, (
        "a queue row is a place in the gallery, not a settings form")
    view._select_reroll.assert_called_once_with(folder)


def test_clicking_an_enhancements_row_in_the_queue_goes_to_its_image(qtbot, tmp_path):
    view = GalleryView(_enhanceable_db(tmp_path, count=2), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view.enhance_items(["g1"])
    view._tree.setCurrentItem(_image_workflow(view._tree))
    view._update_queue()
    (row,) = view._queue.rows()

    qtbot.mouseClick(row, Qt.MouseButton.LeftButton)

    assert view.selected_prompt_ids() == ["g1"]
    assert view._gallery_pane._thumb_widgets["g1"]._selected
    assert view._generate_pane.current_generate_tab().displayed_row()["prompt_id"] == "g1"


def test_the_strip_times_the_job_against_the_workflows_recent_runs(qtbot):
    db = FakeDB([
        _row("v1", "wan22_i2v", {"seed": 1}, "wan22_i2v_1.mp4", duration_seconds=700.0),
        _row("v2", "wan22_i2v", {"seed": 2}, "wan22_i2v_2.mp4", duration_seconds=724.0),
        _row("v3", "wan22_i2v", {"seed": 3}, "wan22_i2v_3.mp4", duration_seconds=800.0),
    ])
    db.add(_running_row("rr1", workflow="wan22_i2v"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    folder_key = _running_folder_key(view)
    began = time.time() - 90.5
    view._jobs._jobs[folder_key] = [_FakeRerollJob(
        "rr1", "wan22_i2v", {}, state="running", progress=(10, 20), started_at=began
    )]

    item = view._inflight_items()[0]
    assert item.reading.started_at == began
    assert item.reading.typical_seconds == 724.0

    view._update_queue()
    assert view._queue._running.status_text() == "50% · 1:30 elapsed · ~6:02 left"


def test_the_strip_has_no_clock_for_a_job_still_queued(qtbot):
    db = FakeDB([_image("done", "a cat", 50, 1)])
    db.add(_row("waiting", "sdxl_t2i", {"positive_prompt": "w"}, "waiting.png",
                status="pending", output_files="[]"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    assert view._inflight_items()[0].reading.started_at is None, (
        "nothing has begun, so there is no elapsed time to report: the wait on ComfyUI is the "
        "queue beside it to explain")
    assert view._queue._running.status_text() == ""


def test_a_queued_job_carries_what_the_strip_leads_its_row_with(qtbot):
    db = FakeDB([
        _row("v1", "wan22_i2v", {"seed": 1}, "wan22_i2v_1.mp4", duration_seconds=120.0),
    ])
    db.add(_running_row("rr1", workflow="wan22_i2v"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    item = view._inflight_items()[0]
    assert item.job_kind == "Video"
    assert item.reading.typical_seconds == 120.0


def test_a_job_a_spoken_request_queued_says_so(qtbot):
    db = FakeDB([_image("src", "a kite", 50, 1)])
    db.add(_running_row("asked", prompt="a kite, no string"))
    db.record_request(NewRequest(prompt_id="asked", source_prompt_id="src",
                      heard="Request, no string, over."))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    items = {it.key: it for it in view._inflight_items()}
    assert items["asked"].requested


def test_a_job_nobody_asked_for_out_loud_is_not_marked(qtbot):
    db = FakeDB([_image("src", "a kite", 50, 1)])
    db.add(_running_row("typed", prompt="a kite"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    assert not view._inflight_items()[0].requested


def test_an_image_conditioned_job_carries_the_frame_it_starts_from(qtbot):
    db = FakeDB([])
    db.add(_row("rr1", "wan22_i2v", {"input_image": "kite_00007_.png [output]"},
                "rr1.mp4", status="running", output_files="[]"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    assert view._inflight_items()[0].source_image == "kite_00007_.png [output]"


def test_an_enhancement_carries_the_image_it_is_a_second_pass_over(qtbot):
    db = FakeDB([])
    db.add(_row("en1", "image_enhance", {"input_image": "kite_00007_.png [output]"},
                "en1.png", status="running", output_files="[]"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    assert view._inflight_items()[0].source_image == "kite_00007_.png [output]"


def test_an_image_that_takes_an_input_is_still_placed_by_its_folder(qtbot):
    db = FakeDB([])
    db.add(_row("pt1", "sdxl_pose_transfer", {"input_image": "pose_00002_.png [output]"},
                "pt1.png", status="running", output_files="[]"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    item = view._inflight_items()[0]
    assert item.job_kind == "Image"
    assert item.source_image is None


def test_a_job_started_from_words_alone_names_no_frame(qtbot):
    db = FakeDB([_image("done", "a kite", 50, 1)])
    db.add(_running_row("gen1", prompt="a kite"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    items = {it.key: it for it in view._inflight_items()}
    assert items["gen1"].source_image is None


def test_a_dropped_video_combine_carries_the_clip_it_follows(qtbot):
    db = FakeDB([])
    db.add(_row("source", "wan22_i2v", {"positive_prompt": "dance"}, "source.mp4",
                thumbnail_path="thumbs/source.jpg"))
    db.add(_row("rr1", "wan22_i2v", {"input_image": "kite_00007_.png [output]"},
                "rr1.mp4", status="running", output_files="[]",
                source_video="source"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    item = {it.key: it for it in view._inflight_items()}["rr1"]
    assert item.action == ""
    assert item.source_video_thumbnail == "thumbs/source.jpg"


@pytest.mark.parametrize(("prompt", "stands_apart"), [("dance", False),
                                                      ("dance in the rain", True)])
def test_a_combine_whose_words_left_its_source_videos_says_so_on_its_row(qtbot, prompt, stands_apart):
    db = FakeDB([])
    db.add(_row("source", "wan22_i2v", {"positive_prompt": "dance"}, "source.mp4",
                thumbnail_path="thumbs/source.jpg"))
    db.add(_row("rr1", "wan22_i2v",
                {"positive_prompt": prompt, "input_image": "kite_00007_.png [output]"},
                "rr1.mp4", status="running", output_files="[]", source_video="source"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    item = {it.key: it for it in view._inflight_items()}["rr1"]
    assert item.prompt_edited is stands_apart


def test_a_picked_action_shows_no_source_video_at_all(qtbot):
    db = FakeDB([])
    db.add(_row("source", "wan22_i2v", {"positive_prompt": "dance"}, "source.mp4",
                thumbnail_path="thumbs/source.jpg"))
    db.add(_row("rr1", "wan22_i2v", {"input_image": "kite_00007_.png [output]"},
                "rr1.mp4", status="running", output_files="[]",
                action="dancing", source_video="source"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    item = {it.key: it for it in view._inflight_items()}["rr1"]
    assert item.action == "dancing"
    assert item.source_video_thumbnail is None, (
        "the action names what the video will do, which is the whole of what was chosen: the "
        "video its settings were mined out of answers a question nobody asked, and an image of "
        "a video the user never picked reads as a job that is that video")


def test_a_run_that_came_from_no_combine_carries_neither(qtbot):
    db = FakeDB([])
    db.add(_row("rr1", "wan22_i2v", {"input_image": "kite_00007_.png [output]"},
                "rr1.mp4", status="running", output_files="[]"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    item = view._inflight_items()[0]
    assert item.action == ""
    assert item.source_video_thumbnail is None


def test_a_queued_job_carries_a_few_thumbnails_from_the_folder_it_joins(qtbot):
    settings = {"positive_prompt": "a kite", "steps": 50}
    db = FakeDB([])
    for i in range(6):
        db.add(_row(f"done{i}", "sdxl_t2i", {**settings, "seed": i}, f"done{i}.png",
                    thumbnail_path=f"thumbs/done{i}.jpg"))
    db.add(_row("waiting", "sdxl_t2i", {**settings, "seed": 99}, "waiting.png",
                status="pending", output_files="[]"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    items = {it.key: it for it in view._inflight_items()}
    assert items["waiting"].folder_thumbnails == (
        "thumbs/done5.jpg", "thumbs/done4.jpg", "thumbs/done3.jpg", "thumbs/done2.jpg",
    ), (
        "a queued job's own output does not exist yet, so its row can only be recognized by "
        "thumbnails of something else: what its folder already holds says where the run is "
        "headed, newest first, since the newest are what the user was just looking at")


def test_the_first_run_of_new_settings_has_no_folder_to_show(qtbot):
    db = FakeDB([_image("elsewhere", "a boat", 50, 1)])
    db.add(_row("waiting", "sdxl_t2i", {"positive_prompt": "a kite", "steps": 12},
                "waiting.png", status="pending", output_files="[]"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    items = {it.key: it for it in view._inflight_items()}
    assert items["waiting"].folder_thumbnails == ()


def _running_folder_key(view):
    return gallery.settings_folder_key(
        view._db.get_generation("rr1"),
        gallery.build_image_config_index(view._image_rows),
    )


def _finished_row_db(tmp_path):
    db = Database(tmp_path / "t.db")
    p = dict(_SDXL.default_params(), seed=1, positive_prompt="a cat")
    db.insert_generation(NewGeneration(prompt_id="done", workflow_name="sdxl_t2i", workflow_version="v",
                         positive_prompt="a cat", seed=1,
                         params_json=json.dumps(p), workflow_json="{}"))
    db.update_generation("done", status="completed",
                         output_files=json.dumps([{"filename": "sdxl_t2i_done.png"}]))
    return db


def _history_of_a_run_still_going(prompt_id):
    return {}


def test_generate_inflight_tile_persists_across_navigation_and_polls(qtbot, tmp_path):
    client = ComfyUIClient(folders=SUITE_FOLDERS)
    client.submit_job = lambda payload, prompt_id: prompt_id
    client.fetch_history = _history_of_a_run_still_going
    db = _finished_row_db(tmp_path)
    gv = GalleryView(db, client=client)
    qtbot.addWidget(gv)
    gv.refresh()
    gv._generate_pane._add_subtab()
    tab = _tab_with_prompts(gv)
    tab._param_form.set_values({"seed": 2, "positive_prompt": "a dog"})
    tab._on_generate()
    (pid,) = [job.prompt_id for job in gv._live_jobs.values()]

    gv._tree.setCurrentItem(_collection(gv, LATEST_KEY))
    assert pid in gv._gallery_pane._inflight_tiles

    folder = _at(_image_workflow(gv._tree), 0, 0)
    gv._tree.setCurrentItem(folder)
    gv._tree.setCurrentItem(_collection(gv, LATEST_KEY))
    assert pid in gv._gallery_pane._inflight_tiles, "card vanished after navigating away and back"

    gv._poll()
    assert pid in gv._gallery_pane._inflight_tiles, "card vanished after a poll"


def test_reroll_inflight_tile_persists_across_navigation_and_polls(qtbot, tmp_path):
    client = ComfyUIClient(folders=SUITE_FOLDERS)
    client.submit_job = lambda payload, prompt_id: prompt_id
    client.fetch_history = _history_of_a_run_still_going
    db = _finished_row_db(tmp_path)
    gv = GalleryView(db, client=client)
    qtbot.addWidget(gv)
    gv.refresh()

    folder_key = gallery.settings_folder_key(db.get_generation("done"))
    gv._start_reroll(folder_key)
    rr_pid = gv._live_jobs[folder_key].prompt_id

    gv._tree.setCurrentItem(_collection(gv, LATEST_KEY))
    assert rr_pid in gv._gallery_pane._inflight_tiles

    gv._tree.setCurrentItem(gv._tree_item_for(folder_key))
    gv._tree.setCurrentItem(_collection(gv, LATEST_KEY))
    assert rr_pid in gv._gallery_pane._inflight_tiles, "re-roll card vanished after navigation"

    gv._poll()
    assert rr_pid in gv._gallery_pane._inflight_tiles, "re-roll card vanished after a poll"


def test_i2v_reroll_inflight_tile_follows_the_image_to_video_handoff(qtbot, tmp_path):
    db = _seeded_i2v_db(tmp_path)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_leaf_of(view, "vid")
    _new_tile(view).add_requested.emit()
    img_job = view._live_jobs[key]

    view._tree.setCurrentItem(_collection(view, LATEST_KEY))
    assert img_job.prompt_id in view._gallery_pane._inflight_tiles

    client.job_completed.emit(img_job.prompt_id, _IMG_REROLL_HISTORY)
    vid_job = view._live_jobs[key]
    assert vid_job.prompt_id != img_job.prompt_id

    view._poll()
    assert vid_job.prompt_id in view._gallery_pane._inflight_tiles, "video-stage card missing after handoff"

    view._tree.setCurrentItem(view._tree_item_for(key))
    view._tree.setCurrentItem(_collection(view, LATEST_KEY))
    assert vid_job.prompt_id in view._gallery_pane._inflight_tiles, "video-stage card missing after navigation"


def test_latest_shows_a_running_reroll_row_with_no_live_job(qtbot, tmp_path):
    db = _finished_row_db(tmp_path)
    p = dict(_SDXL.default_params(), seed=5, positive_prompt="a wolf")
    db.insert_generation(NewGeneration(prompt_id="rr_running", workflow_name="sdxl_t2i",
                         workflow_version="v", positive_prompt="a wolf", seed=5,
                         params_json=json.dumps(p), workflow_json="{}"))
    db.update_generation("rr_running", status="running")
    gv = GalleryView(db, client=ComfyUIClient(folders=SUITE_FOLDERS))
    qtbot.addWidget(gv)
    gv.refresh()
    gv._tree.setCurrentItem(_collection(gv, LATEST_KEY))

    assert "rr_running" in gv._gallery_pane._inflight_tiles



def test_generate_shows_the_front_tabs_cancel_button(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    tab = _front_panel(view)
    tab.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a brand new prompt"))

    tab._on_generate()

    assert view._live_jobs
    assert tab._cancel_btn.isHidden() is False


def _two_image_db(tmp_path, prompts=("the first one", "a completely different one")):
    db = Database(tmp_path / "t.db")
    for (pid, prompt), seed in zip(zip(("a", "b"), prompts, strict=True), (7, 8), strict=True):
        params = dict(_SDXL.default_params(), seed=seed, positive_prompt=prompt)
        db.insert_generation(NewGeneration(prompt_id=pid, workflow_name="sdxl_t2i",
                             workflow_version=_SDXL.version, positive_prompt=prompt,
                             seed=seed, params_json=json.dumps(params), workflow_json="{}"))
        db.update_generation(pid, status="completed",
                             output_files=json.dumps([{"filename": f"sdxl_{pid}.png",
                                                       "subfolder": ""}]))
    return db


def _click_thumbnail(view, row, image_rows):
    view._generate_pane.load_selection(row, image_rows)
    return _front_panel(view)


def test_another_image_of_the_folder_being_generated_cannot_be_generated_too(qtbot, tmp_path):
    db = _two_image_db(tmp_path, prompts=("a shared prompt", "a shared prompt"))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    rows = {r["prompt_id"]: r for r in db.list_generations()}
    image_rows = list(rows.values())
    first = _click_thumbnail(view, rows["a"], image_rows)
    first.use_random_seed()
    first._on_generate()
    assert len(view._jobs.all_jobs) == 1

    tab = _click_thumbnail(view, rows["b"], image_rows)

    assert tab is first
    assert tab._generating is False, (
        "a tab pointed at another image lets go of the run it launched, so its Generate button is "
        "read again at once")
    assert tab._generate_btn.isEnabled() is False

    tab.use_random_seed()
    tab._on_generate()

    assert len(view._jobs.all_jobs) == 1


def test_another_images_tab_can_still_generate_while_the_first_runs(qtbot, tmp_path):
    db = _two_image_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    rows = {r["prompt_id"]: r for r in db.list_generations()}
    image_rows = list(rows.values())
    view._generate_pane.load_selection(rows["a"], image_rows)
    first = _front_panel(view)
    first._param_form.set_values({"positive_prompt": "a re-roll of the first one"})
    first._on_generate()

    view._generate_pane.load_selection(rows["b"], image_rows)

    second = _front_panel(view)
    assert second is not first
    assert second._generating is False
    assert second._generate_btn.text() == "Generate"
    assert second._generate_btn.isEnabled() is True
    assert second._cancel_btn.isHidden() is True


def test_a_setting_that_moves_the_folder_frees_generate_and_moving_back_grays_it(
        qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    tab = _front_panel(view)
    tab.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a brand new prompt"))
    tab.use_random_seed()
    tab._on_generate()
    assert tab._generate_btn.isEnabled() is False
    steps = tab._param_form._widgets["steps"]

    steps.setValue(_SDXL.default_params()["steps"] + 1)

    assert tab._generate_btn.isEnabled() is True
    qtbot.waitUntil(lambda: "already making" not in tab._generate_btn.toolTip())

    steps.setValue(_SDXL.default_params()["steps"])

    assert tab._generate_btn.isEnabled() is False
    qtbot.waitUntil(lambda: "already making" in tab._generate_btn.toolTip())


def _a_run_launched_from_the_front_tab(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    tab = _front_panel(view)
    tab.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a brand new prompt"))
    tab._on_generate()
    job = next(iter(view._live_jobs.values()))
    assert tab._cancel_btn.isHidden() is False
    return client, view, tab, job


def test_finishing_a_reroll_hides_the_front_tabs_cancel_button(qtbot, tmp_path):
    client, view, tab, job = _a_run_launched_from_the_front_tab(qtbot, tmp_path)

    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)

    assert view._live_jobs == {}
    assert tab._cancel_btn.isHidden() is True
    assert tab._generate_btn.isEnabled() is True


def test_finishing_a_reroll_hides_the_cancel_button_of_a_tab_under_another(qtbot, tmp_path):
    client, view, launcher, job = _a_run_launched_from_the_front_tab(qtbot, tmp_path)
    in_front = view._generate_pane._add_subtab()

    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)

    assert view._generate_pane.current_generate_tab() is in_front
    assert launcher._cancel_btn.isHidden() is True, (
        "every tab is set against the runs in flight, not just the front one, so a tab now "
        "under another still shows what its own run is doing")


def test_a_tabs_cancel_stops_its_run_and_hands_the_folder_back(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    tab = _front_panel(view)
    tab.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a brand new prompt"))
    tab.use_random_seed()
    tab._on_generate()
    (being_made,) = [job.prompt_id for job in view._jobs.all_jobs]

    tab._cancel_btn.click()

    assert view._jobs.all_jobs == []
    assert view._db.get_generation(being_made) is None
    assert tab._generating is False
    assert tab._generate_btn.isEnabled() is True

    tab._on_generate()

    assert len(view._jobs.all_jobs) == 1


def test_cancel_works_on_a_run_launched_from_a_clicked_image(qtbot, tmp_path):
    db = _two_image_db(tmp_path, prompts=("a shared prompt", "a shared prompt"))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    rows = {r["prompt_id"]: r for r in db.list_generations()}
    tab = _click_thumbnail(view, rows["a"], list(rows.values()))
    tab.use_random_seed()
    tab._on_generate()
    prompt_id = view._jobs.all_jobs[0].prompt_id
    assert tab._cancel_btn.isHidden() is False

    tab = _front_panel(view)
    tab._cancel_btn.click()

    assert view._jobs.all_jobs == []
    assert view._db.get_generation(prompt_id) is None


def test_clicking_the_tabs_cancel_button_stops_its_run(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    tab = _front_panel(view)
    tab.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a brand new prompt"))
    tab._on_generate()
    prompt_id = next(iter(view._live_jobs.values())).prompt_id

    tab._cancel_btn.click()

    assert view._jobs.all_jobs == []
    assert view._db.get_generation(prompt_id) is None


def test_canceling_from_the_front_tab_stops_the_reroll(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    tab = _front_panel(view)
    tab.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a brand new prompt"))
    tab._on_generate()
    prompt_id = next(iter(view._live_jobs.values())).prompt_id
    assert view._db.get_generation(prompt_id) is not None

    tab.cancel_requested.emit()

    assert view._live_jobs == {}
    assert view._db.get_generation(prompt_id) is None
    assert tab._cancel_btn.isHidden() is True


def _edited_tab_showing_the_saved_image(view, qtbot):
    panel = _front_panel(view)
    row = view._db.get_generation("orig")
    panel.show_saved_generation(row, [row])
    field = panel._param_form._widgets["positive_prompt"].boxes()[0]
    field.setPlainText("a dog")
    qtbot.waitUntil(lambda: _struck_and_lit(field) == ("cat", "dog"), timeout=5000)
    return panel, field


def test_canceling_a_generate_brings_back_how_the_prompt_differs_from_the_item_shown(
        qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel, field = _edited_tab_showing_the_saved_image(view, qtbot)
    panel._on_generate()
    assert _struck_and_lit(field) == ("", "")

    panel.cancel_requested.emit()

    assert _struck_and_lit(field) == ("cat", "dog")


def test_a_generate_on_an_image_a_request_made_leaves_its_prompt_plain(
        qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    db.record_request(NewRequest(prompt_id="orig", source_prompt_id="src", heard="", asked="no bird",
                      old_positive="a bird", old_negative="",
                      new_positive="a cat", new_negative=""))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel = _front_panel(view)
    row = db.get_generation("orig")
    panel.show_saved_generation(row, [row])
    field = panel._param_form._widgets["positive_prompt"].boxes()[0]
    assert _struck_and_lit(field) == ("", "")

    panel._on_generate()

    assert panel.launched_runs()
    assert _struck_and_lit(field) == ("", "")


def test_a_generate_that_lands_leaves_the_prompt_plain_under_what_it_made(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel, field = _edited_tab_showing_the_saved_image(view, qtbot)
    panel._on_generate()

    _finish_reroll(view, next(iter(view._live_jobs.values())))

    assert panel.launched_runs() == []
    assert _struck_and_lit(field) == ("", "")


def test_a_duplicate_generate_switches_the_front_tab_to_a_random_seed(qtbot, tmp_path):
    db = _seeded_db(tmp_path, seed=42)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    tab = _front_panel(view)
    tab.prefill("sdxl_t2i", dict(_SDXL.default_params(), seed=42, positive_prompt="a cat"))
    assert tab.current_config().seed_is_random is False

    tab._on_generate()

    assert tab.current_config().seed_is_random is True


def test_a_landed_generation_tells_an_open_tab_its_seed_is_now_a_duplicate(qtbot, tmp_path):
    db = Database(tmp_path / "test.db")
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    tab = _front_panel(view)
    params = dict(_SDXL.default_params(), seed=42, positive_prompt="a cat")
    tab.prefill("sdxl_t2i", params)
    qtbot.waitUntil(lambda: not tab._caption_timer.isActive())
    assert tab._generate_btn.text() == "Generate"

    db.insert_generation(NewGeneration(
        prompt_id="done", workflow_name="sdxl_t2i", workflow_version=_SDXL.version,
        positive_prompt="a cat", negative_prompt="", seed=42,
        params_json=json.dumps(params), workflow_json="{}",
    ))
    db.update_generation("done", status="completed", output_files=json.dumps(
        [{"filename": "sdxl_done.png", "subfolder": ""}]))
    view.refresh()

    qtbot.waitUntil(lambda: tab._generate_btn.text() == "Generate with Random seed")


def test_the_random_seed_survives_a_cancel_so_re_generate_is_another_variation(
        qtbot, tmp_path, monkeypatch):
    asked = []
    for question in ("question", "information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, question, staticmethod(lambda *a, **kw: asked.append(a)))
    monkeypatch.setattr(QMessageBox, "exec", lambda box: asked.append(box.text()))
    db = _seeded_db(tmp_path, seed=42)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    tab = _front_panel(view)
    tab.prefill("sdxl_t2i", dict(_SDXL.default_params(), seed=42, positive_prompt="a cat"))

    tab._on_generate()
    assert asked == [], "a Generate over a duplicate takes a fresh seed, no question asked"
    first = next(iter(view._live_jobs.values())).params["seed"]
    key = next(iter(view._live_jobs))
    view._cancel_reroll(key)
    assert view._live_jobs == {}

    tab._on_generate()

    launched = next(iter(view._live_jobs.values())).params["seed"]
    assert launched not in (42, first)


def test_unticking_random_after_a_generate_keeps_the_seed_that_made_it(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    tab = _front_panel(view)
    tab.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a brand new prompt"))
    tab._param_form.set_seed_random(True)
    tab._on_generate()
    (made,) = view._live_jobs.values()
    _finish_reroll(view, made)

    tab._param_form.set_seed_random(False)
    tab._param_form._widgets["positive_prompt"].boxes()[0].setPlainText(
        "a brand new prompt, at dusk")
    tab._on_generate()

    (tweaked,) = view._live_jobs.values()
    assert tweaked.params["seed"] == made.params["seed"]



def test_pressing_generate_shows_a_row_before_there_is_a_job(qtbot, tmp_path, monkeypatch):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    deferred = []
    monkeypatch.setattr(view._combine, "_after_painting", deferred.append)

    view._combine.widget.combine_requested.emit(
        CombineRequest(image_id="img", video_id="vid",
                       intent=view._combine.widget.selected_intent()))

    assert len(view._queue.rows()) == 1, (
        "checking every stored generation for a duplicate, building the settings and posting "
        "the prompt all run on the window's thread; with nothing on screen for that stretch the "
        "button reads as one that did nothing")
    row, = view._queue.rows()
    assert row._note_text == "Starting…", (
        "the launch itself is left for the next turn of the event loop: run at once, nothing is "
        "painted while it works, and the stand-in row would show only once the work it stood in "
        "for was over")
    assert view._live_jobs == {}

    deferred[0]()

    assert len(view._live_jobs) == 1
    assert not any(item.starting for item in view._queue._items)


def test_the_stand_in_row_already_carries_the_action_that_was_picked(qtbot, tmp_path, monkeypatch):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(view._combine, "_after_painting", lambda work: None)

    view._combine._on_generate_category("img", "dancing", action_settings.VIDEO)

    item = view._queue._items[0]
    assert item.action == "dancing", (
        "it is the row that will replace it, minus the price, so the line does not blink one "
        "thing away and a different-looking one in")
    assert item.source_image == "sdxl_pick.png [output]"
    assert item.source_video_thumbnail is None
    assert item.cancel is None


def test_the_stand_in_row_shows_the_dropped_video(qtbot, tmp_path, monkeypatch):
    db = _combine_db(tmp_path)
    db.update_generation("vid", thumbnail_path="thumbs/vid.jpg")
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(view._combine, "_after_painting", lambda work: None)

    view._combine.widget.combine_requested.emit(
        CombineRequest(image_id="img", video_id="vid",
                       intent=view._combine.widget.selected_intent()))

    item = view._queue._items[0]
    assert item.source_video_thumbnail == "thumbs/vid.jpg"
    assert item.action == ""


def test_the_stand_in_row_goes_when_the_action_has_no_past_video(qtbot, tmp_path, monkeypatch):
    db = _combine_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(gallery_view_module.QMessageBox, "information", lambda *a, **k: None)

    view._combine._on_generate_category("img", "epsilon", action_settings.VIDEO)

    assert view._queue.rows() == []
    assert view._live_jobs == {}


def test_the_stand_in_row_goes_when_the_dropped_image_is_gone(qtbot, tmp_path, monkeypatch):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._on_generate_category("missing", "dancing", action_settings.VIDEO)

    assert view._queue.rows() == []


def test_a_row_standing_in_for_an_image_waits_in_front_of_the_videos(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view._jobs.start_prepared("video/a", _WAN_I2V, dict(_WAN_I2V.default_params(), seed=3))
    view._jobs.start_prepared("video/b", _WAN_I2V, dict(_WAN_I2V.default_params(), seed=4))
    making, waiting = view._jobs.queue_order

    standing = view._starting.show(caption="An image from a Request, still being started",
                                   media_type=MediaType.IMAGE)

    assert [item.key for item in view._queue._items] == [making, standing, waiting]
    assert [item.key for item in view.queue_now()[0]] == [making, standing, waiting]



class _QueueClient(ComfyUIClient):
    def __init__(self, foreign=None, fail=None):
        super().__init__(folders=SUITE_FOLDERS)
        self._foreign = foreign if foreign is not None else ForeignQueue(running=[], pending=[])
        self._fail = fail
        self.cleared = 0

    def foreign_queue(self):
        return self._foreign

    def clear_foreign_queue(self):
        if self._fail is not None:
            raise self._fail
        self.cleared += 1
        gone = self._foreign.total
        self._foreign = ForeignQueue(running=[], pending=[])
        return gone


def _queue_view(qtbot, client):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), client=client)
    qtbot.addWidget(view)
    view.refresh()
    return view


def test_the_strip_names_another_apps_queue_before_generate_is_pressed(qtbot):
    client = _QueueClient(ForeignQueue(running=["r"], pending=["a", "b"]))
    view = _queue_view(qtbot, client)

    view._poll()

    assert view._queue._running.status_text() == (
        "3 jobs from another app are queued on ComfyUI")
    assert not view._queue._clear.isHidden()


def test_a_queue_of_our_own_leaves_the_strip_as_it_was(qtbot):
    view = _queue_view(qtbot, _QueueClient())

    view._poll()

    assert view._queue._running.status_text() == ""
    assert view._queue._clear.isHidden()


def test_an_unreadable_queue_claims_nothing_rather_than_a_stale_count(qtbot):
    class Wedged(_QueueClient):
        def foreign_queue(self):
            raise OSError("connection refused")

    view = _queue_view(qtbot, _QueueClient(ForeignQueue(running=[], pending=["a"])))
    view._poll()
    assert not view._queue._clear.isHidden()

    view._client = Wedged()
    view._poll()

    assert view._foreign_queue.total == 0
    assert view._queue._clear.isHidden()


def test_clearing_wipes_the_other_apps_jobs_off_comfyui(qtbot, monkeypatch):
    client = _QueueClient(ForeignQueue(running=["r"], pending=["a", "b"]))
    view = _queue_view(qtbot, client)
    view._poll()
    _answer_confirmation(monkeypatch, QMessageBox.StandardButton.Yes)

    view._queue._clear.click()

    assert client.cleared == 1, (
        "the user's ask: a way out from under a queue the user did not fill; the shared "
        "server gathers jobs no window here can account for")


def test_clearing_can_be_declined_at_the_prompt(qtbot, monkeypatch):
    client = _QueueClient(ForeignQueue(running=[], pending=["a"]))
    view = _queue_view(qtbot, client)
    view._poll()
    _answer_confirmation(monkeypatch, QMessageBox.StandardButton.No)

    view._queue._clear.click()

    assert client.cleared == 0


def test_the_prompt_says_how_many_jobs_go(qtbot):
    client = _QueueClient(ForeignQueue(running=["r"], pending=["a", "b"]))
    view = _queue_view(qtbot, client)
    view._poll()
    asked = []
    view._confirm_clear_queue = lambda total: asked.append(total) or False

    view._queue._clear.click()

    assert asked == [3]


def test_a_failed_clear_is_surfaced_not_swallowed(qtbot, monkeypatch):
    client = _QueueClient(ForeignQueue(running=[], pending=["a"]),
                          fail=OSError("ComfyUI is not responding"))
    view = _queue_view(qtbot, client)
    view._poll()
    view._confirm_clear_queue = lambda total: True
    warned = []
    monkeypatch.setattr(
        "origenerator.gui.gallery_view.QMessageBox.warning",
        lambda *a, **k: warned.append(a),
    )

    view._queue._clear.click()

    assert warned


def test_a_cleared_queue_blanks_the_bar_without_waiting_for_a_poll(qtbot):
    client = _QueueClient(ForeignQueue(running=[], pending=["a", "b"]))
    view = _queue_view(qtbot, client)
    view._poll()
    view._confirm_clear_queue = lambda total: True

    view._queue._clear.click()

    assert view._queue._running.status_text() == ""
    assert view._queue._clear.isHidden()



def _cancelable(key, cancelled):
    return InFlightItem(key=key, caption="Alpha Workflow \u203a a paper kite",
                        reading=RunReading(status="queued"), reveal=lambda: None,
                        cancel=lambda: cancelled.append(key))


def _view_holding(qtbot, monkeypatch, items):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    monkeypatch.setattr(view, "_inflight_items", lambda rows=None, requests=None: items)
    view._update_queue()
    return view


def test_cancel_all_cancels_nothing_when_the_answer_is_no(qtbot, monkeypatch):
    cancelled = []
    view = _view_holding(qtbot, monkeypatch, [_cancelable("a", cancelled),
                                              _cancelable("b", cancelled)])
    _answer_confirmation(monkeypatch, QMessageBox.StandardButton.No)

    view._queue._cancel_all.click()

    assert cancelled == []


def test_cancel_all_cancels_every_job_from_the_back_of_the_line_forward(qtbot, monkeypatch):
    cancelled = []
    view = _view_holding(qtbot, monkeypatch, [_cancelable(key, cancelled)
                                              for key in ("a", "b", "c")])
    _answer_confirmation(monkeypatch, QMessageBox.StandardButton.Yes)

    view._queue._cancel_all.click()

    assert cancelled == ["c", "b", "a"], (
        "from the back of the line forward, so nothing waiting starts only to be stopped a "
        "moment later")


def test_cancel_all_asks_about_the_jobs_it_would_cancel(qtbot, monkeypatch):
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda _parent, title, text, *_a, **_kw: asked.append((title, text))
        or QMessageBox.StandardButton.No))
    for held in ([_cancelable("a", []), _cancelable("b", []),
                  InFlightItem(key="c", caption="Alpha Workflow \u203a a paper kite",
                               reading=RunReading(status="queued"), reveal=lambda: None)],
                 [_cancelable("a", [])]):
        _view_holding(qtbot, monkeypatch, held)._queue._cancel_all.click()

    assert asked == [("Cancel All", "Cancel all 2 jobs in the Job Queue?"),
                     ("Cancel All", "Cancel the job in the Job Queue?")]


def test_cancel_all_leaves_populate_on_to_start_its_next_seed(
        qtbot, tmp_path, monkeypatch):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_populate(True)
    (job,) = view._jobs.all_jobs
    view.refresh()
    _answer_confirmation(monkeypatch, QMessageBox.StandardButton.Yes)

    view._queue._cancel_all.click()

    assert view._populate.is_active(key), (
        "the user's call: Cancel All does not switch Populate off")
    (next_seed,) = view._jobs.all_jobs
    assert next_seed.prompt_id != job.prompt_id


def test_restoring_an_emptied_item_runs_it_again_in_its_own_folder_and_brings_it_back(
        qtbot, tmp_path):
    db = Database(tmp_path / "test.db")
    db.insert_generation(NewGeneration(prompt_id="p1", workflow_name="sdxl_t2i", workflow_version="v1",
                         params_json=json.dumps({"seed": 4242}), workflow_json="{}"))
    db.set_generation_favorite("p1", True)
    db.update_generation("p1", status="completed",
                         output_files=json.dumps([{"filename": "a.png", "subfolder": ""}]))
    view = GalleryView(db, client=_reroll_client(),
                       actions=GalleryEdits(db, OutputPlaces.in_one_folder(tmp_path / "out"),
                                              Trash(tmp_path / "trash")))
    qtbot.addWidget(view)
    view.refresh()
    view._delete_rows([db.get_generation("p1")])
    record = db.get_trashed("p1")
    db.record_trashed("p1", record["row"], {**record["batch"], "emptied": True},
                       deleted_at=record["deleted_at"])

    view.restore_from_trash(["p1"])

    job_prompt_id = db.get_trashed("p1")["batch"]["regenerating_as"]
    job_row = db.get_generation(job_prompt_id)
    assert json.loads(job_row["params_json"])["seed"] == 4242
    assert view._jobs.job_for_prompt(job_prompt_id) is not None
    assert not view._gallery_pane.showing_trash()

    new_files = json.dumps([{"filename": "b.png", "subfolder": ""}])
    db.update_generation(job_prompt_id, status="completed", output_files=new_files)
    view.refresh()

    back = db.get_generation("p1")
    assert (back["output_files"], back["starred"]) == (new_files, 1)
    assert db.get_generation(job_prompt_id) is None
    assert db.get_trashed("p1") is None


def test_a_completion_the_poll_found_is_still_drawn_when_that_tick_ends(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    _new_tile(view).add_requested.emit()
    (job,) = view._jobs.all_jobs
    client.fetch_history = lambda prompt_id: _REROLL_HISTORY

    view._poll()

    assert job.prompt_id in view.listed_prompt_ids()


def test_a_tabs_cancel_stops_the_oldest_of_its_runs_still_alive(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    tab = _front_panel(view)
    tab.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a brand new prompt"))
    tab.use_random_seed()
    tab._how_many.set_how_many(4)
    tab._on_generate()
    oldest, *others = tab.launched_runs()

    tab._cancel_btn.click()

    assert view._db.get_generation(oldest) is None
    assert all(view._db.get_generation(run) is not None for run in others)


def test_a_tabs_cancel_hover_answers_for_the_oldest_of_its_runs_in_two_folders(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    tab = _front_panel(view)
    for prompt in ("a first prompt", "a second prompt"):
        tab.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt=prompt))
        tab.use_random_seed()
        tab._on_generate()
    _oldest, newest = tab.launched_runs()
    newest_folder = view._job_folder_key(view._jobs.job_for_origin(newest))

    view._populate.start(newest_folder)
    view._sync_cancel_buttons()

    assert tab._cancel_btn.toolTip() == cancel_tooltip(False)


class _JobFromAFrame:
    prompt_id = "a-job-nobody-asked-for-in-words"

    def __init__(self, frame):
        self.params = {"input_image": str(frame)}


def test_a_job_with_no_request_behind_it_stands_on_the_frame_it_starts_from(qtbot, tmp_path):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    frame = tmp_path / "start_frame.png"
    frame.write_bytes(_png_bytes())

    assert view._job_source_image(_JobFromAFrame(frame)) == str(frame)


def test_going_to_a_runs_folder_is_a_stop_and_a_visit(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key, _job = _running_reroll(view)
    workflow = _image_workflow(view._tree)
    view._tree.setCurrentItem(workflow)
    view._folder_history.clear()

    view._reveal_reroll(key)

    assert [base_of(visit) for visit in view._folder_history] == [key], (
        "the folder is a stop and a visit all the same, both recorded once the tile is picked")
    view._navigation.go_back()
    assert view._tree.currentItem() is _image_workflow(view._tree)


def test_clicking_a_runs_tile_puts_a_running_search_away(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key, _job = _running_reroll(view)
    _search_for(view, "cat")
    assert view._gallery_pane.showing_search()

    view._reveal_reroll(key)

    assert not view._gallery_pane.showing_search()
    assert view._search.field.text() == ""


def test_a_run_in_a_folder_the_tree_has_not_drawn_yet_is_gone_to_all_the_same(qtbot):
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    db.add(_running_row("gen1", prompt="a dog"))
    folder = gallery.settings_folder_key(
        db.get_generation("gen1"), gallery.build_image_config_index(view._image_rows))

    view._reveal_reroll(folder)

    assert _selected_folder(view) == folder


def test_a_runs_tile_goes_to_the_tab_following_it_before_the_tab_that_launched_it(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    launcher = _front_panel(view)
    launcher.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a new prompt"))
    launcher.use_random_seed()
    launcher._on_generate()
    (key,) = view._live_jobs
    launcher.stop_watching()
    following = view._generate_pane._add_subtab()
    following.watch_folder(key, None)
    view._generate_pane.setCurrentWidget(launcher)

    view._select_reroll(key)

    assert view._generate_pane.current_generate_tab() is following


def test_a_run_no_tab_launched_lands_in_the_front_tab_when_it_stands_on_that_folder(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    front = view._generate_pane.current_generate_tab()
    view._generate_pane.pin_tab(front)
    view._jobs.start_reroll(key, view.group_for_key(key), view._image_rows)
    count = view._generate_pane.count()

    view._select_reroll(key)

    assert view._generate_pane.current_generate_tab() is front
    assert view._generate_pane.count() == count


def test_a_run_that_made_no_file_is_not_loaded_into_the_tab_that_launched_it(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    tab = _front_panel(view)
    tab.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a brand new prompt"))
    tab.use_random_seed()
    tab._on_generate()
    ((key, job),) = view._live_jobs.items()
    following = view._generate_pane._add_subtab()
    following.watch_folder(key, None)
    shown = []
    tab.show_completed_result = lambda row, rows: shown.append(row)
    following.show_finished_media = shown.append

    view._on_reroll_finished(key, job.prompt_id)

    assert shown == []


def test_populate_in_a_video_folder_runs_the_settings_it_read_with_no_image_stage(qtbot,
                                                                                       tmp_path):
    view = GalleryView(_seeded_i2v_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_leaf_of(view, "vid")

    view._toggle_populate(True)

    names = {job.workflow.name for job in view._jobs.all_jobs}
    assert "wan22_i2v" in names
    assert "sdxl_t2i" not in names


def test_flushing_the_queue_hands_comfyui_what_it_is_still_holding_and_says_how_many(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    tab = _front_panel(view)
    tab.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a brand new prompt"))
    tab.use_random_seed()
    tab._how_many.set_how_many(4)
    tab._on_generate()
    sent = client.submit_job.call_count
    assert sent < 4

    assert view.flush_queue_to_server() == 4 - sent
    assert client.submit_job.call_count == 4


def test_a_landing_shows_in_the_tabs_following_it_and_the_launcher_only_its_end_state(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    launcher = _front_panel(view)
    launcher.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a brand new prompt"))
    launcher.use_random_seed()
    launcher._on_generate()
    ((key, job),) = view._live_jobs.items()
    following = view._generate_pane._add_subtab()
    following.watch_folder(key, None)
    told = []
    launcher.show_finished_media = lambda row: told.append(("launcher", row["prompt_id"]))
    following.show_finished_media = lambda row: told.append(("following", row["prompt_id"]))

    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)

    assert told == [("following", job.prompt_id)]
