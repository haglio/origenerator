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
    act_settings,
    fix_training,
    gallery,
    look_training,
    lora_training,
)
from origenerator.comfyui_client import ComfyUIClient, ForeignQueue
from origenerator.db import Database
from origenerator.gallery.collection import (
    RECENTS_KEY,
)
from origenerator.generation_state import GenerationSource
from origenerator.gui import gallery_view as gallery_view_module
from origenerator.gui import generate_config_panel as gcp_module
from origenerator.gui.combine_panel import CombineRequest
from origenerator.gui.gallery_view import _GROUP_ROLE, GalleryView
from origenerator.gui.hud_queue import queue_section
from origenerator.gui.inflight import InFlightItem, RunReading
from origenerator.media import MediaType
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
    _open_recents,
    _png_bytes,
    _preview_of,
    _reroll_client,
    _reroll_tile,
    _resolve_by_id,
    _row,
    _running_reroll,
    _running_row,
    _seeded_db,
    _select_first_leaf,
    _selected_folder,
    _single_i2v_db,
    _tab_with_prompts,
)
from tests.slideshow_hud_support import engine_of, funestra_of

pytestmark = pytest.mark.usefixtures("_stub_preview_resolution")


# The two stages of a chained i2v re-roll: a fresh image, then the video on it.
_IMG_REROLL_HISTORY = {"outputs": {"7": {"images": [
    {"filename": "sdxl_new.png", "subfolder": "image", "type": "output"}]}}}


def _insert_running_reroll(db, prompt_id="rr", seed=99):
    """A re-roll left running by a prior session: same settings folder as
    _seeded_db's 'orig', no output yet, status running."""
    params = dict(_SDXL.default_params(), seed=seed, positive_prompt="a cat")
    db.insert_generation(
        prompt_id=prompt_id, workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt="a cat", seed=seed,
        params_json=json.dumps(params), workflow_json="{}",
    )
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
    client.submit_job.assert_not_called()  # reconnected, never resubmitted


def test_a_training_left_running_is_taken_up_before_the_line_it_held_is_sent(
        qtbot, tmp_path, monkeypatch):
    db = _seeded_db(tmp_path, seed=7)
    _insert_running_reroll(db, "waiting")
    db.update_generation("waiting", status="pending")
    trainer = SimpleNamespace(running=lambda: True, began=0.0)
    job = {"part": "hands", "display_name": "Hands fix 1.0",
           "status": str(tmp_path / "status.json"), "log": str(tmp_path / "training.log")}
    monkeypatch.setattr(fix_training, "trainings", lambda: [job])
    monkeypatch.setattr(lora_training, "trainer_of", lambda kept: trainer)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)

    view.reconnect_running_jobs()

    assert view._jobs.training is not None
    client.submit_job.assert_not_called()


def test_a_look_loras_training_left_running_is_taken_up_without_holding_the_line(
        qtbot, tmp_path, monkeypatch):
    db = _seeded_db(tmp_path, seed=7)
    _insert_running_reroll(db, "waiting")
    db.update_generation("waiting", status="pending")
    trainer = SimpleNamespace(running=lambda: True, began=0.0)
    job = {"base": "Example Look", "display_name": "Example Look 1.1",
           "status": str(tmp_path / "status.json"), "log": str(tmp_path / "training.log")}
    monkeypatch.setattr(look_training, "trainings", lambda: [job])
    monkeypatch.setattr(lora_training, "trainer_of", lambda kept: trainer)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)

    view.reconnect_running_jobs()

    assert view._jobs.training is not None
    assert not view._jobs.training_holds_the_machine()
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
    assert _generating_tile(view) is not None  # the run's own, cancelable tile

    client.job_completed.emit("rr", _REROLL_HISTORY)

    row = db.get_generation("rr")
    assert row["status"] == "completed"
    assert "a.png" in row["output_files"]
    assert view._live_jobs == {}


def test_starting_a_reroll_records_a_running_row(qtbot, tmp_path):
    # A re-roll persists a running row the moment it's submitted, so a restart
    # mid-generation can find it again (reconnect) instead of losing all trace.
    db = _seeded_db(tmp_path, seed=7)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    _reroll_tile(view).add_requested.emit()

    job = view._live_jobs[key]
    row = db.get_generation(job.prompt_id)  # keyed by the same id ComfyUI runs it under
    assert row is not None
    assert row["status"] == "running"
    assert row["workflow_name"] == "sdxl_t2i"
    assert gallery.row_output_files(row) == []  # no output yet: stays out of the tree


def test_reroll_completion_finalizes_the_running_row(qtbot, tmp_path):
    client = _reroll_client()
    db = _seeded_db(tmp_path, seed=7)
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _reroll_tile(view).add_requested.emit()
    prompt_id = view._live_jobs[key].prompt_id

    client.job_completed.emit(prompt_id, _REROLL_HISTORY)

    rows = db.list_generations()
    assert len(rows) == 2  # the running row was updated in place, not duplicated
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
    _reroll_tile(view).add_requested.emit()
    prompt_id = view._live_jobs[key].prompt_id
    assert db.get_generation(prompt_id) is not None

    _generating_tile(view).cancel_requested.emit()

    assert db.get_generation(prompt_id) is None  # the abandoned run leaves no trace


def test_failed_reroll_marks_its_running_row_error(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _reroll_tile(view).add_requested.emit()
    job = view._live_jobs[key]

    view._client.job_error.emit(job.prompt_id, "boom")

    assert db.get_generation(job.prompt_id)["status"] == "error"
    assert key not in view._live_jobs


def _generation_failed_dialog(view):
    (dialog,) = view.findChildren(gallery_view_module.QMessageBox)
    assert dialog.windowTitle() == "Generation failed"
    return dialog


def test_a_failed_run_says_so_instead_of_vanishing(qtbot, tmp_path):
    """A failed run leaves nothing — no file, so no tile, and the row it
    does leave is one every collection filters out for having produced nothing. So it
    used to simply disappear: minutes of GPU, the tile gone off the Job Queue, and no
    word anywhere but the log. Someone watching read that as a success and went
    looking for the video."""
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _reroll_tile(view).add_requested.emit()
    job = view._live_jobs[key]

    view._client.job_error.emit(job.prompt_id, json.dumps(
        {"node_type": "RIFE VFI",
         "exception_message": "Tried all base urls but no success"
         + chr(10) * 2 + "long log"}))

    # The node that threw and its first line -- not the download log under it.
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
    # Both calls, whatever the view last heard about the run: the server takes
    # the prompt out of its line if it is waiting there, and stops it if it is
    # the one being rendered -- by name, so nothing else's run is touched.
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _reroll_tile(view).add_requested.emit()
    prompt_id = view._live_jobs[key].prompt_id

    client.node_executing.emit(prompt_id, "5")  # job is now executing
    _generating_tile(view).cancel_requested.emit()

    client.cancel_prompt.assert_called_once_with(prompt_id)
    client.interrupt.assert_called_once_with(prompt_id)
    assert key not in view._live_jobs
    assert _generating_tile(view) is None
    assert _reroll_tile(view).isEnabled()  # the + is live again


def test_active_reroll_survives_a_refresh(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _reroll_tile(view).add_requested.emit()

    view.refresh()  # a poll-driven rebuild must not drop the running job

    assert key in view._live_jobs
    assert _generating_tile(view) is not None  # the run still has its tile


# --- re-roll preview mirrored into the info pane ----------------------------


def test_selecting_a_running_reroll_shows_its_live_preview_in_the_info_pane(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)
    frame = _png_bytes()
    client.preview_image.emit(job.prompt_id, frame)  # a frame arrives, cached on the job
    _preview_of(view).show_frame = MagicMock()

    _generating_tile(view).selected.emit()  # user clicks the running tile

    _preview_of(view).show_frame.assert_called_once_with(frame)


def test_new_frames_route_to_the_info_pane_while_the_reroll_is_selected(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)
    _generating_tile(view).selected.emit()
    _preview_of(view).show_frame = MagicMock()

    client.preview_image.emit(job.prompt_id, _png_bytes())  # a later frame

    _preview_of(view).show_frame.assert_called_once_with(_png_bytes())


def test_selecting_a_thumbnail_stops_the_reroll_from_driving_the_info_pane(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)  # starting the re-roll selects it
    view._on_thumbnail_clicked("orig")  # user views a finished item instead

    _preview_of(view).show_frame = MagicMock()
    client.preview_image.emit(job.prompt_id, _png_bytes())  # tile updates, info pane does not

    _preview_of(view).show_frame.assert_not_called()
    assert view._selected_reroll_key is None


def test_selecting_the_reroll_highlights_its_tile_and_drops_thumbnail_picks(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _running_reroll(view)
    view._browser.apply_selection("orig", _NO_MOD)  # a thumbnail is picked while it runs
    assert view.selected_prompt_ids() == ["orig"]

    _generating_tile(view).selected.emit()

    assert _generating_tile(view)._selected
    assert view.selected_prompt_ids() == []  # the thumbnail pick is cleared


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
    # Change 4: a Generate ends on its result. When the re-roll it launched finishes,
    # the just-saved generation loads into that tab (show_completed_result), so it
    # shows the finished item — not the live-frame or idle placeholder.
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=client)
    qtbot.addWidget(view)
    view.refresh()
    panel = view._info_tabs.current_config_panel()
    key = _generate_in_current_tab(view, positive_prompt="a cat", seed=9)
    job = view._live_jobs[key]

    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)  # the re-roll finishes

    assert panel._displayed_row is not None
    assert panel._displayed_row["prompt_id"] == job.prompt_id  # the just-finished result


def test_the_tiles_run_lands_in_the_tab_standing_on_its_folder(qtbot, tmp_path):
    # The folder tile's "+" is the gallery's launch, not a tab's Generate, so it
    # has no tab of its own — it goes to the tab already standing on that very
    # folder, which opening the folder is what put there. A tab parked on other
    # settings still gets nothing
    # (test_a_tab_on_other_settings_does_not_claim_the_tiles_launch).
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)

    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)

    assert view._info_tabs.count() == 1   # no tab grew beside it
    panel = view._info_tabs.current_config_panel()
    assert panel.displayed_row()["prompt_id"] == job.prompt_id


