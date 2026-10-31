from __future__ import annotations

import json

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
    act_settings,
    gallery,
)
from origenerator.db import Database
from origenerator.gallery.collection import (
    RECENTS_KEY,
)
from origenerator.gui import (
    combine_controller,
)
from origenerator.gui import gallery_view as gallery_view_module
from origenerator.gui import generate_config_panel as gcp_module
from origenerator.gui import generating_tile as generating_tile_module
from origenerator.gui.combine_panel import CombineRequest
from origenerator.gui.drags import under_way
from origenerator.gui.gallery_view import _GROUP_ROLE, GalleryView
from origenerator.gui.generation_drag import generation_mime
from origenerator.gui.thumbnail_widget import ThumbnailWidget
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
from tests.test_combine_panel import _listed_under_recent

pytestmark = pytest.mark.usefixtures("_stub_preview_resolution")


# --- combine: a video's settings applied to a dropped image -----------------


def _looping_video(db, prompt_id="loop"):
    """A past looping clip for the Genau lane to mine, sampled the long way --
    21 frames at 16fps, which is a cycle and a half and the whole problem."""
    wf = WORKFLOW_REGISTRY["wan22_flf2v_loop"]
    db.insert_generation(
        prompt_id=prompt_id, workflow_name=wf.name, workflow_version=wf.version,
        positive_prompt="alpha", seed=8,
        params_json=json.dumps(dict(wf.default_params(), seed=8,
                                    positive_prompt="alpha")),
        workflow_json="{}")
    db.update_generation(prompt_id, status="completed", output_files=json.dumps(
        [{"filename": "flf2v_loop_01.mp4", "subfolder": "video"}]))
    return wf


def test_the_genau_lane_asks_for_settings_one_cycle_long(qtbot, tmp_path):
    """The lane used to choose only WHICH past clip was mined, and from there a
    Genau flick was made exactly like any other video. It cannot be: what Genau
    needs of a clip is a property of its LENGTH, and the clip being mined was
    made before anyone knew that."""
    db = _combine_db(tmp_path)
    wf = _looping_video(db)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._generate_combination("img", "loop", intent=act_settings.GENAU)

    job = next(iter(view._live_jobs.values()))
    assert job.params["frame_count"] == gallery.CYCLE_FRAMES   # the length that closes
    assert job.params["frame_rate"] > wf.default_params()["frame_rate"]  # smoothed
    assert job.params["positive_prompt"] != "alpha"             # asked for one cycle


def test_the_act_chooses_which_cycle_words_the_lane_adds(qtbot, tmp_path):
    """A cycle is not one motion, so the wording is per act — and the act has to
    reach the shaping, which is the whole reason it is threaded through."""
    db = _combine_db(tmp_path)
    _looping_video(db)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    asked = []
    real = gallery.cycle_shaped
    view._db  # noqa: B018  (the view is built; patch after)

    def spy(params, workflow, category=""):
        asked.append(category)
        return real(params, workflow, category)

    gallery_view_module.gallery.cycle_shaped = spy
    try:
        view._combine._generate_combination("img", "loop", intent=act_settings.GENAU,
                                            category="beta")
    finally:
        gallery_view_module.gallery.cycle_shaped = real

    assert asked == ["beta"]


def test_the_video_lane_takes_the_mined_settings_as_they_stand(qtbot, tmp_path):
    # A clip for a Funestra is watched at its own rate and wants the settings that
    # made the one it was mined from.
    db = _combine_db(tmp_path)
    wf = _looping_video(db)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._generate_combination("img", "loop")

    job = next(iter(view._live_jobs.values()))
    assert job.params["frame_count"] == wf.default_params()["frame_count"]
    assert job.params["frame_rate"] == wf.default_params()["frame_rate"]
    assert job.params["positive_prompt"] == "alpha"


