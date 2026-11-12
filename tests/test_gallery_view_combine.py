from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from PIL import Image
from PyQt6 import sip
from PyQt6.QtCore import (
    QPoint,
    Qt,
)
from PyQt6.QtGui import (
    QDrag,
    QPixmap,
)

from origenerator import (
    action_settings,
    gallery,
)
from origenerator.db import Database, NewGeneration
from origenerator.gallery.collection import (
    LATEST_KEY,
)
from origenerator.generation_state import GenerationStatus
from origenerator.gui import (
    combine_controller,
)
from origenerator.gui import gallery_view as gallery_view_module
from origenerator.gui import generate_tab as generate_tab_module
from origenerator.gui import generating_tile as generating_tile_module
from origenerator.gui.combine import CombineRequest
from origenerator.gui.drags import under_way
from origenerator.gui.gallery_view import _GROUP_ROLE, GalleryView
from origenerator.gui.generation_drag import generation_mime
from origenerator.gui.item_tile import ItemTile
from origenerator.item_actions import ItemActions, actions_of
from origenerator.media import MediaType
from origenerator.output_places import OutputPlaces
from origenerator.workflows import WORKFLOW_REGISTRY, offered_workflows
from tests import drops
from tests.gallery_view_support import (
    _SDXL,
    _VID_REROLL_HISTORY,
    _WAN_I2V,
    _collection,
    _combine_db,
    _front_panel,
    _reroll_client,
    _selected_folder,
    _write_looping_webp,
)
from tests.related_links import settings_tile, source_tile
from tests.test_combine import _listed_under_recent

pytestmark = pytest.mark.usefixtures("_stub_preview_resolution")



def _looping_video(db, prompt_id="loop"):
    wf = WORKFLOW_REGISTRY["wan22_flf2v_loop"]
    db.insert_generation(NewGeneration(
        prompt_id=prompt_id, workflow_name=wf.name, workflow_version=wf.version,
        positive_prompt="alpha", seed=8,
        params_json=json.dumps(dict(wf.default_params(), seed=8,
                                    positive_prompt="alpha")),
        workflow_json="{}"))
    db.update_generation(prompt_id, status="completed", output_files=json.dumps(
        [{"filename": "flf2v_loop_01.mp4", "subfolder": "video"}]))
    return wf


def test_the_genau_lane_asks_for_settings_one_cycle_long(qtbot, tmp_path):
    db = _combine_db(tmp_path)
    wf = _looping_video(db)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._generate_combination("img", "loop", intent=action_settings.GENAU)

    job = next(iter(view._live_jobs.values()))
    assert job.params["frame_count"] == gallery.CYCLE_FRAMES, (
        "the lane cuts the settings again and does not only choose which are mined: what Genau "
        "needs of a video is a property of the video's own length, and the past video being "
        "mined was made before anyone knew that")
    assert job.params["frame_rate"] > wf.default_params()["frame_rate"]
    assert job.params["positive_prompt"] != "alpha"


def test_the_action_chooses_which_cycle_words_the_lane_adds(qtbot, tmp_path):
    db = _combine_db(tmp_path)
    _looping_video(db)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    asked = []
    real = gallery.cycle_shaped
    view._db  # noqa: B018  (the view is built; patch after)

    def spy(params, workflow, *names):
        asked.append(names)
        return real(params, workflow, *names)

    gallery_view_module.gallery.cycle_shaped = spy
    try:
        view._combine._generate_combination("img", "loop", intent=action_settings.GENAU,
                                            category="beta")
    finally:
        gallery_view_module.gallery.cycle_shaped = real

    assert asked == [("beta",)]


def test_the_video_lane_takes_the_mined_settings_as_they_stand(qtbot, tmp_path):
    db = _combine_db(tmp_path)
    wf = _looping_video(db)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._generate_combination("img", "loop")

    job = next(iter(view._live_jobs.values()))
    assert job.params["frame_count"] == wf.default_params()["frame_count"], (
        "a video for a Funestra is watched at its own rate, and wants the settings that made the "
        "one it was mined from")
    assert job.params["frame_rate"] == wf.default_params()["frame_rate"], (
        "a video for a Funestra is watched at its own rate, and wants the settings that made the "
        "one it was mined from")
    assert job.params["positive_prompt"] == "alpha"