def test_the_tab_claiming_the_tiles_run_is_kept(qtbot, tmp_path):
    # That run's Cancel and its filling bar are in this tab now, so it is no
    # longer one a later click may replace — the rule a tab's own Generate
    # already follows.
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    tabs = view._info_tabs
    assert tabs._preview_panel is tabs.current_config_panel()  # italic until now

    _reroll_tile(view).add_requested.emit()

    assert tabs._preview_panel is None


def test_opening_a_runs_folder_from_its_card_loads_no_saved_item(qtbot, tmp_path):
    # Clicking an in-flight card goes to the run, so the folder it opens on the
    # way lands on no saved item of its own — one loaded there would paint an
    # image nobody asked for over the very tab the run belongs to.
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key, _job = _running_reroll(view)
    view._tree.setCurrentItem(_image_workflow(view._tree))  # browse away from it
    view._info_tabs.load_selection = MagicMock()

    view._reveal_reroll(key)

    view._info_tabs.load_selection.assert_not_called()
    assert view._info_tabs.current_config_panel().watched_key() == key


def test_finishing_a_reroll_keeps_a_prompt_typed_while_it_ran(qtbot, tmp_path):
    # The reported bug, end to end: the user keeps typing the next prompt while a
    # Generate runs; when it finishes, loading its result into that tab must not
    # re-seed the form and wipe what they typed.
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=client)
    qtbot.addWidget(view)
    view.refresh()
    panel = view._info_tabs.current_config_panel()
    key = _generate_in_current_tab(view, positive_prompt="a cat", seed=9)
    job = view._live_jobs[key]
    panel._param_form.set_values({"positive_prompt": "a wizard mid-edit"})

    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)  # the re-roll finishes

    assert panel._param_form.get_values()["positive_prompt"] == "a wizard mid-edit"


def test_canceling_a_selected_reroll_releases_the_info_pane(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key, _job = _running_reroll(view)
    _generating_tile(view).selected.emit()

    view._cancel_reroll(key)

    assert view._selected_reroll_key is None


def test_a_generation_can_be_watched_fullscreen_while_it_is_still_being_made(
        qtbot, tmp_path, monkeypatch):
    # The reported gap, end to end: double-clicking the preview mid-generation did
    # nothing. Now it opens over the live frames, keeps streaming them, and lands on
    # the finished image when the run completes.
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)
    _generating_tile(view).selected.emit()
    client.preview_image.emit(job.prompt_id, _png_bytes())
    view._poll()  # the tick that lists the run as in flight

    win = _preview_of(view).open_fullscreen()  # the double-click, mid-generation
    qtbot.addWidget(win.shown)
    assert win._set.current_prompt_id() == job.prompt_id
    assert engine_of(win.shown).on_screen.read_bytes() == _png_bytes()
    win.tick()  # it reads its Funestra, as its poll does a moment later

    buf = BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, format="PNG")  # a later, redder frame
    client.preview_image.emit(job.prompt_id, buf.getvalue())
    assert engine_of(win.shown).on_screen.read_bytes() == buf.getvalue()  # it goes on streaming

    done = tmp_path / "done.png"
    Image.new("RGB", (8, 8), (10, 120, 200)).save(done, "PNG")
    landed = lambda row, places: (done, "image") if row["prompt_id"] == job.prompt_id else None
    monkeypatch.setattr(gcp_module, "resolve_preview", landed)
    monkeypatch.setattr(gallery, "resolve_preview", landed)

    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)
    win.tick()  # it reads its Funestra, as its poll does a moment later --
    win.tick()  # and once more, for whatever that reading sent it

    # Ends on the result, not the last frame.
    assert engine_of(win.shown).on_screen == done
    assert not win._set.playlist.current().is_live
    win.close()


def test_a_run_watched_fullscreen_lands_as_its_generation_among_its_folder(
        qtbot, tmp_path, monkeypatch):
    by_id = lambda row, places: (f"{row['prompt_id']}.png", "image")
    monkeypatch.setattr(gallery, "resolve_preview", by_id)
    monkeypatch.setattr(gcp_module, "resolve_preview", by_id)
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)
    _generating_tile(view).selected.emit()
    client.preview_image.emit(job.prompt_id, _png_bytes())
    view._poll()  # the tick that lists the run as in flight
    slideshow = _preview_of(view).open_fullscreen()
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
    # Nothing will ever land, so the slideshow would sit on a stale partial frame.
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key, job = _running_reroll(view)
    _generating_tile(view).selected.emit()
    client.preview_image.emit(job.prompt_id, _png_bytes())
    view._poll()  # the tick that lists the run as in flight
    slideshow = _double_click_slideshow(view, qtbot, media=None)
    slideshow.shown.show()

    view._cancel_reroll(key)
    view._poll()  # the tick that hears the run is no longer in flight

    assert job.prompt_id not in [slide.prompt_id
                                 for slide in slideshow._set.playlist.in_play_order()]


def test_a_cancelled_generation_leaves_a_slideshow_of_a_saved_file_alone(qtbot, tmp_path):
    # One opened over a saved file has its own thing on screen: it stays up.
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
    # One click on "+" starts the run and puts it up in a tab, which is where it
    # can be watched full size — the tile's own image is a thumbnail. The tile
    # is lit as well, the gallery's selection being that run now.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)

    _reroll_tile(view).add_requested.emit()

    assert view._info_tabs.current_config_panel().watched_key() == key
    assert view._selected_reroll_key == key
    assert _generating_tile(view)._selected


def test_selecting_a_reroll_before_any_frame_avoids_the_idle_placeholder(qtbot, tmp_path):
    # "Select a generation to preview" would misdescribe a running re-roll, so a
    # queued one with no frame yet shows a waiting note instead of clearing.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _running_reroll(view)  # no preview frame has arrived yet
    painted = []  # what the pane is told to show, in order
    _preview_of(view).clear = MagicMock(side_effect=lambda: painted.append("(placeholder)"))
    _preview_of(view).show_message = MagicMock(
        side_effect=lambda text, **kwargs: painted.append(text))

    _generating_tile(view).selected.emit()

    # Seeding the landing tab from the run's settings may pass through the
    # placeholder; what the pane ends on is the point.
    assert painted[-1] == "Waiting for preview…"
    assert _preview_of(view).show_message.call_args == (("Waiting for preview…",), {"live": True})


def _waiting_view(qtbot, tmp_path, backlog):
    """A gallery with a selected re-roll ComfyUI hasn't started, ``backlog`` prompts
    ahead of it and no frame yet — the state that used to read as a hang."""
    client = _reroll_client()
    client.fetch_history = MagicMock(return_value={})  # reconcile finds nothing done
    client.foreign_backlog = MagicMock(return_value=backlog)
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _running_reroll(view)
    _preview_of(view).show_message = MagicMock()  # the resting tab, where the click lands
    _generating_tile(view).selected.emit()
    return view, client


def test_a_run_stuck_behind_another_app_says_how_much_is_ahead(qtbot, tmp_path):
    # The reported mystery: a Generate parked after another client's work looked
    # exactly like a hang. The pane now names what's holding it.
    view, _client = _waiting_view(qtbot, tmp_path, backlog=3)

    view._poll()

    assert _preview_of(view).show_message.call_args.args[0] == "Waiting on 3 jobs from another app"


def test_the_wait_text_follows_the_queue_as_it_drains(qtbot, tmp_path):
    view, client = _waiting_view(qtbot, tmp_path, backlog=3)
    view._poll()

    client.foreign_backlog = MagicMock(return_value=1)  # one finished ahead of us
    view._poll()

    assert _preview_of(view).show_message.call_args.args[0] == "Waiting on 1 job from another app"