def test_combine_submits_the_settings_on_the_dropped_image_with_a_fresh_seed(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._generate_combination("img", "vid")

    assert len(view._live_jobs) == 1
    job = next(iter(view._live_jobs.values()))
    assert job.workflow.name == "wan22_i2v"
    assert job.params["input_image"] == "sdxl_pick.png [output]"  # the dropped image
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
    view._jobs.start_now()  # the minute videos wait after an image, here the enhancement

    first, then = [call.args for call in view._client.submit_job.call_args_list]
    assert first[1] == enhance.prompt_id
    assert "image/image_enhance_00001_.png [output]" in json.dumps(then[0])
    assert gallery.row_output_files(db.get_generation("img"))[0]["filename"] \
        == "image_enhance_00001_.png"


def test_open_combination_prefills_a_generate_tab_without_launching(qtbot, tmp_path):
    # "Edit individual…" builds the same combination Generate would, but hands it to
    # an editable tab to tweak first — so no job runs and the form is prefilled.
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._open_combination("img", "vid")

    assert view._live_jobs == {}                 # opened for editing, not launched
    view._client.submit_job.assert_not_called()
    config = view._info_tabs.current_config_panel().current_config()
    assert config.workflow_name == "wan22_i2v"
    assert config.params["input_image"] == "sdxl_pick.png [output]"  # the dropped image
    assert config.seed_is_random                                     # a new take of the motion


def test_the_tab_edit_individual_opens_lists_only_the_video_workflows(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._open_combination("img", "vid")

    combo = view._info_tabs.current_config_panel()._workflow_combo
    assert [combo.itemData(i) for i in range(combo.count())] == [
        workflow.name for workflow in offered_workflows(makes=MediaType.VIDEO)]


def test_open_combination_takes_over_the_blank_tab_and_marks_it_italic(qtbot, tmp_path):
    # "Edit individual…" is the same "show me this" gesture a thumbnail click is:
    # it lands in the pane's untouched "New generation" tab rather than beside it,
    # and wears the slant that says the next open may replace it.
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    tabs = view._info_tabs
    before = tabs.count()

    view._combine._open_combination("img", "vid")

    assert tabs.count() == before  # no "New generation" left standing beside it
    panel = tabs.current_config_panel()
    assert tabs.tabBar()._preview_index == tabs.indexOf(panel)


def test_edit_individual_in_the_genau_lane_opens_the_looping_workflow_as_it_starts(
        qtbot, tmp_path, monkeypatch):
    # A past looping video of the act is there, and its settings are not what opens;
    # nor is the one-cycle cut the lane gives the settings it runs.
    db = _combine_db(tmp_path)
    looping = _looping_video(db)
    db.set_settings_source("loop", category="alpha")
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    shown = []
    monkeypatch.setattr(gallery_view_module.QMessageBox, "information",
                        lambda *a, **k: shown.append(a[1:]))

    view._combine._open_category("img", "alpha", act_settings.GENAU)

    assert view._live_jobs == {}
    view._client.submit_job.assert_not_called()
    assert shown == []
    config = view._info_tabs.current_config_panel().current_config()
    assert WORKFLOW_REGISTRY[config.workflow_name].display_name == (
        "WAN 2.2 I2V (Looping)")
    assert config.params["input_image"] == "sdxl_pick.png [output]"
    assert (config.params["positive_prompt"], config.params["negative_prompt"]) == ("", "")
    assert config.params["frame_count"] == looping.default_params()["frame_count"]
    assert config.seed_is_random


def test_combine_open_buttons_are_wired_to_the_view(qtbot, tmp_path):
    # An "Edit individual…" press reaches the view's open handler, so clicking it with a
    # dropped video (or a picked act) opens an editable tab.
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine.panel.combine_requested.emit(CombineRequest(
        image_id="img", video_id="vid", edit_first=True))

    assert view._live_jobs == {}
    config = view._info_tabs.current_config_panel().current_config()
    assert config.workflow_name == "wan22_i2v"
    assert config.params["input_image"] == "sdxl_pick.png [output]"


def _insert_completed_video(db, prompt_id, params, filename):
    db.insert_generation(
        prompt_id=prompt_id, workflow_name="wan22_i2v", workflow_version=_WAN_I2V.version,
        positive_prompt=params.get("positive_prompt", ""), negative_prompt="",
        seed=params.get("seed"), params_json=json.dumps(params), workflow_json="{}",
    )
    db.update_generation(prompt_id, status="completed",
                         output_files=json.dumps([{"filename": filename, "subfolder": ""}]))


def test_the_combine_panel_is_up_under_the_folders_when_comfyui_can_be_reached(qtbot, tmp_path):
    view = GalleryView(Database(tmp_path / "test.db"), client=_reroll_client())
    qtbot.addWidget(view)
    view.show()

    assert view._combine.panel.isVisible()


def test_without_comfyui_the_combine_panel_takes_its_section_with_it(qtbot, tmp_path):
    view = GalleryView(Database(tmp_path / "test.db"))
    qtbot.addWidget(view)
    view.show()

    assert not view._combine.panel.parentWidget().isVisible()


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
    db.insert_generation(prompt_id="vx", workflow_name="mystery", workflow_version="v",
                         positive_prompt="", seed=1, params_json=json.dumps({"seed": 1}),
                         workflow_json="{}")
    db.update_generation("vx", status="completed",
                         output_files=json.dumps([{"filename": "mystery_vx.mp4", "subfolder": ""}]))
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._generate_combination("img", "vx")  # can't rebuild "mystery"

    assert view._live_jobs == {}
    view._client.submit_job.assert_not_called()


def test_combine_noop_when_the_image_has_no_output_file(qtbot, tmp_path):
    db = _combine_db(tmp_path)
    db.update_generation("img", output_files=json.dumps([]))  # file pruned since it was dropped
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._generate_combination("img", "vid")

    assert view._live_jobs == {}


def test_category_runs_the_acts_most_used_video(qtbot, tmp_path):
    # The combine DB's one "dance" clip is the "dancing" act's most-used video.
    db = _combine_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine.generate_category("img", "dancing")

    job = next(iter(view._live_jobs.values()))
    assert job.workflow.name == "wan22_i2v"
    assert job.params["input_image"] == "sdxl_pick.png [output]"


def test_refresh_greys_out_the_acts_with_no_video_to_mine(qtbot, tmp_path):
    db = _combine_db(tmp_path)  # its one video is a "dance" clip
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)

    view.refresh()

    combo = view._combine.panel._category
    enabled = {combo.itemText(i) for i in range(1, combo.count())
               if combo.model().item(i).isEnabled()}
    # "dancing" has a video to mine; "gamma" needs none — the example overlay
    # pins settings for it.
    assert enabled == {"dancing", "gamma"}


def test_category_prefers_the_overlays_pinned_settings_over_mining(qtbot, tmp_path, monkeypatch):
    # "gamma" is curated in the example overlay, so the launch takes its pinned
    # workflow+params — mining is never consulted, and the gallery needs no past
    # gamma video at all.
    db = _combine_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(combine_controller.act_settings, "most_used_video",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("curated act must not mine")))

    view._combine.generate_category("img", "gamma")

    job = next(iter(view._live_jobs.values()))
    assert job.workflow.name == "wan22_i2v"
    assert job.params["input_image"] == "sdxl_pick.png [output]"     # run on the dropped image
    assert job.params["lora_high"] == "example-act-high.safetensors"  # the curated spec's pin
    assert job.params["steps"] == 24