def test_combine_submits_the_settings_on_the_dropped_image_with_a_fresh_seed(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._generate_combination("img", "vid")

    assert len(view._live_jobs) == 1
    job = next(iter(view._live_jobs.values()))
    assert job.workflow.name == "wan22_i2v"
    assert job.params["input_image"] == "sdxl_pick.png [output]"
    assert job.params["noise_seed"] != 99
    view._client.submit_job.assert_called_once()


def test_a_combine_on_an_image_never_enhanced_enhances_it_and_makes_the_video_from_that(
        qtbot, tmp_path):
    db = _combine_db(tmp_path, enhanced=False)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._generate_combination("img", "vid")
    (enhance,) = [job for job in view._jobs.all_jobs if job.enhances]
    enhance.finished.emit([{"filename": "image_enhance_00001_.png", "subfolder": "image"}],
                          None, 1.0)
    view._jobs.start_now()

    first, then = [call.args for call in view._client.submit_job.call_args_list]
    assert first[1] == enhance.prompt_id
    assert "image/image_enhance_00001_.png [output]" in json.dumps(then[0])
    assert gallery.row_output_files(db.get_generation("img"))[0]["filename"] \
        == "image_enhance_00001_.png"


def test_open_combination_prefills_a_generate_tab_without_launching(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._open_combination("img", "vid")

    assert view._live_jobs == {}
    view._client.submit_job.assert_not_called()
    config = view._generate_pane.current_generate_tab().current_config()
    assert config.workflow_name == "wan22_i2v"
    assert config.params["input_image"] == "sdxl_pick.png [output]"
    assert config.seed_is_random, (
        "a new take of the motion, never the source video's own seed")


def test_the_tab_edit_individual_opens_lists_only_the_video_workflows(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._open_combination("img", "vid")

    dropdown = view._generate_pane.current_generate_tab()._workflow_dropdown
    assert [dropdown.itemData(i) for i in range(dropdown.count())] == [
        workflow.name for workflow in offered_workflows(makes=MediaType.VIDEO)]


def test_open_combination_takes_over_the_blank_tab_and_marks_it_italic(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    tabs = view._generate_pane
    before = tabs.count()

    view._combine._open_combination("img", "vid")

    assert tabs.count() == before
    tab = tabs.current_generate_tab()
    assert tabs.tabBar()._preview_index == tabs.indexOf(tab)


def test_edit_individual_in_the_genau_lane_opens_the_looping_workflow_as_it_starts(
        qtbot, tmp_path, monkeypatch):
    db = _combine_db(tmp_path)
    looping = _looping_video(db)
    db.set_settings_source("loop", category="alpha")
    db.set_actions("loop", MediaType.VIDEO, ItemActions(("alpha",)))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    shown = []
    monkeypatch.setattr(gallery_view_module.QMessageBox, "information",
                        lambda *a, **k: shown.append(a[1:]))

    view._combine._open_category("img", "alpha", action_settings.GENAU)

    assert view._live_jobs == {}
    view._client.submit_job.assert_not_called()
    assert shown == []
    config = view._generate_pane.current_generate_tab().current_config()
    assert WORKFLOW_REGISTRY[config.workflow_name].display_name == (
        "WAN 2.2 I2V (Looping)")
    assert config.params["input_image"] == "sdxl_pick.png [output]"
    assert (config.params["positive_prompt"], config.params["negative_prompt"]) == ("", "")
    assert config.params["frame_count"] == looping.default_params()["frame_count"]
    assert config.seed_is_random


def test_combine_open_buttons_are_wired_to_the_view(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine.widget.combine_requested.emit(CombineRequest(
        image_id="img", video_id="vid", edit_first=True))

    assert view._live_jobs == {}
    config = view._generate_pane.current_generate_tab().current_config()
    assert config.workflow_name == "wan22_i2v"
    assert config.params["input_image"] == "sdxl_pick.png [output]"


def _insert_completed_video(db, prompt_id, params, filename):
    db.insert_generation(NewGeneration(
        prompt_id=prompt_id, workflow_name="wan22_i2v", workflow_version=_WAN_I2V.version,
        positive_prompt=params.get("positive_prompt", ""), negative_prompt="",
        seed=params.get("seed"), params_json=json.dumps(params), workflow_json="{}",
    ))
    db.update_generation(prompt_id, status="completed",
                         output_files=json.dumps([{"filename": filename, "subfolder": ""}]))


def test_the_combine_is_up_under_the_folders_when_comfyui_can_be_reached(qtbot, tmp_path):
    view = GalleryView(Database(tmp_path / "test.db"), client=_reroll_client())
    qtbot.addWidget(view)
    view.show()

    assert view._combine.widget.isVisible()


def test_without_comfyui_the_combine_takes_its_section_with_it(qtbot, tmp_path):
    view = GalleryView(Database(tmp_path / "test.db"))
    qtbot.addWidget(view)
    view.show()

    assert not view._combine.widget.parentWidget().isVisible()


def test_combining_a_pair_already_made_makes_another_video(qtbot, tmp_path):
    db = _combine_db(tmp_path)
    made = {**json.loads(db.get_generation("vid")["params_json"]),
            "input_image": "sdxl_pick.png [output]"}
    _insert_completed_video(db, "made", made, "wan22_i2v_made.mp4")
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._generate_combination("img", "vid")

    (job,) = view._live_jobs.values()
    assert job.workflow.name == "wan22_i2v"
    assert job.params["noise_seed"] != made["noise_seed"]


def test_combine_noop_for_an_unknown_video_workflow(qtbot, tmp_path):
    db = _combine_db(tmp_path)
    db.insert_generation(NewGeneration(prompt_id="vx", workflow_name="mystery", workflow_version="v",
                         positive_prompt="", seed=1, params_json=json.dumps({"seed": 1}),
                         workflow_json="{}"))
    db.update_generation("vx", status="completed",
                         output_files=json.dumps([{"filename": "mystery_vx.mp4", "subfolder": ""}]))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._generate_combination("img", "vx")

    assert view._live_jobs == {}
    view._client.submit_job.assert_not_called()


def test_combine_noop_when_the_image_has_no_output_file(qtbot, tmp_path):
    db = _combine_db(tmp_path)
    db.update_generation("img", output_files=json.dumps([]))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._generate_combination("img", "vid")

    assert view._live_jobs == {}


def test_category_runs_the_actions_most_used_video(qtbot, tmp_path):
    db = _combine_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine.generate_category("img", "alpha")

    job = next(iter(view._live_jobs.values()))
    assert job.workflow.name == "wan22_i2v"
    assert job.params["input_image"] == "sdxl_pick.png [output]"


def test_refresh_greys_out_the_actions_with_no_video_to_mine(qtbot, tmp_path):
    db = _combine_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)

    view.refresh()

    dropdown = view._combine.widget._category
    enabled = {dropdown.itemText(i) for i in range(1, dropdown.count())
               if dropdown.model().item(i).isEnabled()}
    assert enabled == {"alpha"}


def test_category_prefers_the_overlays_pinned_settings_over_mining(qtbot, tmp_path, monkeypatch):
    db = _combine_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(combine_controller.action_settings, "most_used_video",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("curated action must not mine")))

    view._combine.generate_category("img", "alpha + third box")

    job = next(iter(view._live_jobs.values()))
    assert job.workflow.name == "wan22_i2v"
    assert job.params["input_image"] == "sdxl_pick.png [output]"
    assert job.params["lora_high"] == "example-action-high.safetensors"
    assert job.params["steps"] == 24



def _launched_row(view):
    job = next(iter(view._live_jobs.values()))
    return view._db.get_generation(job.prompt_id)


def test_settings_from_a_dropped_video_name_that_video(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._generate_combination("img", "vid")

    row = _launched_row(view)
    assert row["source_video"] == "vid"
    assert row["action"] is None


def test_recent_already_lists_a_video_generated_from_before_this_session(qtbot, tmp_path):
    db = _combine_db(tmp_path)
    db.insert_generation(NewGeneration(prompt_id="made", workflow_name="wan22_i2v",
                         workflow_version=_WAN_I2V.version, params_json="{}", workflow_json="{}"))
    db.set_settings_source("made", video_prompt_id="vid")
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    combine = view._combine.widget

    assert _listed_under_recent(combine) == ["vid"]
    combine.set_intent(action_settings.GENAU)
    assert _listed_under_recent(combine) == []


def _view_with_a_looping_video(qtbot, tmp_path):
    db = _combine_db(tmp_path)
    _looping_video(db, "looping")
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    return view


def test_recent_under_kino_leaves_out_a_looping_video_used_under_kino(qtbot, tmp_path):
    combine = _view_with_a_looping_video(qtbot, tmp_path)._combine.widget

    combine.video_zone.set_item("vid")
    combine.video_zone.set_item("looping")

    assert _listed_under_recent(combine) == ["vid"]


def test_recent_under_genau_lists_a_looping_video_used_under_kino(qtbot, tmp_path):
    combine = _view_with_a_looping_video(qtbot, tmp_path)._combine.widget

    combine.video_zone.set_item("looping")
    combine.set_intent(action_settings.GENAU)

    assert _listed_under_recent(combine) == ["looping"]


def test_recent_under_genau_leaves_out_a_full_length_video_used_under_genau(qtbot, tmp_path):
    combine = _view_with_a_looping_video(qtbot, tmp_path)._combine.widget
    combine.set_intent(action_settings.GENAU)

    combine.video_zone.set_item("looping")
    combine.video_zone.set_item("vid")

    assert _listed_under_recent(combine) == ["looping"]


def test_a_picked_action_is_recorded_with_the_video_it_resolved_to(qtbot, tmp_path, monkeypatch):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine.generate_category("img", "alpha")

    row = _launched_row(view)
    assert row["action"] == "alpha"
    assert actions_of(row, MediaType.VIDEO) == ItemActions(("alpha",))
    assert row["source_video"] == "vid"


def test_a_curated_action_records_the_action_with_no_video_behind_it(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine.generate_category("img", "alpha + third box")

    row = _launched_row(view)
    assert row["action"] == "alpha + third box"
    assert actions_of(row, MediaType.VIDEO) == ItemActions(("alpha",), ("third box",))
    assert row["source_video"] is None


def test_open_in_generator_marks_the_tab_with_where_the_settings_came_from(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._open_combination("img", "vid")

    assert _front_panel(view).settings_source() == ("", "vid", action_settings.VIDEO, ())


def test_a_generate_from_an_opened_combination_still_names_its_video(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view._combine._open_combination("img", "vid")
    tab = _front_panel(view)
    tab._param_form.set_values({"positive_prompt": "edited before running"})

    tab._on_generate()

    assert _launched_row(view)["source_video"] == "vid"


def test_a_generate_from_an_opened_dropped_video_notes_the_lane_it_was_opened_under(
        qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view._combine._open_combination("img", "vid", intent=action_settings.GENAU)

    _front_panel(view)._on_generate()

    noted = [(use["intent"], use["video_prompt_id"], use["generation_prompt_id"])
             for use in view._db.list_combine_video_uses()]
    assert noted == [(action_settings.GENAU, "vid", _launched_row(view)["prompt_id"])]


def test_a_tab_pointed_at_another_generation_drops_the_settings_source(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view._combine._open_combination("img", "vid")
    tab = _front_panel(view)

    tab.show_saved_generation(view._db.get_generation("vid"), view._image_rows)

    assert tab.settings_source() == ("", None, "", ())


def test_a_tab_switched_to_another_workflow_drops_the_settings_source(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view._combine._open_combination("img", "vid")
    tab = _front_panel(view)

    tab.prefill("sdxl_t2i", _SDXL.default_params())

    assert tab.settings_source() == ("", None, "", ())


def test_open_in_generator_shows_the_pair_rather_than_an_empty_pane(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._open_combination("img", "vid")

    preview = _front_panel(view)._viewport
    assert preview._stack.currentWidget() is preview._combination


def test_open_in_generator_links_to_the_image_and_the_video_before_generating(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._open_combination("img", "vid")

    related = _front_panel(view)._related
    assert not source_tile(related).isHidden()
    assert source_tile(related)._prompt_id == "img"
    assert not settings_tile(related).isHidden()
    assert settings_tile(related)._prompt_id == "vid"


def test_the_video_an_opened_combination_makes_keeps_both_links(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_combine_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    view._combine._open_combination("img", "vid")
    tab = _front_panel(view)
    tab._on_generate()
    job = next(iter(view._live_jobs.values()))

    client.job_completed.emit(job.prompt_id, _VID_REROLL_HISTORY)

    assert tab.displayed_row()["prompt_id"] == job.prompt_id
    assert source_tile(tab._related)._prompt_id == "img"
    assert settings_tile(tab._related)._prompt_id == "vid"
    assert not settings_tile(tab._related).isHidden()


def test_an_action_whose_settings_came_from_no_video_links_to_the_image_alone(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._open_category("img", "alpha + third box")

    related = _front_panel(view)._related
    assert source_tile(related)._prompt_id == "img"
    assert settings_tile(related).isHidden()


def _combine_view_with_a_looping_video(qtbot, tmp_path):
    video = str(_write_looping_webp(tmp_path / "vid_anim.webp"))
    class _Showing(GalleryView):
        def animated_preview(self, row):
            return video

    view = _Showing(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    return view


def _opened_combination(qtbot, tmp_path, intent=action_settings.VIDEO):
    view = _combine_view_with_a_looping_video(qtbot, tmp_path)
    view._combine._open_combination("img", "vid", intent=intent)
    return view, _front_panel(view)


def test_a_combination_opened_for_genau_has_its_source_video_in_parentheses_before_any_edit(
        qtbot, tmp_path):
    _view, tab = _opened_combination(qtbot, tmp_path, intent=action_settings.GENAU)

    assert not tab._viewport._combination.open_paren_label.isHidden()


@pytest.mark.parametrize(("key", "as_made", "edited"), [
    ("positive_prompt", "dance", "dance in the rain"),
    ("negative_prompt", "", "blurry"),
])
def test_the_clip_of_an_opened_combination_stands_in_parentheses_while_its_prompt_differs(
        qtbot, tmp_path, key, as_made, edited):
    _view, tab = _opened_combination(qtbot, tmp_path)
    parens = tab._viewport._combination.open_paren_label
    assert parens.isHidden()

    tab._param_form.set_values({key: edited})
    assert not parens.isHidden()

    tab._param_form.set_values({key: as_made})
    assert parens.isHidden()


def test_a_run_from_an_edited_combination_keeps_its_source_video_in_parentheses_while_it_waits(
        qtbot, tmp_path, monkeypatch):
    drawn = []
    monkeypatch.setattr(generating_tile_module, "combination_pixmap",
                        lambda made_from, size: drawn.append(made_from))
    _view, tab = _opened_combination(qtbot, tmp_path)
    tab._param_form.set_values({"positive_prompt": "dance in the rain"})

    tab._on_generate()

    assert drawn[-1].prompt_edited
    assert tab._live_source.prompt_edited


def test_a_genau_run_straight_from_the_combine_waits_with_its_source_video_in_parentheses(
        qtbot, tmp_path):
    view = _combine_view_with_a_looping_video(qtbot, tmp_path)

    view._combine._generate_combination("img", "vid", intent=action_settings.GENAU)
    view._select_reroll(next(iter(view._live_jobs)))

    assert _front_panel(view)._live_source.prompt_edited


@pytest.mark.parametrize(("lane", "stands_apart"), [(action_settings.VIDEO, False),
                                                    (action_settings.GENAU, True)])
def test_a_pressed_combine_stands_in_line_with_its_source_video_marked_as_its_run_will_be(
        qtbot, tmp_path, monkeypatch, lane, stands_apart):
    view = _combine_view(qtbot, tmp_path)
    monkeypatch.setattr(view._combine, "_after_painting", lambda work: None)
    _pick_lane(view._combine.widget, lane)

    view._combine.widget.combine_requested.emit(
        CombineRequest(image_id="img", video_id="vid",
                       intent=view._combine.widget.selected_intent()))

    (standing,) = view._starting.rows()
    assert standing.prompt_edited is stands_apart


def test_changing_a_setting_other_than_the_prompt_leaves_the_clip_out_of_parentheses(
        qtbot, tmp_path):
    _view, tab = _opened_combination(qtbot, tmp_path)

    tab._param_form.set_values({"seed": 7})

    assert tab._viewport._combination.open_paren_label.isHidden()


@pytest.mark.parametrize(("zone_name", "prompt_id"), [("image_zone", "img"),
                                                      ("video_zone", "vid")])
def test_clicking_a_combine_drop_zone_goes_to_what_it_holds(qtbot, tmp_path, zone_name, prompt_id):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    zone = getattr(view._combine.widget, zone_name)
    zone.set_item(prompt_id)

    qtbot.mouseClick(zone, Qt.MouseButton.LeftButton)

    assert view.selected_prompt_ids() == [prompt_id]
    assert zone.current_id() == prompt_id


def test_combines_drop_zones_name_what_was_dropped_on_them(qtbot, tmp_path):
    view = _combine_view(qtbot, tmp_path)
    combine = view._combine.widget

    drops.let_go_over(combine.image_zone, "img")
    drops.let_go_over(combine.video_zone, "vid")

    named = (combine.image_zone._caption.text(), combine.video_zone._caption.text())
    assert named == (view._item_names.of("img"), view._item_names.of("vid"))
    assert "" not in named


def test_what_a_launch_puts_back_in_combine_is_named_once_the_gallery_draws(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.restore_combine_selection({"image": "img", "videos": {action_settings.VIDEO: "vid"}})

    view.refresh()

    combine = view._combine.widget
    named = (combine.image_zone._caption.text(), combine.video_zone._caption.text())
    assert named == (view._item_names.of("img"), view._item_names.of("vid"))
    assert "" not in named


def test_a_start_image_a_launch_puts_back_is_named_once_the_gallery_draws(qtbot, tmp_path,
                                                                          monkeypatch):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    Image.new("RGB", (8, 8)).save(output_dir / "sdxl_pick.png")
    monkeypatch.setattr(generate_tab_module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output_dir))
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    tab = view._generate_pane.current_generate_tab()
    tab._workflow_dropdown.setCurrentIndex(tab._workflow_dropdown.findData("wan22_i2v"))
    start = tab._param_form._widgets["input_image"]
    tab._param_form.set_values({"input_image": "sdxl_pick.png [output]"})

    view.refresh()

    assert start._caption.text() == view._item_names.of("img") != ""


def test_an_image_browsed_into_combine_offers_no_way_into_the_gallery(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view.follow_link("img")
    zone = view._combine.widget.image_zone
    zone.set_item(str(tmp_path / "scene one.png"))

    qtbot.mouseClick(zone, Qt.MouseButton.LeftButton)

    assert zone.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert view.selected_prompt_ids() == ["img"]


def test_a_pair_opened_in_a_tab_holds_the_settings_generate_would_launch(
        qtbot, tmp_path, monkeypatch):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(view._combine, "_after_painting", lambda work: work())
    opened = []
    monkeypatch.setattr(view._generate_pane, "open_config",
                        lambda name, params: opened.append((name, params)))
    lane = view._combine.widget.selected_intent()

    view._combine.widget.combine_requested.emit(
        CombineRequest(image_id="img", video_id="vid", intent=lane, edit_first=True))
    view._combine.widget.combine_requested.emit(
        CombineRequest(image_id="img", video_id="vid", intent=lane))

    (name, in_the_tab), = opened
    (job,) = view._live_jobs.values()
    seeds = set(job.workflow.seed_keys())
    launched = {key: value for key, value in job.params.items() if key not in seeds}
    assert (job.workflow.name, launched) == (
        name, {key: value for key, value in in_the_tab.items() if key not in seeds}), (
        "the tab is prefilled with the same combination Generate would launch, ready to tweak")


def test_open_category_prefers_the_pinned_settings_too(qtbot, tmp_path, monkeypatch):
    db = _combine_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(combine_controller.action_settings, "most_used_video",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("curated action must not mine")))
    opened = []
    monkeypatch.setattr(view._generate_pane, "open_config",
                        lambda name, params: opened.append((name, params)))

    view._combine._open_category("img", "alpha + third box")

    (name, params), = opened
    assert name == "wan22_i2v"
    assert params["input_image"] == "sdxl_pick.png [output]"
    assert params["lora_high"] == "example-action-high.safetensors"


def test_category_noop_and_hints_when_the_action_has_no_video(qtbot, tmp_path, monkeypatch):
    db = _combine_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    shown = []
    monkeypatch.setattr(gallery_view_module.QMessageBox, "information",
                        lambda *a, **k: shown.append(a))

    view._combine.generate_category("img", "beta")

    assert view._live_jobs == {}
    view._client.submit_job.assert_not_called()
    assert shown


def test_combine_new_folder_lands_on_latest_then_reveals_on_finish(qtbot, tmp_path):
    db = _combine_db(tmp_path)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()

    view._combine._generate_combination("img", "vid")

    assert view._gallery_pane.showing_latest(), (
        "the fixture video was made from no image, so a combination, filed by the image dropped "
        "on it, opens a folder of its own rather than joining the video's, and waits on Latest "
        "until it lands")
    prompt_id = next(iter(view._live_jobs.values())).prompt_id

    client.job_completed.emit(prompt_id, _VID_REROLL_HISTORY)

    assert not view._gallery_pane.showing_latest()
    new_row = db.get_generation(prompt_id)
    image_rows = [r for r in db.list_generations() if gallery.media_type_of_row(r) == "image"]
    expected = gallery.settings_folder_key(new_row, gallery.build_image_config_index(image_rows))
    assert _selected_folder(view) == expected


def test_combine_existing_folder_is_opened_with_the_live_tile(qtbot, tmp_path):
    db = _combine_db(tmp_path)
    sib = dict(_WAN_I2V.default_params(), seed=7, noise_seed=7, positive_prompt="dance",
               input_image="sdxl_pick.png [output]")
    _insert_completed_video(db, "vsib", sib, "wan22_i2v_vsib.mp4")
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._generate_combination("img", "vid")

    expected = view._leaf_by_id["vsib"].data(0, _GROUP_ROLE).key
    assert not view._gallery_pane.showing_latest()
    assert _selected_folder(view) == expected
    assert view._selected_reroll_key == expected


def test_a_combine_left_running_comes_back_after_a_restart_in_its_folder(qtbot, tmp_path):
    db = _combine_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view._combine._generate_combination("img", "vid")
    (key,) = view._live_jobs
    prompt_id = view._live_jobs[key].prompt_id
    assert db.get_generation(prompt_id)["status"] == GenerationStatus.RUNNING
    client = _reroll_client()
    client.executing_prompts = MagicMock(return_value={prompt_id})
    reopened = GalleryView(db, client=client)
    qtbot.addWidget(reopened)

    reopened.reconnect_running_jobs()

    client.submit_job.assert_not_called()
    assert list(reopened._live_jobs) == [key], (
        "a combine is kept under its settings folder, so after a restart it reconnects and lands "
        "in that folder exactly as a re-roll does")
    assert reopened._live_jobs[key].prompt_id == prompt_id


def test_combine_slot_predicates_gate_by_kind(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    assert view._combine._accepts_image("img") is True
    assert view._combine._accepts_image("vid") is False
    assert view._combine._accepts_video("vid") is True
    assert view._combine._accepts_video("img") is False


def test_combine_generate_button_launches_the_job(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view._combine.widget.image_zone.set_item("img")
    view._combine.widget.video_zone.set_item("vid")

    view._combine.widget._generate_btn.click()

    assert len(view._live_jobs) == 1
    job = next(iter(view._live_jobs.values()))
    assert job.params["input_image"] == "sdxl_pick.png [output]"
    assert job.params["noise_seed"] != 99


def _combine_view(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    return view


def _pick_action(tab, action):
    index = tab._category.findText(action)
    tab._category.setCurrentIndex(index if index >= 1 else 0)


def _pick_lane(tab, intent):
    radio = (tab._genau_radio if intent == action_settings.GENAU
             else tab._video_radio)
    radio.setChecked(True)


def test_combine_selection_reports_the_slotted_ids(qtbot, tmp_path):
    view = _combine_view(qtbot, tmp_path)
    view._combine.widget.image_zone.set_item("img")
    view._combine.widget.video_zone.set_item("vid")

    assert view.combine_selection() == {
        "image": "img", "videos": {action_settings.VIDEO: "vid"},
        "intent": action_settings.VIDEO, "category": "", "checked": [],
    }


def test_combine_selection_carries_the_lane_and_the_action(qtbot, tmp_path):
    view = _combine_view(qtbot, tmp_path)
    view._combine.widget.image_zone.set_item("img")
    _pick_lane(view._combine.widget, action_settings.GENAU)
    _pick_action(view._combine.widget, "beta")

    assert view.combine_selection() == {
        "image": "img", "videos": {},
        "intent": action_settings.GENAU, "category": "beta", "checked": [],
    }


def test_restore_combine_selection_refills_the_slots(qtbot, tmp_path):
    view = _combine_view(qtbot, tmp_path)

    view.restore_combine_selection({"image": "img", "video": "vid"})

    assert view._combine.widget.image_zone.current_id() == "img"
    assert view._combine.widget.video_zone.current_id() == "vid"


def test_a_restored_session_brings_back_the_video_each_lane_last_had(qtbot, tmp_path):
    first = _combine_view(qtbot, tmp_path)
    _looping_video(first._db)
    first._combine.widget.video_zone.set_item("vid")
    _pick_lane(first._combine.widget, action_settings.GENAU)
    first._combine.widget.video_zone.set_item("loop")
    saved = first.combine_selection()

    restored = GalleryView(first._db, client=_reroll_client())
    qtbot.addWidget(restored)
    restored.refresh()
    restored.restore_combine_selection(saved)

    assert restored._combine.widget.video_zone.current_id() == "loop"
    _pick_lane(restored._combine.widget, action_settings.VIDEO)
    assert restored._combine.widget.video_zone.current_id() == "vid"


def test_restore_combine_selection_puts_the_lane_and_action_back(qtbot, tmp_path):
    view = _combine_view(qtbot, tmp_path)

    view.restore_combine_selection(
        {"image": "img", "intent": action_settings.GENAU, "category": "beta"})

    assert view._combine.widget.selected_intent() == action_settings.GENAU
    assert view._combine.widget.selected_category() == "beta"
    assert view._combine.widget._generate_btn.isEnabled()


def test_restore_reads_the_video_lane_under_the_name_older_sessions_saved(qtbot, tmp_path):
    view = _combine_view(qtbot, tmp_path)
    _pick_lane(view._combine.widget, action_settings.GENAU)

    view.restore_combine_selection({"image": "img", "intent": "players"})

    assert view._combine.widget.selected_intent() == action_settings.VIDEO


def test_restore_drops_an_action_the_saved_lane_cannot_answer(qtbot, tmp_path):
    view = _combine_view(qtbot, tmp_path)

    view.restore_combine_selection(
        {"image": "img", "intent": action_settings.GENAU, "category": "alpha + beta"})

    assert view._combine.widget.selected_intent() == action_settings.GENAU
    assert view._combine.widget.selected_category() == ""


def test_restore_combine_selection_reads_the_two_item_list_older_sessions_wrote(
        qtbot, tmp_path):
    view = _combine_view(qtbot, tmp_path)

    view.restore_combine_selection(["img", "vid"])

    assert view._combine.widget.image_zone.current_id() == "img"
    assert view._combine.widget.video_zone.current_id() == "vid"


def test_restore_combine_selection_skips_gone_or_mismatched_items(qtbot, tmp_path):
    view = _combine_view(qtbot, tmp_path)

    view.restore_combine_selection({"image": "ghost", "video": "img"})

    assert view._combine.widget.image_zone.current_id() is None
    assert view._combine.widget.video_zone.current_id() is None


def test_restore_combine_selection_tolerates_a_missing_payload(qtbot, tmp_path):
    view = _combine_view(qtbot, tmp_path)

    view.restore_combine_selection(None)
    view.restore_combine_selection(["only-one"])

    assert view.combine_selection() == {
        "image": None, "videos": {},
        "intent": action_settings.VIDEO, "category": "", "checked": [],
    }


def _lit_while_dragging(monkeypatch, drag_out, mime, zones) -> dict:
    lit = {}

    def drag_loop(_drag, _action):
        lit.update({name: zone._label.property("dragActive") for name, zone in zones.items()})

    monkeypatch.setattr(QDrag, "exec", drag_loop)
    drag_out.start(mime, QPixmap())
    return lit


def test_dragging_a_gallery_pane_thumbnail_lights_its_combine_slot(qtbot, tmp_path, monkeypatch):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    tw = ItemTile("vid", None, "v")
    qtbot.addWidget(tw)
    combine = view._combine.widget
    mime = generation_mime("vid")

    lit = _lit_while_dragging(monkeypatch, tw.drag_out, mime,
                              {"video": combine.video_zone, "image": combine.image_zone})

    assert lit == {"video": True, "image": False}
    assert combine.video_zone._label.property("dragActive") is False


def test_a_video_dragged_from_an_image_the_gallery_holds_lights_the_image_slot_too(
        qtbot, tmp_path):
    db = _combine_db(tmp_path)
    params = json.loads(db.get_generation("vid")["params_json"])
    db.set_params_json("vid", json.dumps(dict(params, input_image="sdxl_pick.png [output]")))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    mime = generation_mime("vid")

    under_way.started.emit(mime, None)

    assert view._combine.widget.image_zone._label.property("dragActive") is True
    assert view._combine.widget.video_zone._label.property("dragActive") is True
    under_way.ended.emit()


def test_combines_generate_grays_while_the_pair_dropped_in_it_is_being_made(qtbot, tmp_path):
    view = _combine_view(qtbot, tmp_path)
    combine = view._combine.widget
    combine.image_zone.set_item("img")
    combine.video_zone.set_item("vid")
    assert combine._generate_btn.isEnabled()

    view._combine._generate_combination("img", "vid")

    assert not combine._generate_btn.isEnabled()


def test_dragging_the_generate_preview_lights_its_combine_slot(qtbot, tmp_path, monkeypatch):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    preview = view._generate_pane.current_generate_tab()._viewport
    combine = view._combine.widget
    mime = generation_mime("vid")

    lit = _lit_while_dragging(monkeypatch, preview.drag_out, mime,
                              {"video": combine.video_zone, "image": combine.image_zone})

    assert lit == {"video": True, "image": False}
    assert combine.video_zone._label.property("dragActive") is False


def test_a_thumbnail_redrawn_away_mid_drag_still_puts_its_combine_slot_out(
        qtbot, tmp_path, monkeypatch):
    view = _combine_view(qtbot, tmp_path)
    view._tree.setCurrentItem(_collection(view, LATEST_KEY))
    tile = view._gallery_pane._thumb_widgets["vid"]
    zone = view._combine.widget.video_zone._label
    in_flight = {}

    def drag_loop_through_a_grid_redraw(drag, _action):
        view._db.update_generation("vid", thumbnail_path="moved.jpg")
        view.refresh()
        in_flight["zone lit"] = zone.property("dragActive")
        in_flight["drag alive"] = not sip.isdeleted(drag)

    monkeypatch.setattr(QDrag, "exec", drag_loop_through_a_grid_redraw)

    qtbot.mousePress(tile, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
    qtbot.mouseMove(tile, QPoint(120, 120))
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton)

    assert sip.isdeleted(tile)
    assert in_flight == {"zone lit": True, "drag alive": True}
    assert zone.property("dragActive") is False


def test_a_job_launched_as_an_action_is_made_from_no_video_though_one_gave_its_settings(qtbot, tmp_path):
    db = _combine_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view._combine._generate_combination("img", "vid")
    (job,) = view._jobs.all_jobs
    assert view._job_made_from(job, lambda video: video["prompt_id"]).source_video == "vid"

    db.set_settings_source(job.prompt_id, category="alpha", video_prompt_id="vid")

    assert view._job_made_from(job, lambda video: video["prompt_id"]).source_video is None