def test_a_queue_of_the_users_own_jobs_leaves_the_plain_waiting_note(qtbot, tmp_path):
    # Waiting on his own queue means ComfyUI is generating something he asked
    # for, which is no mystery at all.
    view, _client = _waiting_view(qtbot, tmp_path, backlog=0)

    view._poll()

    assert _preview_of(view).show_message.call_args.args[0] == "Waiting for preview…"


def test_a_run_waiting_out_the_minute_after_an_image_says_when_it_starts(
        qtbot, tmp_path, monkeypatch):
    view, _client = _waiting_view(qtbot, tmp_path, backlog=0)
    waiting, = view._live_jobs.values()
    # The half-second keeps the count a clear half-second off a rollover.
    start = time.monotonic() + 42.5
    monkeypatch.setattr(view._jobs, "starts_at",
                        lambda prompt_id: start if prompt_id == waiting.prompt_id else None)

    view._poll()

    assert _preview_of(view).show_message.call_args.args[0] == "Starts in 0:43"


def test_start_now_on_the_job_queue_starts_the_video_waiting_out_the_minute(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    _key, image = _running_reroll(view)  # an image asked for: videos wait a minute
    view._jobs.start_prepared("video/k", _WAN_I2V, dict(_WAN_I2V.default_params(), seed=3))
    video = view._jobs.newest_job_for("video/k")
    view._jobs.cancel_job(image.prompt_id)
    view._update_queue()
    assert view._queue._running.status_text().startswith("Starts in")

    view._queue._running._start_now.click()

    assert client.submit_job.call_args_list[-1].args[1] == video.prompt_id
    assert not view._queue._running.status_text().startswith("Starts in")


def test_a_streamed_frame_ends_the_wait_text(qtbot, tmp_path):
    # Once ComfyUI is rendering it, the frame is the answer — don't paint over it.
    view, client = _waiting_view(qtbot, tmp_path, backlog=3)
    view._poll()
    job = list(view._live_jobs.values())[0]
    client.preview_image.emit(job.prompt_id, _png_bytes())
    _preview_of(view).show_message = MagicMock()

    view._poll()

    _preview_of(view).show_message.assert_not_called()


def test_selected_reroll_survives_the_rebuild_its_running_row_triggers(qtbot, tmp_path):
    # Submitting a re-roll inserts a running row, so the next poll rebuilds the
    # tree — the selected re-roll must keep driving the info pane across it.
    client = _reroll_client()
    client.fetch_history = MagicMock(return_value={})  # reconcile finds nothing done
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key, job = _running_reroll(view)
    frame = _png_bytes()
    client.preview_image.emit(job.prompt_id, frame)
    _generating_tile(view).selected.emit()
    panel = view._info_tabs.current_config_panel()
    assert panel.watched_key() == key
    assert _frame_shown(panel._preview, frame)

    view._poll()  # the rebuild the new running row triggers

    assert view._selected_reroll_key == key
    assert _generating_tile(view)._selected
    # The tab following the run kept its frame: a rebuild repaints no tab.
    assert view._info_tabs.current_config_panel() is panel
    assert panel.watched_key() == key
    assert _frame_shown(panel._preview, frame)


def test_i2v_video_stage_keeps_the_last_image_frame_until_it_previews(qtbot, tmp_path):
    # Re-rolling an i2v runs a fresh image, then the video. When it moves onto the
    # video — which has no preview of its own yet — the info pane must keep showing
    # the image frame rather than going blank across the rebuild that the finished
    # image row triggers.
    client = _reroll_client()
    client.fetch_history = MagicMock(return_value={})
    view = GalleryView(_seeded_i2v_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_leaf_of(view, "vid")
    _reroll_tile(view).add_requested.emit()  # image stage starts
    img_job = view._live_jobs[key]
    _generating_tile(view).selected.emit()
    image_frame = _png_bytes()
    client.preview_image.emit(img_job.prompt_id, image_frame)

    client.job_completed.emit(img_job.prompt_id, _IMG_REROLL_HISTORY)  # image done -> video starts
    assert view._live_jobs[key].workflow.name == "wan22_i2v"

    view._poll()  # the rebuild the finished image row triggers

    assert view._selected_reroll_key == key
    panel = view._info_tabs.current_config_panel()
    assert panel.watched_key() == key
    assert _frame_shown(panel._preview, image_frame)  # still the image's frame


def _seeded_i2v_db(tmp_path):
    """A DB with a re-rollable SDXL image and a WAN i2v video built on it."""
    db = Database(tmp_path / "i2v.db")
    db.insert_generation(
        prompt_id="img", workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt="a cat", negative_prompt="", seed=7,
        params_json=json.dumps(dict(_SDXL.default_params(), seed=7, positive_prompt="a cat")),
        workflow_json="{}",
    )
    db.update_generation(
        "img", status="completed",
        output_files=json.dumps([{"filename": "sdxl_src.png", "subfolder": "image"}]),
    )
    db.insert_generation(
        prompt_id="vid", workflow_name="wan22_i2v", workflow_version="v002",
        positive_prompt="dance", negative_prompt="", seed=3,
        params_json=json.dumps(dict(_WAN_I2V.default_params(), seed=3, noise_seed=9,
                                    positive_prompt="dance", input_image="sdxl_src.png")),
        workflow_json="{}",
    )
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
    # Re-rolling an i2v whose input image is a known, re-buildable generation
    # first makes a fresh image (its settings, new seed), has it enhanced, then
    # runs the video on the enhancement -- all persisted, and the new video links
    # back to the new image.
    db = _seeded_i2v_db(tmp_path)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_leaf_of(view, "vid")

    _reroll_tile(view).add_requested.emit()

    # Stage 1: the image re-roll runs first, with the source image's settings.
    img_job = view._live_jobs[key]
    assert img_job.workflow.name == "sdxl_t2i"
    assert img_job.params["seed"] != 7  # fresh seed

    client.job_completed.emit(img_job.prompt_id, _IMG_REROLL_HISTORY)

    # Stage 2: the fresh image is enhanced before any video is made of it.
    (enhance_job,) = [job for job in view._jobs.all_jobs if job.enhances]
    assert enhance_job.params["input_image"] == "image/sdxl_new.png [output]"
    enhance_job.finished.emit(
        [{"filename": "image_enhance_new.png", "subfolder": "image", "type": "output"}],
        None, 1.0)
    view._jobs.start_now()  # the minute videos wait after an image, here the enhancement

    # Stage 3: the video now runs on the enhancement, its own seeds fresh.
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
    # The new video's stored input image resolves back to the new image (feature 1).
    image_rows = [r for r in rows if gallery.media_type_of_row(r) == "image"]
    assert gallery.find_source_image_id(new_video, image_rows) == new_image["prompt_id"]


def _tooltips(view, prompt_id):
    return [b.toolTip() for b in view._browser._thumb_widgets[prompt_id]._corner_buttons]


def test_i2v_folder_item_carries_both_seed_reroll_hovers(qtbot, tmp_path):
    view = GalleryView(_seeded_i2v_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_leaf_of(view, "vid")  # the i2v's own settings leaf

    # Its start frame is a re-buildable image, so both per-seed controls show.
    assert _tooltips(view, "vid") == ["Randomize video seed", "Randomize image seed"]


def test_image_folder_item_has_no_seed_reroll_hovers(qtbot, tmp_path):
    view = GalleryView(_seeded_i2v_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_leaf_of(view, "img")  # a plain SDXL image leaf — not image-conditioned

    assert _tooltips(view, "img") == []


def test_i2v_item_with_a_handpicked_frame_offers_only_the_video_seed(qtbot, tmp_path):
    view = GalleryView(_single_i2v_db(tmp_path, "handpicked.png"), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_leaf_of(view, "vid")

    # The frame can't be re-rolled, so only the video-seed control is offered.
    assert _tooltips(view, "vid") == ["Randomize video seed"]


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

    view._browser._thumb_widgets["vid"]._corner_buttons[0].click()  # "Randomize video seed"

    view._jobs.reroll_video_seed.assert_called_once()
    _key, row = view._jobs.reroll_video_seed.call_args.args
    assert row["prompt_id"] == "vid"


def test_image_seed_hover_rerolls_only_the_item_image_seed(qtbot, tmp_path):
    view = GalleryView(_seeded_i2v_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_leaf_of(view, "vid")
    view._jobs.reroll_image_seed = MagicMock()

    view._browser._thumb_widgets["vid"]._corner_buttons[1].click()  # "Randomize image seed"

    view._jobs.reroll_image_seed.assert_called_once()
    _key, row, _image_rows = view._jobs.reroll_image_seed.call_args.args
    assert row["prompt_id"] == "vid"


def test_poll_reconciles_a_reroll_whose_completion_signal_was_missed(qtbot, tmp_path):
    # If ComfyUI's one-shot completion frame is missed, the periodic poll pulls
    # /history as a backstop so the finished generation still lands in the gallery
    # without a restart.
    client = _reroll_client()
    client.fetch_history = MagicMock(return_value=_REROLL_HISTORY)
    db = _seeded_db(tmp_path, seed=7)
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    _reroll_tile(view).add_requested.emit()
    # The live job_completed is never delivered — only the poll runs.

    view._poll()

    rows = db.list_generations()
    assert len(rows) == 2  # the re-roll persisted without a restart
    assert view._live_jobs == {}
    assert key not in view._live_jobs


def test_i2v_reroll_without_a_known_source_image_reuses_the_input(qtbot, tmp_path):
    # No image generation matches the video's input, so the re-roll can't rebuild
    # a fresh frame — it re-rolls the video alone, keeping the same input image.
    db = Database(tmp_path / "i2v.db")
    db.insert_generation(
        prompt_id="vid", workflow_name="wan22_i2v", workflow_version="v002",
        positive_prompt="dance", negative_prompt="", seed=3,
        params_json=json.dumps(dict(_WAN_I2V.default_params(), seed=3, noise_seed=9,
                                    positive_prompt="dance", input_image="outside.png")),
        workflow_json="{}",
    )
    db.update_generation(
        "vid", status="completed",
        output_files=json.dumps([{"filename": "wan_src.mp4", "subfolder": "video"}]),
    )
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_leaf_of(view, "vid")

    _reroll_tile(view).add_requested.emit()

    job = view._live_jobs[key]
    assert job.workflow.name == "wan22_i2v"          # no image stage
    assert job.params["input_image"] == "outside.png"  # same input, re-used
    client.submit_job.assert_called_once()


# --- Recents collection: in-flight cards for queued/running generations -------


def test_a_slideshow_is_handed_the_job_queue_worked_out_off_the_listing_in_hand(qtbot):
    # Worked out off both tables read again for each slideshow that opened, the
    # line held a double-click up to a quarter of a second more.
    db = FakeDB([_image("done", "a cat", 50, 1)])
    db.add(_running_row("gen1", prompt="a dog"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    listings = []
    listing = db.list_generations
    db.list_generations = lambda: listings.append(1) or listing()

    items, _foreign = view.queue_now()

    assert ([item.key for item in items], listings) == (["gen1"], [])


def test_recents_shows_an_inflight_card_above_finished_items(qtbot):
    # An in-flight generation (a running DB row, as a re-roll inserts) shows as a
    # card on Recents; the finished item still lists below it, and the output-less
    # running row is never counted among the finished thumbnails.
    db = FakeDB([_image("done", "a cat", 50, 1)])
    db.add(_running_row("gen1", prompt="a dog"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    _open_recents(view)

    assert "gen1" in view._browser._inflight_cards
    assert view.listed_prompt_ids() == ["done"]          # cards aren't finished items


def test_recents_shows_a_live_reroll_as_an_inflight_card(qtbot):
    # A gallery re-roll: a running DB row (as _launch_reroll inserts) plus a live
    # job that supplies the frame. The card shows and carries the job's frame.
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.add(_running_row("rr1", prompt="a cat"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    folder_key = _key(_at(_image_workflow(view._tree), 0, 0))
    view._jobs._jobs[folder_key] = [_FakeRerollJob(
        "rr1", "sdxl_t2i", {"positive_prompt": "a cat"}, state="running", frame=_png_bytes()
    )]
    _open_recents(view)

    assert "rr1" in view._browser._inflight_cards
    assert not view._browser._inflight_cards["rr1"]._image.pixmap().isNull()  # the job's live frame
    # Clicking the re-roll card opens the folder it runs in (its tile shows there).
    view._browser._on_inflight_clicked("rr1")
    assert _selected_folder(view) == folder_key


def test_right_clicking_an_inflight_card_offers_to_cancel_the_run(
        qtbot, tmp_path, monkeypatch):
    # A card is the whole of what the collection shows of a run being made, and it used
    # to answer a right-click with nothing at all: stopping the run meant finding
    # it again among the Job Queue's rows.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)
    view.refresh()          # the launch's running row is in the DB now
    _open_recents(view)
    assert job.prompt_id in view._browser._inflight_cards
    labels = _menu_offering(monkeypatch, "browser_pane", pick="Cancel")

    view._browser._inflight_context_menu(job.prompt_id, QPoint(0, 0))

    assert labels == [["Cancel"]]
    assert view._jobs.all_jobs == []      # the run really stopped


def test_an_auto_generating_folders_card_offers_a_cancel_and_a_real_stop(
        qtbot, tmp_path, monkeypatch):
    # A Cancel ends nothing while Auto-Generate is on — it throws this seed away
    # and Auto-Generate launches another — and the menu says it in the same words
    # the tile's button and the Job Queue's row use. Unlike those, it has room to
    # offer the stop as well, which is the thing you cannot otherwise ask for
    # without going to the header for the Auto switch.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view._toggle_auto(True)          # Auto-Generate launches the first variation
    (job,) = view._jobs.all_jobs
    view.refresh()
    _open_recents(view)
    labels = _menu_offering(monkeypatch, "browser_pane")

    view._browser._inflight_context_menu(job.prompt_id, QPoint(0, 0))

    assert labels == [["Cancel", "Cancel and stop auto-generating"]]


def test_canceling_from_an_auto_generating_folders_card_ends_auto_generate_too(
        qtbot, tmp_path, monkeypatch):
    # The whole point of the second entry: Auto-Generate goes off and the run in it
    # is thrown away. The order matters — a discard while Auto-Generate is on is its
    # cue to
    # launch the next seed, so canceling first would leave a fresh run running.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_auto(True)
    (job,) = view._jobs.all_jobs
    view.refresh()
    _open_recents(view)
    _menu_offering(monkeypatch, "browser_pane", pick="Cancel and stop")

    view._browser._inflight_context_menu(job.prompt_id, QPoint(0, 0))

    assert not view._auto.is_active(key)     # Auto-Generate is off...
    assert view._jobs.all_jobs == []       # ...and nothing was launched in its place


def test_a_card_with_no_live_job_behind_it_raises_no_menu(qtbot, monkeypatch):
    # A running row this session never adopted (a restart mid-generation) has
    # nothing here to stop it with — the Job Queue hides the same button — so the
    # right-click raises nothing rather than a menu that cannot act.
    db = FakeDB([_image("done", "a cat", 50, 1)])
    db.add(_running_row("gen1"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    _open_recents(view)
    assert "gen1" in view._browser._inflight_cards      # the card is there...
    labels = _menu_offering(monkeypatch, "browser_pane")

    view._browser._inflight_context_menu("gen1", QPoint(0, 0))

    assert labels == []                        # ...but it offers nothing


def test_right_clicking_a_folders_live_tile_offers_to_cancel_the_run(
        qtbot, tmp_path, monkeypatch):
    # The same act as the button on the tile's face, on the gesture the rest of
    # the grid answers.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key, _job = _running_reroll(view)
    labels = _menu_offering(monkeypatch, "gallery_view", pick="Cancel")

    view._generating_tile_menu(key, QPoint(0, 0))

    assert labels == [["Cancel"]]
    assert view._jobs.all_jobs == []


def test_an_auto_generating_folders_live_tile_offers_the_stop_its_button_cannot(
        qtbot, tmp_path, monkeypatch):
    # The tile's Cancel only starts the next seed while Auto-Generate is on, and
    # there is no room on it for a second act. The menu has the room, so it carries the stop.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_auto(True)
    labels = _menu_offering(monkeypatch, "gallery_view", pick="Cancel and stop")

    view._generating_tile_menu(key, QPoint(0, 0))

    assert labels == [["Cancel", "Cancel and stop auto-generating"]]
    assert not view._auto.is_active(key)
    assert view._jobs.all_jobs == []


def _running_in_folder(prompt_id, prompt, steps, seed):
    """A running sdxl row sharing the settings folder of _image(prompt, steps, …) —
    same settings, fresh seed, no output — as a tab's Generate inserts up front."""
    return _row(prompt_id, "sdxl_t2i",
                {"positive_prompt": prompt, "steps": steps, "seed": seed},
                f"{prompt_id}.png", status="running", output_files="[]")


def test_open_folder_shows_a_running_generation_on_its_generating_tile(qtbot, tmp_path):
    # A tab's Generate IS a re-roll, so a generation running in a folder is the
    # folder's GeneratingTile — it shows the live frame. The output-less running
    # row is not drawn as a separate card or a (broken) static thumbnail; the tile
    # stands for it. Its folder's other, finished items still list as static
    # thumbnails.
    view = GalleryView(_seeded_db(tmp_path, seed=7), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)                 # a real re-roll running in the folder

    assert _generating_tile(view) is not None        # the running generation IS the tile
    assert job.prompt_id not in view._browser._inflight_cards  # not a separate in-flight card
    assert job.prompt_id not in view.listed_prompt_ids()  # nor an output-less static tile
    assert view.listed_prompt_ids() == ["orig"]     # only the finished item is a thumbnail


def test_open_folder_omits_a_running_row_from_the_static_grid(qtbot):
    # A running row (no output yet) gives its folder a tree node, but must not
    # draw as a broken, output-less static thumbnail. It draws as a live card
    # instead — it is the thing the folder is waiting for.
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.add(_running_in_folder("run1", "a cat", 50, 2))  # same folder as i1, still running
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    view._tree.setCurrentItem(view._leaf_by_id["i1"])

    assert "run1" in view._browser._inflight_cards           # in_flight, and shown as in_flight
    assert view.listed_prompt_ids() == ["i1"]      # run1 isn't a static thumbnail


def test_open_folder_does_not_double_show_a_reroll_running_in_it(qtbot, tmp_path):
    # A gallery re-roll running in a folder already has its GeneratingTile; its
    # running row must not ALSO appear as a separate in-flight card in that folder.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _key, job = _running_reroll(view)            # a real re-roll running in the folder

    view._rerender_current_leaf()               # redraw the open folder with its live tile

    assert _generating_tile(view) is not None   # the GeneratingTile shows it...
    assert job.prompt_id not in view._browser._inflight_cards  # ...and no duplicate in-flight card


def test_a_reroll_finishing_drops_its_inflight_card(qtbot):
    # The card tracks the database: once the re-roll's row leaves the running state
    # (it completed), the in-flight card drops even though a job object lingers.
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.add(_running_row("rr1", prompt="a cat"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    folder_key = _key(_at(_image_workflow(view._tree), 0, 0))
    view._jobs._jobs[folder_key] = [
        _FakeRerollJob("rr1", "sdxl_t2i", {"positive_prompt": "a cat"})]
    _open_recents(view)
    assert "rr1" in view._browser._inflight_cards

    # The re-roll finishes: its row becomes a completed generation, its job drops.
    view._live_jobs.pop(folder_key)
    db.delete_generation("rr1")
    db.add(_row("rr1", "sdxl_t2i", {"positive_prompt": "a cat"}, "rr1.png"))
    view._poll()
    assert "rr1" not in view._browser._inflight_cards


def test_inflight_card_frame_updates_in_place_without_a_rerender(qtbot):
    # A tracked re-roll's live frame is pushed into its existing card between
    # rebuilds, without re-rendering the whole collection.
    db = FakeDB([_image("i1", "a cat", 50, 1)])
    db.add(_running_row("rr1", prompt="a cat"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    folder_key = _key(_at(_image_workflow(view._tree), 0, 0))
    job = _FakeRerollJob("rr1", "sdxl_t2i", {"positive_prompt": "a cat"}, frame=None)
    view._jobs._jobs[folder_key] = [job]
    _open_recents(view)
    card = view._browser._inflight_cards["rr1"]

    job.last_preview = _png_bytes()  # a live frame arrives on the tracked re-roll
    view._poll()
    assert view._browser._inflight_cards["rr1"] is card       # same card object — no re-render
    assert not card._image.pixmap().isNull()          # now showing the frame


def test_recents_collection_appears_for_a_running_generation(qtbot):
    # A generation is running (a running DB row, no output yet): the Recents collection
    # appears and lists it as an in-flight card.
    view = GalleryView(FakeDB([_running_row("gen1")]))
    qtbot.addWidget(view)
    view.refresh()

    assert "Latest" in _alls(view._tree)
    _open_recents(view)
    assert "gen1" in view._browser._inflight_cards


def test_inflight_running_cards_sort_before_queued(qtbot):
    # Running generations sort before queued ones in the collection, regardless of the
    # order their in-flight rows come back from the database.
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
    """A stand-in for a job in the queue's line, as the display reads it."""
    return SimpleNamespace(prompt_id=prompt_id, media_type="image", source="generated",
                           state=state, shielded=False)


def test_inflight_items_follow_the_order_the_queue_will_run_them_in(qtbot):
    # An image jumping ahead of a video, or a drag moving a row, leaves no mark on
    # anything the rows record — so the Job Queue is ordered by the queue's own line,
    # here the reverse of the order the rows were made in.
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
    # A row a restart hasn't re-adopted has no place in the line; it waits at the
    # end rather than jumping the queue on screen.
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

    assert [it.key for it in view._inflight_items()] == ["known", "brand-new"]


def test_the_queue_shows_the_active_job_then_empties_when_idle(qtbot):
    # The Job Queue surfaces in-flight work from anywhere in the view, then
    # empties once nothing runs — keeping its slot so the panes never shift.
    db = FakeDB([_image("done", "a cat", 50, 1)])
    db.add(_running_row("gen1", prompt="a dog"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    with qtbot.waitExposed(view):   # showEvent -> refresh -> feeds the Job Queue
        view.show()

    assert view._queue.isVisible()
    assert view._queue.keys() == ["gen1"]
    assert view._queue._running.key == "gen1"

    db.delete_generation("gen1")   # the job ends, its running row gone
    view._poll()
    assert view._queue.isVisible()                    # still holding its slot
    assert view._queue.keys() == []                   # but blank
    assert view._queue._running.key is None


def test_an_open_slideshow_is_fed_the_same_queue_the_strip_shows(qtbot, monkeypatch):
    # The slideshow covers the Job Queue, so the queue follows onto the HUD in front
    # of the user, in the same order.
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

    # Filled at the opening rather than a poll and a half later, and with the
    # same rows and the same job being made Core's Job Queue is showing.
    assert [item.key for item in slideshow.shown.queue_foot.hud_queue[0]] == view._queue.keys() == ["gen1"]
    assert queue_section(*slideshow.shown.queue_foot.hud_queue).leader.key == "gen1"

    db.delete_generation("gen1")  # the job ends
    view._poll()
    assert queue_section(*slideshow.shown.queue_foot.hud_queue).lines == ()

    slideshow.close()


def test_a_row_dragged_in_the_slideshows_queue_moves_the_job_and_redraws_both_at_once(
        qtbot, monkeypatch):
    # The block on the slideshow's HUD lists the same line as the Job Queue and
    # asks for the same things, so it reaches the same queue, and both are drawn
    # again from its line the moment it moves.
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

    slideshow.shown.queue_foot.move("w2", "w1")  # the last waiting job, up one

    assert [item.key for item in slideshow.shown.queue_foot.hud_queue[0]] == ["gen1", "w2", "w1"]
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
    # Not a poll later: a row that sits still after the drop reads as one missed.
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
    # A queue row is a place in the gallery, not a settings form: clicking it
    # lands in the folder the job will appear in, with its live card selected.
    db = FakeDB([_running_row("gen1", prompt="a dog")])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    folder = gallery.settings_folder_key(
        db.get_generation("gen1"), gallery.build_image_config_index(view._image_rows))
    view._select_reroll = MagicMock()

    view._inflight_items()[0].reveal()

    assert _selected_folder(view) == folder             # the folder it will land in
    view._select_reroll.assert_called_once_with(folder)  # ...and its live card


def test_clicking_an_enhancements_row_in_the_queue_goes_to_its_image(qtbot, tmp_path):
    # An enhancement lands on the image it improves, never in a folder of its
    # own, so a click on its row that looked for its folder opened nothing.
    view = GalleryView(_enhanceable_db(tmp_path, count=2), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view.enhance_items(["g1"])
    view._tree.setCurrentItem(_image_workflow(view._tree))  # browse away from it
    view._update_queue()
    (row,) = view._queue.rows()

    qtbot.mouseClick(row, Qt.MouseButton.LeftButton)

    assert view.selected_prompt_ids() == ["g1"]
    assert view._browser._thumb_widgets["g1"]._selected
    assert view._info_tabs.current_config_panel().displayed_row()["prompt_id"] == "g1"


def test_the_strip_times_the_job_against_the_workflows_recent_runs(qtbot):
    # What the running half counts down from: the live job's own start time and
    # the median of what this workflow's finished runs actually took.
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
    assert item.reading.typical_seconds == 724.0   # the median of the three timed runs

    view._update_queue()
    assert view._queue._running.status_text() == "50% · 1:30 elapsed · ~6:02 left"


def test_the_strip_has_no_clock_for_a_job_still_queued(qtbot):
    # Nothing has begun, so there is no elapsed time to report — the wait on
    # ComfyUI is the queue beside it to explain.
    db = FakeDB([_image("done", "a cat", 50, 1)])
    db.add(_row("waiting", "sdxl_t2i", {"positive_prompt": "w"}, "waiting.png",
                status="pending", output_files="[]"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    assert view._inflight_items()[0].reading.started_at is None
    assert view._queue._running.status_text() == ""


def test_a_queued_job_carries_what_the_strip_leads_its_row_with(qtbot):
    # The price and the kind: the two things about a job that are true before it
    # starts, and what a line of waiting work is read for.
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
    # The one kind of job launched without looking at a form, and so the one
    # hardest to recognize later in the line.
    db = FakeDB([_image("src", "a kite", 50, 1)])
    db.add(_running_row("asked", prompt="a kite, no string"))
    db.record_request(prompt_id="asked", source_prompt_id="src",
                      heard="Request, no string, over.")
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
    # Its row shows that image: two i2v runs off one folder's settings are the same
    # caption and differ only in the frame.
    db = FakeDB([])
    db.add(_row("rr1", "wan22_i2v", {"input_image": "kite_00007_.png [output]"},
                "rr1.mp4", status="running", output_files="[]"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    assert view._inflight_items()[0].source_image == "kite_00007_.png [output]"


def test_an_enhancement_carries_the_image_it_is_a_second_pass_over(qtbot):
    # Same relation as a video's start frame: the image it is *of* is the whole
    # of what one enhancement in the line has to distinguish it from another.
    db = FakeDB([])
    db.add(_row("en1", "image_enhance", {"input_image": "kite_00007_.png [output]"},
                "en1.png", status="running", output_files="[]"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    assert view._inflight_items()[0].source_image == "kite_00007_.png [output]"


def test_an_image_that_takes_an_input_is_still_placed_by_its_folder(qtbot):
    # A pose transfer reads a structure image, but what it is making is an image
    # like any other — so its row is placed the way every image's is.
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
    # No act was picked, so the image is the only thing naming which source video
    # this run is of — and its row is where that gets read.
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
    assert item.act == ""
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


def test_a_picked_act_shows_no_source_video_at_all(qtbot):
    # The act names what the video will do, which is the whole of what was
    # chosen. The video its settings were mined out of answers a question nobody
    # asked, and an image of a video the user never picked reads as a job that
    # is that video.
    db = FakeDB([])
    db.add(_row("source", "wan22_i2v", {"positive_prompt": "dance"}, "source.mp4",
                thumbnail_path="thumbs/source.jpg"))
    db.add(_row("rr1", "wan22_i2v", {"input_image": "kite_00007_.png [output]"},
                "rr1.mp4", status="running", output_files="[]",
                act="dancing", source_video="source"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    item = {it.key: it for it in view._inflight_items()}["rr1"]
    assert item.act == "dancing"
    assert item.source_video_thumbnail is None


def test_a_run_that_came_from_no_combine_carries_neither(qtbot):
    db = FakeDB([])
    db.add(_row("rr1", "wan22_i2v", {"input_image": "kite_00007_.png [output]"},
                "rr1.mp4", status="running", output_files="[]"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    item = view._inflight_items()[0]
    assert item.act == ""
    assert item.source_video_thumbnail is None


def test_a_queued_job_carries_a_few_thumbnails_from_the_folder_it_joins(qtbot):
    # Its own output is the one image it cannot show, so its row is placed by
    # what the same settings made last time — newest first, four at most.
    settings = {"positive_prompt": "a kite", "steps": 50}
    db = FakeDB([])
    for i in range(6):  # oldest first, so the listing hands them back newest first
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
    )


def test_the_first_run_of_new_settings_has_no_folder_to_show(qtbot):
    # Nothing has landed there yet, so there is no folder in the tree at all —
    # and the row draws no block rather than an empty grid.
    db = FakeDB([_image("elsewhere", "a boat", 50, 1)])
    db.add(_row("waiting", "sdxl_t2i", {"positive_prompt": "a kite", "steps": 12},
                "waiting.png", status="pending", output_files="[]"))
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()

    items = {it.key: it for it in view._inflight_items()}
    assert items["waiting"].folder_thumbnails == ()


def _running_folder_key(view):
    """The settings-folder key the running wan22_i2v row above lands in."""
    return gallery.settings_folder_key(
        view._db.get_generation("rr1"),
        gallery.build_image_config_index(view._image_rows),
    )


def _finished_row_db(tmp_path):
    db = Database(tmp_path / "t.db")
    p = dict(_SDXL.default_params(), seed=1, positive_prompt="a cat")
    db.insert_generation(prompt_id="done", workflow_name="sdxl_t2i", workflow_version="v",
                         positive_prompt="a cat", seed=1,
                         params_json=json.dumps(p), workflow_json="{}")
    db.update_generation("done", status="completed",
                         output_files=json.dumps([{"filename": "sdxl_t2i_done.png"}]))
    return db


def test_generate_inflight_card_persists_across_navigation_and_polls(qtbot, tmp_path):
    # Real wiring, as the app builds it: a tab's Generate launches a re-roll, whose
    # in-flight card must stay on Recents across navigating to a folder and back, and
    # across poll ticks.
    client = ComfyUIClient(folders=SUITE_FOLDERS)
    client.submit_job = lambda payload, prompt_id: prompt_id
    client.fetch_history = lambda prompt_id: {}   # reconcile finds nothing done
    db = _finished_row_db(tmp_path)
    gv = GalleryView(db, client=client)
    qtbot.addWidget(gv)
    gv.refresh()
    gv._info_tabs._add_subtab()
    panel = _tab_with_prompts(gv)
    panel._param_form.set_values({"seed": 2, "positive_prompt": "a dog"})
    panel._on_generate()                          # emits generate_requested -> a re-roll
    (pid,) = [job.prompt_id for job in gv._live_jobs.values()]

    gv._tree.setCurrentItem(_collection(gv, RECENTS_KEY))
    assert pid in gv._browser._inflight_cards

    folder = _at(_image_workflow(gv._tree), 0, 0)
    gv._tree.setCurrentItem(folder)              # navigate away
    gv._tree.setCurrentItem(_collection(gv, RECENTS_KEY))    # and back
    assert pid in gv._browser._inflight_cards, "card vanished after navigating away and back"

    gv._poll()
    assert pid in gv._browser._inflight_cards, "card vanished after a poll"


def test_reroll_inflight_card_persists_across_navigation_and_polls(qtbot, tmp_path):
    client = ComfyUIClient(folders=SUITE_FOLDERS)
    client.submit_job = lambda payload, prompt_id: prompt_id
    client.fetch_history = lambda prompt_id: {}   # reconcile finds nothing done
    db = _finished_row_db(tmp_path)
    gv = GalleryView(db, client=client)
    qtbot.addWidget(gv)
    gv.refresh()

    folder_key = gallery.settings_folder_key(db.get_generation("done"))
    gv._start_reroll(folder_key)
    rr_pid = gv._live_jobs[folder_key].prompt_id

    gv._tree.setCurrentItem(_collection(gv, RECENTS_KEY))
    assert rr_pid in gv._browser._inflight_cards

    gv._tree.setCurrentItem(gv._tree_item_for(folder_key))  # into the re-roll's folder
    gv._tree.setCurrentItem(_collection(gv, RECENTS_KEY))             # and back
    assert rr_pid in gv._browser._inflight_cards, "re-roll card vanished after navigation"

    gv._poll()
    assert rr_pid in gv._browser._inflight_cards, "re-roll card vanished after a poll"


def test_i2v_reroll_inflight_card_follows_the_image_to_video_handoff(qtbot, tmp_path):
    # The user's real case: an i2v re-roll runs its image stage, then swaps to the
    # video stage under the same folder key (a new prompt id). The Recents card
    # must follow that handoff, on Recents and after navigating away and back.
    db = _seeded_i2v_db(tmp_path)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_leaf_of(view, "vid")
    _reroll_tile(view).add_requested.emit()
    img_job = view._live_jobs[key]

    view._tree.setCurrentItem(_collection(view, RECENTS_KEY))
    assert img_job.prompt_id in view._browser._inflight_cards

    client.job_completed.emit(img_job.prompt_id, _IMG_REROLL_HISTORY)  # image -> video
    vid_job = view._live_jobs[key]
    assert vid_job.prompt_id != img_job.prompt_id

    view._poll()
    assert vid_job.prompt_id in view._browser._inflight_cards, "video-stage card missing after handoff"

    view._tree.setCurrentItem(view._tree_item_for(key))   # away
    view._tree.setCurrentItem(_collection(view, RECENTS_KEY))        # and back
    assert vid_job.prompt_id in view._browser._inflight_cards, "video-stage card missing after navigation"


def test_recents_shows_a_running_reroll_row_with_no_live_job(qtbot, tmp_path):
    # A re-roll left running in the DB but not tracked by a live job — e.g. a
    # restart that didn't re-adopt it into _live_jobs — must still show as
    # in-flight. The card reflects the database, the source of truth for what is
    # in flight, not just the jobs this session happens to hold objects for.
    db = _finished_row_db(tmp_path)
    p = dict(_SDXL.default_params(), seed=5, positive_prompt="a wolf")
    db.insert_generation(prompt_id="rr_running", workflow_name="sdxl_t2i",
                         workflow_version="v", positive_prompt="a wolf", seed=5,
                         params_json=json.dumps(p), workflow_json="{}")
    db.update_generation("rr_running", status="running")
    gv = GalleryView(db, client=ComfyUIClient(folders=SUITE_FOLDERS))
    qtbot.addWidget(gv)
    gv.refresh()
    gv._tree.setCurrentItem(_collection(gv, RECENTS_KEY))

    assert "rr_running" in gv._browser._inflight_cards


# --- cancel the front tab's run, and remember an accepted random-seed choice ---


def test_generate_shows_the_front_tabs_cancel_button(qtbot, tmp_path):
    # A Generate launched from a tab makes that tab offer to cancel it, mirroring
    # the folder's live re-roll tile.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel = _front_panel(view)
    panel.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a brand new prompt"))

    panel._on_generate()

    assert view._live_jobs                          # a run is in flight
    assert panel._cancel_btn.isHidden() is False      # the tab offers to cancel it


def _two_image_db(tmp_path, prompts=("the first one", "a completely different one")):
    """Two completed images. Same prompt for both puts them in one settings folder;
    different prompts put them in two."""
    db = Database(tmp_path / "t.db")
    for (pid, prompt), seed in zip(zip(("a", "b"), prompts, strict=True), (7, 8), strict=True):
        params = dict(_SDXL.default_params(), seed=seed, positive_prompt=prompt)
        db.insert_generation(prompt_id=pid, workflow_name="sdxl_t2i",
                             workflow_version=_SDXL.version, positive_prompt=prompt,
                             seed=seed, params_json=json.dumps(params), workflow_json="{}")
        db.update_generation(pid, status="completed",
                             output_files=json.dumps([{"filename": f"sdxl_{pid}.png",
                                                       "subfolder": ""}]))
    return db


def _click_thumbnail(view, row, image_rows):
    """Load a browsed generation into the info pane, as clicking its tile does."""
    view._info_tabs.load_selection(row, image_rows)
    return _front_panel(view)


def test_another_image_of_the_folder_being_generated_cannot_be_generated_too(qtbot, tmp_path):
    # One item at a time per folder, whichever of its images is open: a folder
    # already making one takes no second Generate, and the tab on the other image
    # still does not claim the run it did not start.
    db = _two_image_db(tmp_path, prompts=("a shared prompt", "a shared prompt"))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    rows = {r["prompt_id"]: r for r in db.list_generations()}
    image_rows = list(rows.values())
    first = _click_thumbnail(view, rows["a"], image_rows)
    first.use_random_seed()  # a fresh sample, not a duplicate of what's on screen
    first._on_generate()
    assert len(view._jobs.all_jobs) == 1

    panel = _click_thumbnail(view, rows["b"], image_rows)

    assert panel._generating is False
    assert panel._generate_btn.isEnabled() is False

    panel.use_random_seed()
    panel._on_generate()

    assert len(view._jobs.all_jobs) == 1  # still the one being made


def test_another_images_tab_can_still_generate_while_the_first_runs(qtbot, tmp_path):
    # The reported block: Generate one image, click a completely different one, and
    # its tab came up already in progress mode — so the second one could not be
    # launched at all, and the button claimed a run that was not its own.
    db = _two_image_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    rows = {r["prompt_id"]: r for r in db.list_generations()}
    image_rows = list(rows.values())
    view._info_tabs.load_selection(rows["a"], image_rows)
    first = _front_panel(view)
    first._param_form.set_values({"positive_prompt": "a re-roll of the first one"})
    first._on_generate()

    view._info_tabs.load_selection(rows["b"], image_rows)

    second = _front_panel(view)
    assert second is not first
    assert second._generating is False
    assert second._generate_btn.text() == "Generate"
    assert second._generate_btn.isEnabled() is True
    assert second._cancel_btn.isHidden() is True


def test_a_setting_that_moves_the_folder_frees_generate_and_moving_back_grays_it(
        qtbot, tmp_path):
    # Reported: a run in flight grays Generate ("This folder is already making
    # one"), and a changed LoRA, which puts the next run in another folder, left
    # it grayed until the run ended. Any setting that moves the folder does it.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel = _front_panel(view)
    panel.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a brand new prompt"))
    panel.use_random_seed()
    panel._on_generate()
    assert panel._generate_btn.isEnabled() is False
    steps = panel._param_form._widgets["steps"]

    steps.setValue(_SDXL.default_params()["steps"] + 1)

    assert panel._generate_btn.isEnabled() is True
    qtbot.waitUntil(lambda: "already making" not in panel._generate_btn.toolTip())

    steps.setValue(_SDXL.default_params()["steps"])

    assert panel._generate_btn.isEnabled() is False
    qtbot.waitUntil(lambda: "already making" in panel._generate_btn.toolTip())


def test_finishing_a_reroll_hides_the_front_tabs_cancel_button(qtbot, tmp_path):
    # When the run ends the tab drops Cancel and Generate returns.
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    panel = _front_panel(view)
    panel.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a brand new prompt"))
    panel._on_generate()
    job = next(iter(view._live_jobs.values()))
    assert panel._cancel_btn.isHidden() is False

    client.job_completed.emit(job.prompt_id, _REROLL_HISTORY)

    assert view._live_jobs == {}
    assert panel._cancel_btn.isHidden() is True
    assert panel._generate_btn.isEnabled() is True


def test_a_tabs_cancel_stops_its_run_and_hands_the_folder_back(qtbot, tmp_path):
    # Its bar follows the run it started, so its Cancel stops that one, throws the
    # abandoned row away, and leaves the folder free to be generated into again.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel = _front_panel(view)
    panel.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a brand new prompt"))
    panel.use_random_seed()
    panel._on_generate()
    (being_made,) = [job.prompt_id for job in view._jobs.all_jobs]

    panel._cancel_btn.click()

    assert view._jobs.all_jobs == []
    assert view._db.get_generation(being_made) is None
    assert panel._generating is False
    assert panel._generate_btn.isEnabled() is True

    panel._on_generate()

    assert len(view._jobs.all_jobs) == 1


def test_cancel_works_on_a_run_launched_from_a_clicked_image(qtbot, tmp_path):
    # The path the user actually takes: click an image in the browser, Generate,
    # then Cancel. The tab is the one the click loaded, not one prefilled by hand.
    db = _two_image_db(tmp_path, prompts=("a shared prompt", "a shared prompt"))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    rows = {r["prompt_id"]: r for r in db.list_generations()}
    panel = _click_thumbnail(view, rows["a"], list(rows.values()))
    panel.use_random_seed()
    panel._on_generate()
    prompt_id = view._jobs.all_jobs[0].prompt_id
    assert panel._cancel_btn.isHidden() is False

    panel = _front_panel(view)
    panel._cancel_btn.click()

    assert view._jobs.all_jobs == []
    assert view._db.get_generation(prompt_id) is None


def test_clicking_the_tabs_cancel_button_stops_its_run(qtbot, tmp_path):
    # The button itself, not the signal under it: it is what the user presses.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel = _front_panel(view)
    panel.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a brand new prompt"))
    panel._on_generate()
    prompt_id = next(iter(view._live_jobs.values())).prompt_id

    panel._cancel_btn.click()

    assert view._jobs.all_jobs == []
    assert view._db.get_generation(prompt_id) is None


def test_canceling_from_the_front_tab_stops_the_reroll(qtbot, tmp_path):
    # The tab's Cancel stops the folder's re-roll exactly as the folder tile's does:
    # the job goes and its abandoned running row is dropped.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel = _front_panel(view)
    panel.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a brand new prompt"))
    panel._on_generate()
    prompt_id = next(iter(view._live_jobs.values())).prompt_id
    assert view._db.get_generation(prompt_id) is not None

    panel.cancel_requested.emit()

    assert view._live_jobs == {}
    assert view._db.get_generation(prompt_id) is None
    assert panel._cancel_btn.isHidden() is True


def test_a_duplicate_generate_switches_the_front_tab_to_a_random_seed(qtbot, tmp_path):
    # Re-rolling over a duplicate doesn't just re-seed this one launch — it switches
    # the front tab's seed to Random, so the form goes on saying what the next press
    # will do instead of showing a pinned seed no run will use again.
    db = _seeded_db(tmp_path, seed=42)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel = _front_panel(view)
    panel.prefill("sdxl_t2i", dict(_SDXL.default_params(), seed=42, positive_prompt="a cat"))
    assert panel.current_config().seed_is_random is False   # pinned to the duplicate seed

    panel._on_generate()

    assert panel.current_config().seed_is_random is True


def test_a_landed_generation_tells_an_open_tab_its_seed_is_now_a_duplicate(qtbot, tmp_path):
    # Nothing the user touched changed — the run they launched simply finished. A
    # tab still pinned to that seed would now reproduce the file, so its Generate
    # says so as the row lands rather than waiting for the form to be edited.
    db = Database(tmp_path / "test.db")
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel = _front_panel(view)
    params = dict(_SDXL.default_params(), seed=42, positive_prompt="a cat")
    panel.prefill("sdxl_t2i", params)
    qtbot.waitUntil(lambda: not panel._caption_timer.isActive())  # let it settle
    assert panel._generate_btn.text() == "Generate"   # nothing like it generated yet

    db.insert_generation(
        prompt_id="done", workflow_name="sdxl_t2i", workflow_version=_SDXL.version,
        positive_prompt="a cat", negative_prompt="", seed=42,
        params_json=json.dumps(params), workflow_json="{}",
    )
    db.update_generation("done", status="completed", output_files=json.dumps(
        [{"filename": "sdxl_done.png", "subfolder": ""}]))
    view.refresh()

    qtbot.waitUntil(lambda: panel._generate_btn.text() == "Generate with Random seed")


def test_the_random_seed_survives_a_cancel_so_re_generate_is_another_variation(qtbot, tmp_path):
    # The user's scenario: Generate over a duplicate, cancel that first attempt,
    # then Generate again. The tab kept the Random seed, so the second press is
    # another fresh variation rather than the pinned seed coming back.
    db = _seeded_db(tmp_path, seed=42)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel = _front_panel(view)
    panel.prefill("sdxl_t2i", dict(_SDXL.default_params(), seed=42, positive_prompt="a cat"))

    panel._on_generate()                 # duplicate → a fresh seed, no question asked
    first = next(iter(view._live_jobs.values())).params["seed"]
    key = next(iter(view._live_jobs))
    view._cancel_reroll(key)             # cancel the first attempt
    assert view._live_jobs == {}

    panel._on_generate()                 # Generate again

    launched = next(iter(view._live_jobs.values())).params["seed"]
    assert launched not in (42, first)   # another variation, not the pinned seed


def test_unticking_random_after_a_generate_keeps_the_seed_that_made_it(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel = _front_panel(view)
    panel.prefill("sdxl_t2i", dict(_SDXL.default_params(), positive_prompt="a brand new prompt"))
    panel._param_form.set_seed_random(True)
    panel._on_generate()
    (made,) = view._live_jobs.values()
    _finish_reroll(view, made)

    panel._param_form.set_seed_random(False)
    panel._param_form._widgets["positive_prompt"].boxes()[0].setPlainText(
        "a brand new prompt, at dusk")
    panel._on_generate()

    (tweaked,) = view._live_jobs.values()
    assert tweaked.params["seed"] == made.params["seed"]


# --- the line's answer to the press, before there is a job ------------------


def test_pressing_generate_shows_a_row_before_there_is_a_job(qtbot, tmp_path, monkeypatch):
    # Checking every stored generation for a duplicate, building the params and
    # posting the prompt all run on this thread; with nothing on screen for that
    # stretch the button reads as one that did nothing.
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    deferred = []
    monkeypatch.setattr(view._combine, "_after_painting", deferred.append)

    view._combine.panel.combine_requested.emit(
        CombineRequest(image_id="img", video_id="vid",
                       intent=view._combine.panel.selected_intent()))

    row, = view._queue.rows()
    assert row._note_text == "Starting…"
    assert view._live_jobs == {}    # and nothing has been submitted for it yet

    deferred[0]()                     # the launch the row was standing in for

    assert len(view._live_jobs) == 1
    assert not any(item.starting for item in view._queue._items)


def test_the_stand_in_row_already_carries_the_act_that_was_picked(qtbot, tmp_path, monkeypatch):
    # It is the row that will replace it, minus the price: so the line doesn't
    # blink one thing away and a different-looking one in.
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(view._combine, "_after_painting", lambda work: None)

    view._combine._on_generate_category("img", "dancing", act_settings.VIDEO)

    item = view._queue._items[0]
    assert item.act == "dancing"
    assert item.source_image == "sdxl_pick.png [output]"  # the frame being animated
    assert item.source_video_thumbnail is None  # an act names itself; no clip to show
    assert item.cancel is None            # nothing on the server to stop yet


def test_the_stand_in_row_shows_the_dropped_video(qtbot, tmp_path, monkeypatch):
    db = _combine_db(tmp_path)
    db.update_generation("vid", thumbnail_path="thumbs/vid.jpg")
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(view._combine, "_after_painting", lambda work: None)

    view._combine.panel.combine_requested.emit(
        CombineRequest(image_id="img", video_id="vid",
                       intent=view._combine.panel.selected_intent()))

    item = view._queue._items[0]
    assert item.source_video_thumbnail == "thumbs/vid.jpg"
    assert item.act == ""


def test_the_stand_in_row_goes_when_the_act_has_no_past_video(qtbot, tmp_path, monkeypatch):
    # It stands in for a launch, so it must not outlive one that never happened.
    db = _combine_db(tmp_path)  # its one video is a "dance" video: no epsilon video
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(gallery_view_module.QMessageBox, "information", lambda *a, **k: None)

    view._combine._on_generate_category("img", "epsilon", act_settings.VIDEO)

    assert view._queue.rows() == []
    assert view._live_jobs == {}


def test_the_stand_in_row_goes_when_the_dropped_image_is_gone(qtbot, tmp_path, monkeypatch):
    # An image that is gone has no settings looked up for it; the row must go too.
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._on_generate_category("missing", "dancing", act_settings.VIDEO)

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


# --- somebody else's queue on the shared ComfyUI ----------------------------


class _QueueClient(ComfyUIClient):
    """A client whose ComfyUI queue holds ``foreign`` jobs of another app's."""

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
        return self._foreign.total


def _queue_view(qtbot, client):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), client=client)
    qtbot.addWidget(view)
    view.refresh()
    return view


def test_the_strip_names_another_apps_queue_before_generate_is_pressed(qtbot):
    # The reported bug: the queue read as free, then Generate reported six jobs
    # ahead of it out of nowhere. Polling the server's own queue is what lets the
    # Job Queue say so while nothing of ours is in flight at all.
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
    # ComfyUI restarting mid-poll must not leave a count on screen offering to
    # clear a queue the app can no longer see.
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
    # What the user asked for: a way out from under a queue he didn't fill,
    # instead of waiting out a batch no window here can account for.
    client = _QueueClient(ForeignQueue(running=["r"], pending=["a", "b"]))
    view = _queue_view(qtbot, client)
    view._poll()
    _answer_confirmation(monkeypatch, QMessageBox.StandardButton.Yes)

    view._queue._clear.click()

    assert client.cleared == 1


def test_clearing_can_be_declined_at_the_prompt(qtbot, monkeypatch):
    client = _QueueClient(ForeignQueue(running=[], pending=["a"]))
    view = _queue_view(qtbot, client)
    view._poll()
    _answer_confirmation(monkeypatch, QMessageBox.StandardButton.No)  # user says no

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

    view._queue._clear.click()  # must not raise

    assert warned


def test_a_cleared_queue_blanks_the_bar_without_waiting_for_a_poll(qtbot):
    client = _QueueClient(ForeignQueue(running=[], pending=["a", "b"]))
    view = _queue_view(qtbot, client)
    view._poll()
    view._confirm_clear_queue = lambda total: True

    client._foreign = ForeignQueue(running=[], pending=[])  # the clear empties it
    view._queue._clear.click()

    assert view._queue._running.status_text() == ""
    assert view._queue._clear.isHidden()


# --- Cancel All, which asks first -------------------------------------------------


def _cancelable(key, cancelled):
    return InFlightItem(key=key, caption="Alpha Workflow › a paper kite",
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
    # So nothing waiting starts only to be stopped a moment later.
    cancelled = []
    view = _view_holding(qtbot, monkeypatch, [_cancelable(key, cancelled)
                                              for key in ("a", "b", "c")])
    _answer_confirmation(monkeypatch, QMessageBox.StandardButton.Yes)

    view._queue._cancel_all.click()

    assert cancelled == ["c", "b", "a"]


def test_cancel_all_asks_about_the_jobs_it_would_cancel(qtbot, monkeypatch):
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda _parent, title, text, *_a, **_kw: asked.append((title, text))
        or QMessageBox.StandardButton.No))
    for held in ([_cancelable("a", []), _cancelable("b", []),
                  InFlightItem(key="c", caption="Alpha Workflow › a paper kite",
                               reading=RunReading(status="queued"), reveal=lambda: None)],
                 [_cancelable("a", [])]):
        _view_holding(qtbot, monkeypatch, held)._queue._cancel_all.click()

    assert asked == [("Cancel All", "Cancel all 2 jobs in the Job Queue?"),
                     ("Cancel All", "Cancel the job in the Job Queue?")]


def test_cancel_all_leaves_auto_generate_on_to_start_its_next_seed(
        qtbot, tmp_path, monkeypatch):
    # His call (2026-10-28): Cancel All does not switch Auto-Generate off.
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._toggle_auto(True)
    (job,) = view._jobs.all_jobs
    view.refresh()
    _answer_confirmation(monkeypatch, QMessageBox.StandardButton.Yes)

    view._queue._cancel_all.click()

    assert view._auto.is_active(key)
    (next_seed,) = view._jobs.all_jobs
    assert next_seed.prompt_id != job.prompt_id