# --- what a combine's run records about where its settings came from --------


def _launched_row(view):
    """The DB row of the one run the view just launched."""
    job = next(iter(view._live_jobs.values()))
    return view._db.get_generation(job.prompt_id)


def test_settings_from_a_dropped_video_name_that_video(qtbot, tmp_path):
    # Nothing in the params says which video the settings were lifted off, and
    # the queue row draws that clip in gray beside the frame being animated.
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._generate_combination("img", "vid")

    row = _launched_row(view)
    assert row["source_video"] == "vid"
    assert row["act"] is None  # a dropped video is no dropdown choice


def test_recent_already_lists_a_video_generated_from_before_this_session(qtbot, tmp_path):
    # Nothing noted which lane those were for, so both lanes list them.
    db = _combine_db(tmp_path)
    db.insert_generation(prompt_id="made", workflow_name="wan22_i2v",
                         workflow_version=_WAN_I2V.version, params_json="{}", workflow_json="{}")
    db.set_settings_source("made", video_prompt_id="vid")
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    panel = view._combine.panel

    assert _listed_under_recent(panel) == ["vid"]
    panel.set_intent(act_settings.GENAU)
    assert _listed_under_recent(panel) == ["vid"]


def test_a_picked_act_is_recorded_with_the_video_it_resolved_to(qtbot, tmp_path, monkeypatch):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine.generate_category("img", "dancing")

    row = _launched_row(view)
    assert row["act"] == "dancing"
    assert row["source_video"] == "vid"


def test_a_curated_act_records_the_act_with_no_video_behind_it(qtbot, tmp_path):
    # "gamma" is pinned in the example overlay: there is no past run for the
    # queue row to show, and the act is the whole of what was chosen.
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine.generate_category("img", "gamma")

    row = _launched_row(view)
    assert row["act"] == "gamma"
    assert row["source_video"] is None


def test_open_in_generator_marks_the_tab_with_where_the_settings_came_from(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._open_combination("img", "vid")

    assert _front_panel(view).settings_source() == ("", "vid", act_settings.VIDEO)


def test_a_generate_from_an_opened_combination_still_names_its_video(qtbot, tmp_path):
    # The whole point of the mark riding through the tab: a combination edited
    # before launching still runs that video's settings, and the queue row is where
    # it is read.
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view._combine._open_combination("img", "vid")
    panel = _front_panel(view)
    panel._param_form.set_values({"positive_prompt": "edited before running"})

    panel._on_generate()

    assert _launched_row(view)["source_video"] == "vid"


def test_a_generate_from_an_opened_dropped_video_notes_the_lane_it_was_opened_under(
        qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view._combine._open_combination("img", "vid", intent=act_settings.GENAU)

    _front_panel(view)._on_generate()

    noted = [(use["intent"], use["video_prompt_id"], use["generation_prompt_id"])
             for use in view._db.list_combine_video_uses()]
    assert noted == [(act_settings.GENAU, "vid", _launched_row(view)["prompt_id"])]


def test_a_tab_pointed_at_another_generation_drops_the_settings_source(qtbot, tmp_path):
    # The tab is about that row now; a launch from it is not the combination's.
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view._combine._open_combination("img", "vid")
    panel = _front_panel(view)

    panel.show_saved_generation(view._db.get_generation("vid"), view._image_rows)

    assert panel.settings_source() == ("", None, "")


def test_a_tab_switched_to_another_workflow_drops_the_settings_source(qtbot, tmp_path):
    # A different workflow is different settings, so the mark must not ride onto
    # a launch that has nothing to do with the combination.
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view._combine._open_combination("img", "vid")
    panel = _front_panel(view)

    panel.prefill("sdxl_t2i", _SDXL.default_params())

    assert panel.settings_source() == ("", None, "")


def test_open_in_generator_shows_the_pair_rather_than_an_empty_pane(qtbot, tmp_path):
    # Nothing has been made from the combination yet, so the pane used to say
    # "select a generation to preview" — over a tab that is about two specific
    # things, both of them on hand to be shown.
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._open_combination("img", "vid")

    preview = _front_panel(view)._preview
    assert preview._stack.currentWidget() is preview._combination


def test_open_in_generator_links_to_the_image_and_the_video_before_generating(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._open_combination("img", "vid")

    related = _front_panel(view)._related
    assert not related._source_tile.isHidden()
    assert related._source_tile._prompt_id == "img"
    assert not related._source_video_tile.isHidden()
    assert related._source_video_tile._prompt_id == "vid"


def test_the_video_an_opened_combination_makes_keeps_both_links(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_combine_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    view._combine._open_combination("img", "vid")
    panel = _front_panel(view)
    panel._on_generate()
    job = next(iter(view._live_jobs.values()))

    client.job_completed.emit(job.prompt_id, _VID_REROLL_HISTORY)

    assert panel.displayed_row()["prompt_id"] == job.prompt_id
    assert panel._related._source_tile._prompt_id == "img"
    assert panel._related._source_video_tile._prompt_id == "vid"
    assert not panel._related._source_video_tile.isHidden()


def test_an_act_whose_settings_came_from_no_video_links_to_the_image_alone(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._open_category("img", "gamma")

    related = _front_panel(view)._related
    assert related._source_tile._prompt_id == "img"
    assert related._source_video_tile.isHidden()


def _combine_view_with_a_looping_video(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    clip = str(_write_looping_webp(tmp_path / "vid_anim.webp"))
    view.animated_preview = lambda row: clip
    return view


def _opened_combination(qtbot, tmp_path, intent=act_settings.VIDEO):
    view = _combine_view_with_a_looping_video(qtbot, tmp_path)
    view._combine._open_combination("img", "vid", intent=intent)
    return view, _front_panel(view)


def test_a_combination_opened_for_genau_has_its_source_video_in_parentheses_before_any_edit(
        qtbot, tmp_path):
    _view, panel = _opened_combination(qtbot, tmp_path, intent=act_settings.GENAU)

    assert not panel._preview._combination.open_paren_label.isHidden()


@pytest.mark.parametrize(("key", "as_made", "edited"), [
    ("positive_prompt", "dance", "dance in the rain"),
    ("negative_prompt", "", "blurry"),
])
def test_the_clip_of_an_opened_combination_stands_in_parentheses_while_its_prompt_differs(
        qtbot, tmp_path, key, as_made, edited):
    _view, panel = _opened_combination(qtbot, tmp_path)
    parens = panel._preview._combination.open_paren_label
    assert parens.isHidden()

    panel._param_form.set_values({key: edited})
    assert not parens.isHidden()

    panel._param_form.set_values({key: as_made})
    assert parens.isHidden()


def test_a_run_from_an_edited_combination_keeps_its_source_video_in_parentheses_while_it_waits(
        qtbot, tmp_path, monkeypatch):
    drawn = []
    monkeypatch.setattr(generating_tile_module, "combination_pixmap",
                        lambda made_from, size: drawn.append(made_from))
    view, panel = _opened_combination(qtbot, tmp_path)
    panel._param_form.set_values({"positive_prompt": "dance in the rain"})

    panel._on_generate()

    assert drawn[-1].prompt_edited
    assert panel._live_source.prompt_edited


def test_a_genau_run_straight_from_the_combine_panel_waits_with_its_source_video_in_parentheses(
        qtbot, tmp_path):
    view = _combine_view_with_a_looping_video(qtbot, tmp_path)

    view._combine._generate_combination("img", "vid", intent=act_settings.GENAU)
    view._select_reroll(next(iter(view._live_jobs)))  # its card in the collection, clicked

    assert _front_panel(view)._live_source.prompt_edited


@pytest.mark.parametrize(("lane", "stands_apart"), [(act_settings.VIDEO, False),
                                                    (act_settings.GENAU, True)])
def test_a_pressed_combine_stands_in_line_with_its_source_video_marked_as_its_run_will_be(
        qtbot, tmp_path, monkeypatch, lane, stands_apart):
    view = _combine_view(qtbot, tmp_path)
    monkeypatch.setattr(view._combine, "_after_painting", lambda work: None)
    _pick_lane(view._combine.panel, lane)

    view._combine.panel.combine_requested.emit(
        CombineRequest(image_id="img", video_id="vid",
                       intent=view._combine.panel.selected_intent()))

    (standing,) = view._starting.rows()
    assert standing.prompt_edited is stands_apart


def test_changing_a_setting_other_than_the_prompt_leaves_the_clip_out_of_parentheses(
        qtbot, tmp_path):
    _view, panel = _opened_combination(qtbot, tmp_path)

    panel._param_form.set_values({"seed": 7})

    assert panel._preview._combination.open_paren_label.isHidden()


@pytest.mark.parametrize(("slot_name", "prompt_id"), [("image_slot", "img"),
                                                      ("video_slot", "vid")])
def test_clicking_a_combine_slot_goes_to_what_it_holds(qtbot, tmp_path, slot_name, prompt_id):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    slot = getattr(view._combine.panel, slot_name)
    slot.set_item(prompt_id)

    qtbot.mouseClick(slot, Qt.MouseButton.LeftButton)

    assert view.selected_prompt_ids() == [prompt_id]
    assert slot.current_id() == prompt_id


def test_combines_drop_zones_name_what_was_dropped_on_them(qtbot, tmp_path):
    view = _combine_view(qtbot, tmp_path)
    panel = view._combine.panel

    drops.let_go_over(panel.image_slot, "img")
    drops.let_go_over(panel.video_slot, "vid")

    named = (panel.image_slot._caption.text(), panel.video_slot._caption.text())
    assert named == (view._item_names.of("img"), view._item_names.of("vid"))
    assert "" not in named


def test_what_a_launch_puts_back_in_combine_is_named_once_the_gallery_draws(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.restore_combine_selection({"image": "img", "videos": {act_settings.VIDEO: "vid"}})

    view.refresh()

    panel = view._combine.panel
    named = (panel.image_slot._caption.text(), panel.video_slot._caption.text())
    assert named == (view._item_names.of("img"), view._item_names.of("vid"))
    assert "" not in named


def test_a_start_image_a_launch_puts_back_is_named_once_the_gallery_draws(qtbot, tmp_path,
                                                                          monkeypatch):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    Image.new("RGB", (8, 8)).save(output_dir / "sdxl_pick.png")
    monkeypatch.setattr(gcp_module, "OUTPUT_PLACES", OutputPlaces.in_one_folder(output_dir))
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    panel = view._info_tabs.current_config_panel()
    panel._workflow_combo.setCurrentIndex(panel._workflow_combo.findData("wan22_i2v"))
    start = panel._param_form._widgets["input_image"]
    panel._param_form.set_values({"input_image": "sdxl_pick.png [output]"})

    view.refresh()

    assert start._caption.text() == view._item_names.of("img") != ""


def test_an_image_browsed_into_combine_offers_no_way_into_the_gallery(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view.follow_link("img")
    slot = view._combine.panel.image_slot
    slot.set_item(str(tmp_path / "scene one.png"))

    qtbot.mouseClick(slot, Qt.MouseButton.LeftButton)

    assert slot.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert view.selected_prompt_ids() == ["img"]


def test_open_category_prefers_the_pinned_settings_too(qtbot, tmp_path, monkeypatch):
    db = _combine_db(tmp_path)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    monkeypatch.setattr(combine_controller.act_settings, "most_used_video",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("curated act must not mine")))
    opened = []
    monkeypatch.setattr(view._info_tabs, "open_config",
                        lambda name, params: opened.append((name, params)))

    view._combine._open_category("img", "gamma")

    (name, params), = opened
    assert name == "wan22_i2v"
    assert params["input_image"] == "sdxl_pick.png [output]"
    assert params["lora_high"] == "example-act-high.safetensors"


def test_category_noop_and_hints_when_the_act_has_no_video(qtbot, tmp_path, monkeypatch):
    db = _combine_db(tmp_path)  # its one video is a "dance" clip — no epsilon video exists
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    shown = []
    monkeypatch.setattr(gallery_view_module.QMessageBox, "information",
                        lambda *a, **k: shown.append(a))

    view._combine.generate_category("img", "epsilon")

    assert view._live_jobs == {}            # nothing to reuse: launch nothing
    view._client.submit_job.assert_not_called()
    assert shown                              # but tell the user why


def test_combine_new_folder_lands_on_recents_then_reveals_on_finish(qtbot, tmp_path):
    db = _combine_db(tmp_path)
    client = _reroll_client()
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()

    view._combine._generate_combination("img", "vid")

    assert view._browser.showing_recents()  # brand-new folder: watch it cook in the collection
    prompt_id = next(iter(view._live_jobs.values())).prompt_id

    client.job_completed.emit(prompt_id, _VID_REROLL_HISTORY)

    assert not view._browser.showing_recents()  # the finished row gave its folder a node
    new_row = db.get_generation(prompt_id)
    image_rows = [r for r in db.list_generations() if gallery.media_type_of_row(r) == "image"]
    expected = gallery.settings_folder_key(new_row, gallery.build_image_config_index(image_rows))
    assert _selected_folder(view) == expected


def test_combine_existing_folder_is_opened_with_the_live_tile(qtbot, tmp_path):
    db = _combine_db(tmp_path)
    # A sibling already made from this image with the video's settings (other seed)
    # gives the target (image × settings) folder a node before we combine.
    sib = dict(_WAN_I2V.default_params(), seed=7, noise_seed=7, positive_prompt="dance",
               input_image="sdxl_pick.png [output]")
    _insert_completed_video(db, "vsib", sib, "wan22_i2v_vsib.mp4")
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    view._combine._generate_combination("img", "vid")

    expected = view._leaf_by_id["vsib"].data(0, _GROUP_ROLE).key
    assert not view._browser.showing_recents()
    assert _selected_folder(view) == expected
    assert view._selected_reroll_key == expected  # watching the live combine tile


def test_combine_slot_predicates_gate_by_kind(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()

    assert view._combine._accepts_image("img") is True
    assert view._combine._accepts_image("vid") is False   # a video isn't a start frame
    assert view._combine._accepts_video("vid") is True
    assert view._combine._accepts_video("img") is False   # an image isn't an i2v video


def test_combine_panel_generate_button_launches_the_job(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view._combine.panel.image_slot.set_item("img")
    view._combine.panel.video_slot.set_item("vid")

    view._combine.panel._generate_btn.click()  # the panel's button, wired to the view

    assert len(view._live_jobs) == 1
    job = next(iter(view._live_jobs.values()))
    assert job.params["input_image"] == "sdxl_pick.png [output]"
    assert job.params["noise_seed"] != 99


def _combine_view(qtbot, tmp_path):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    return view


def _pick_act(panel, act):
    """Choose an act in the combine panel's dropdown, as a click on its row would."""
    index = panel._category.findText(act)
    panel._category.setCurrentIndex(index if index >= 1 else 0)


def _pick_lane(panel, intent):
    """Click the combine panel's lane radio; the group releases the other."""
    radio = (panel._genau_radio if intent == act_settings.GENAU
             else panel._video_radio)
    radio.setChecked(True)


def test_combine_selection_reports_the_slotted_ids(qtbot, tmp_path):
    view = _combine_view(qtbot, tmp_path)
    view._combine.panel.image_slot.set_item("img")
    view._combine.panel.video_slot.set_item("vid")

    assert view.combine_selection() == {
        "image": "img", "videos": {act_settings.VIDEO: "vid"},
        "intent": act_settings.VIDEO, "category": "",
    }


def test_combine_selection_carries_the_lane_and_the_act(qtbot, tmp_path):
    # All four are choices the user made, and none is recoverable from the
    # others: an act says nothing about which lane answers it.
    view = _combine_view(qtbot, tmp_path)
    view._combine.panel.image_slot.set_item("img")
    _pick_lane(view._combine.panel, act_settings.GENAU)
    _pick_act(view._combine.panel, "beta")

    assert view.combine_selection() == {
        "image": "img", "videos": {},
        "intent": act_settings.GENAU, "category": "beta",
    }


def test_restore_combine_selection_refills_the_slots(qtbot, tmp_path):
    view = _combine_view(qtbot, tmp_path)

    view.restore_combine_selection({"image": "img", "video": "vid"})

    assert view._combine.panel.image_slot.current_id() == "img"
    assert view._combine.panel.video_slot.current_id() == "vid"


def test_a_restored_session_brings_back_the_video_each_lane_last_had(qtbot, tmp_path):
    first = _combine_view(qtbot, tmp_path)
    _looping_video(first._db)
    first._combine.panel.video_slot.set_item("vid")
    _pick_lane(first._combine.panel, act_settings.GENAU)
    first._combine.panel.video_slot.set_item("loop")
    saved = first.combine_selection()

    restored = GalleryView(first._db, client=_reroll_client())
    qtbot.addWidget(restored)
    restored.refresh()
    restored.restore_combine_selection(saved)

    assert restored._combine.panel.video_slot.current_id() == "loop"
    _pick_lane(restored._combine.panel, act_settings.VIDEO)
    assert restored._combine.panel.video_slot.current_id() == "vid"


def test_restore_combine_selection_puts_the_lane_and_act_back(qtbot, tmp_path):
    view = _combine_view(qtbot, tmp_path)

    view.restore_combine_selection(
        {"image": "img", "intent": act_settings.GENAU, "category": "beta"})

    assert view._combine.panel.selected_intent() == act_settings.GENAU
    assert view._combine.panel.selected_category() == "beta"
    assert view._combine.panel._generate_btn.isEnabled()  # an image and settings: ready


def test_restore_reads_the_video_lane_under_the_name_older_sessions_saved(qtbot, tmp_path):
    view = _combine_view(qtbot, tmp_path)
    _pick_lane(view._combine.panel, act_settings.GENAU)

    view.restore_combine_selection({"image": "img", "intent": "players"})

    assert view._combine.panel.selected_intent() == act_settings.VIDEO


def test_restore_drops_an_act_the_saved_lane_cannot_answer(qtbot, tmp_path):
    # The lane decides which acts are answerable, and what could be answered when
    # the session closed may not be now — a video binned, or the lane itself
    # changed. A grayed act must not come back selected: the buttons would be
    # live on a pick that can only report "no past video yet".
    view = _combine_view(qtbot, tmp_path)

    view.restore_combine_selection(
        {"image": "img", "intent": act_settings.GENAU, "category": "dancing"})

    assert view._combine.panel.selected_intent() == act_settings.GENAU
    assert view._combine.panel.selected_category() == ""


def test_restore_combine_selection_reads_the_two_item_list_older_sessions_wrote(
        qtbot, tmp_path):
    view = _combine_view(qtbot, tmp_path)

    view.restore_combine_selection(["img", "vid"])

    assert view._combine.panel.image_slot.current_id() == "img"
    assert view._combine.panel.video_slot.current_id() == "vid"


def test_restore_combine_selection_skips_gone_or_mismatched_items(qtbot, tmp_path):
    view = _combine_view(qtbot, tmp_path)

    # image slot given a deleted id; video slot given an image (wrong kind)
    view.restore_combine_selection({"image": "ghost", "video": "img"})

    assert view._combine.panel.image_slot.current_id() is None   # "ghost" no longer exists
    assert view._combine.panel.video_slot.current_id() is None   # "img" isn't an i2v video


def test_restore_combine_selection_tolerates_a_missing_payload(qtbot, tmp_path):
    view = _combine_view(qtbot, tmp_path)

    view.restore_combine_selection(None)          # nothing saved yet
    view.restore_combine_selection(["only-one"])  # malformed

    assert view.combine_selection() == {
        "image": None, "videos": {},
        "intent": act_settings.VIDEO, "category": "",
    }


def _lit_while_dragging(monkeypatch, drag_out, mime, slots) -> dict:
    """Carry ``mime`` out through ``drag_out`` and say which of ``slots`` were lit
    while it was under way, before it reached any of them."""
    lit = {}

    def drag_loop(_drag, _action):
        lit.update({name: slot._label.property("dragActive") for name, slot in slots.items()})

    monkeypatch.setattr(QDrag, "exec", drag_loop)
    drag_out.start(mime, QPixmap())
    return lit


def test_dragging_a_browser_thumbnail_lights_its_combine_slot(qtbot, tmp_path, monkeypatch):
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    tw = ThumbnailWidget("vid", None, "v")  # a video tile, wired like a real one
    qtbot.addWidget(tw)
    panel = view._combine.panel
    mime = generation_mime("vid")

    lit = _lit_while_dragging(monkeypatch, tw.drag_out, mime,
                              {"video": panel.video_slot, "image": panel.image_slot})

    assert lit == {"video": True, "image": False}
    assert panel.video_slot._label.property("dragActive") is False  # put out at the end


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

    assert view._combine.panel.image_slot._label.property("dragActive") is True
    assert view._combine.panel.video_slot._label.property("dragActive") is True
    under_way.ended.emit()


def test_combines_generate_grays_while_the_pair_dropped_in_it_is_being_made(qtbot, tmp_path):
    view = _combine_view(qtbot, tmp_path)
    panel = view._combine.panel
    panel.image_slot.set_item("img")
    panel.video_slot.set_item("vid")
    assert panel._generate_btn.isEnabled()

    view._combine._generate_combination("img", "vid")

    assert not panel._generate_btn.isEnabled()


def test_dragging_the_generate_preview_lights_its_combine_slot(qtbot, tmp_path, monkeypatch):
    # The front generate tab's preview drags onto combine like a browser thumbnail.
    view = GalleryView(_combine_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    preview = view._info_tabs.current_config_panel()._preview
    combine = view._combine.panel
    mime = generation_mime("vid")

    lit = _lit_while_dragging(monkeypatch, preview.drag_out, mime,
                              {"video": combine.video_slot, "image": combine.image_slot})

    assert lit == {"video": True, "image": False}
    assert combine.video_slot._label.property("dragActive") is False


def test_a_thumbnail_redrawn_away_mid_drag_still_puts_its_combine_slot_out(
        qtbot, tmp_path, monkeypatch):
    view = _combine_view(qtbot, tmp_path)
    view._tree.setCurrentItem(_collection(view, RECENTS_KEY))
    tile = view._browser._thumb_widgets["vid"]
    slot = view._combine.panel.video_slot._label
    in_flight = {}

    def drag_loop_through_a_grid_redraw(drag, _action):
        # A redraw keeps a tile whose row still looks the same; this one's thumbnail
        # moves, so the redraw is the kind that takes the tile away under the drag.
        view._db.update_generation("vid", thumbnail_path="moved.jpg")
        view.refresh()
        in_flight["slot lit"] = slot.property("dragActive")
        in_flight["drag alive"] = not sip.isdeleted(drag)

    monkeypatch.setattr(QDrag, "exec", drag_loop_through_a_grid_redraw)

    qtbot.mousePress(tile, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
    qtbot.mouseMove(tile, QPoint(120, 120))
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton)

    assert sip.isdeleted(tile)
    assert in_flight == {"slot lit": True, "drag alive": True}
    assert slot.property("dragActive") is False
