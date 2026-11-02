from __future__ import annotations

import json

import pytest

from origenerator import gallery
from origenerator.db import Database
from origenerator.gallery.enhance import (
    displayed_versions,
    enhance_params_for,
    enhancement_versions,
    fix_params_for,
    remove_enhance_versions,
    version_matching_params,
    version_matching_settings,
)
from origenerator.gallery.enhance_fold import fold_enhancement
from origenerator.gallery.enhance_settings import (
    MATCH_SOURCE_MODEL,
    EnhanceSettings,
    default_enhance_params,
    describe_enhance_params,
    full_settings,
    version_settings,
)
from origenerator.output_places import OutputPlaces
from origenerator.workflows import detail_parts
from origenerator.workflows.detail_parts import DEFAULT_FIX_DENOISE


def _source_row(filename="sdxl_t2i_src.png", checkpoint="anemone_v3.safetensors"):
    return {
        "prompt_id": "src",
        "workflow_name": "sdxl_t2i",
        "params_json": json.dumps({
            "positive_prompt": "a lantern on a jetty",
            "negative_prompt": "blurry",
            "checkpoint": checkpoint,
        }),
        "output_files": json.dumps(
            [{"filename": filename, "subfolder": "image", "type": "output"}]
        ),
    }



def test_an_unconfigured_folder_reads_as_the_defaults_with_the_tick_off():
    settings = EnhanceSettings.parse(None)
    assert settings.auto is False
    assert settings.params == default_enhance_params()
    assert settings.params["checkpoint"] == MATCH_SOURCE_MODEL


@pytest.mark.parametrize("raw", ["", "not json", "[]", "null"])
def test_unreadable_stored_settings_fall_back_to_the_defaults(raw):
    assert EnhanceSettings.parse(raw) == EnhanceSettings.parse(None)


def test_settings_round_trip_through_json():
    settings = EnhanceSettings(auto=True, params={"enhance_scale": 3.0,
                                                  "enhance_steps": 30,
                                                  "enhance_denoise": 0.25})
    back = EnhanceSettings.parse(settings.to_json())
    assert back.auto is True
    assert back.params["enhance_scale"] == 3.0
    assert back.params["enhance_steps"] == 30
    assert back.params["enhance_denoise"] == 0.25
    assert back.params["upscale_model"] == default_enhance_params()["upscale_model"]


def test_stored_settings_cannot_smuggle_in_params_outside_the_panel():
    back = EnhanceSettings.parse(json.dumps(
        {"auto": True, "params": {"input_image": "elsewhere.png", "enhance_steps": 12}}
    ))
    assert "input_image" not in back.params
    assert back.params["enhance_steps"] == 12



def test_enhance_params_take_the_folders_settings_over_the_workflow_defaults():
    settings = EnhanceSettings(auto=False, params={
        "enhance_scale": 1.5, "enhance_steps": 35, "enhance_denoise": 0.4,
        "upscale_model": "some_other_upscaler.pt", "checkpoint": MATCH_SOURCE_MODEL,
    })
    params = enhance_params_for(_source_row(), settings)
    assert params["enhance_scale"] == 1.5
    assert params["enhance_steps"] == 35
    assert params["enhance_denoise"] == 0.4
    assert params["upscale_model"] == "some_other_upscaler.pt"
    assert params["input_image"] == "image/sdxl_t2i_src.png [output]"
    assert params["positive_prompt"] == "a lantern on a jetty"
    assert params["negative_prompt"] == "blurry"


def test_the_detail_pass_is_one_of_the_settings_the_panel_sets():
    settings = EnhanceSettings(params={"enhance_detail_fixes": {"teeth": 0.5}})
    params = enhance_params_for(_source_row(), settings)
    assert params["enhance_detail_fixes"] == {"teeth": 0.5}
    unset = enhance_params_for(_source_row(), EnhanceSettings())
    assert unset["enhance_detail_fixes"] == {}


def test_the_default_model_leaves_the_source_image_its_own_checkpoint():
    params = enhance_params_for(_source_row(), EnhanceSettings())
    assert params["checkpoint"] == "anemone_v3.safetensors"


def test_pinning_a_model_in_the_folder_overrides_the_sources_own():
    settings = EnhanceSettings(params={"checkpoint": "driftwood_v1.safetensors"})
    params = enhance_params_for(_source_row(), settings)
    assert params["checkpoint"] == "driftwood_v1.safetensors"


def test_no_settings_at_all_still_yields_the_workflow_defaults():
    params = enhance_params_for(_source_row())
    defaults = gallery.default_enhance_params()
    assert params["enhance_scale"] == defaults["enhance_scale"]
    assert params["enhance_steps"] == defaults["enhance_steps"]



def _enhance_row(prompt_id, filename, **settings):
    params = {"input_image": "image/sdxl_t2i_src.png [output]", **settings}
    return {
        "prompt_id": prompt_id,
        "workflow_name": "image_enhance",
        "params_json": json.dumps(params),
        "output_files": json.dumps(
            [{"filename": filename, "subfolder": "image", "type": "output"}]
        ),
    }


def _seed_source(db, filename="sdxl_t2i_src.png"):
    db.insert_generation(
        prompt_id="src", workflow_name="sdxl_t2i", workflow_version="v004",
        positive_prompt="a lantern on a jetty", seed=1,
        params_json=json.dumps({"positive_prompt": "a lantern on a jetty"}),
        workflow_json="{}",
    )
    db.update_generation("src", status="completed", output_files=json.dumps(
        [{"filename": filename, "subfolder": "image", "type": "output"}]))


def _add_and_fold(db, prompt_id, filename, **settings):
    db.insert_generation(
        prompt_id=prompt_id, workflow_name="image_enhance", workflow_version="v001",
        params_json=json.dumps({"input_image": "image/sdxl_t2i_src.png [output]", **settings}),
        workflow_json="{}",
    )
    db.update_generation(prompt_id, status="completed", output_files=json.dumps(
        [{"filename": filename, "subfolder": "image", "type": "output"}]))
    return fold_enhancement(db, db.get_generation(prompt_id))


def test_an_unenhanced_image_has_no_versions():
    assert enhancement_versions(_source_row()) == []


def test_an_inline_enhanced_image_lists_the_one_enhancement_it_received():
    row = dict(_source_row(), params_json=json.dumps({
        "positive_prompt": "a lantern on a jetty",
        "enhance": True, "enhance_scale": 2.0, "enhance_steps": 20,
        "enhance_denoise": 0.15,
    }))
    (version,) = enhancement_versions(row)
    assert version.label == "Enhancement 1/1"
    assert version.settings == "2x · 20 steps · 0.15 redraw"
    assert version.file["filename"] == "sdxl_t2i_src.png"


def test_a_batch_the_tail_finished_lists_one_version_not_one_per_file():
    row = dict(
        _source_row(),
        params_json=json.dumps({"enhance": True, "enhance_scale": 2.0}),
        output_files=json.dumps([
            {"filename": "sdxl_t2i_a.png", "subfolder": "image", "type": "output"},
            {"filename": "sdxl_t2i_b.png", "subfolder": "image", "type": "output"},
        ]),
    )
    assert [lvl.label for lvl in enhancement_versions(row)] == ["Enhancement 1/1"]


def test_a_batch_of_several_files_is_not_mistaken_for_versions():
    batch = dict(_source_row(), output_files=json.dumps([
        {"filename": "sdxl_t2i_a.png", "subfolder": "image", "type": "output"},
        {"filename": "sdxl_t2i_b.png", "subfolder": "image", "type": "output"},
    ]))
    assert enhancement_versions(batch) == []


def test_each_fold_adds_a_version_naming_the_settings_that_made_it(tmp_path):
    db = Database(tmp_path / "t.db")
    _seed_source(db)
    _add_and_fold(db, "e1", "image_enhance_00001_.png",
                  enhance_scale=2.0, enhance_steps=20, enhance_denoise=0.15)
    _add_and_fold(db, "e2", "image_enhance_00002_.png",
                  enhance_scale=3.0, enhance_steps=40, enhance_denoise=0.35)

    versions = enhancement_versions(db.get_generation("src"))
    assert [lvl.label for lvl in versions] == ["Enhancement 2/2", "Enhancement 1/2", "Original"]
    assert versions[0].file["filename"] == "image_enhance_00002_.png"
    assert versions[0].settings == "3x · 40 steps · 0.35 redraw"
    assert versions[1].settings == "2x · 20 steps · 0.15 redraw"
    assert versions[2].settings == ""
    assert versions[2].is_original


def test_each_enhancement_is_counted_out_of_the_enhancements_and_the_original_is_not(tmp_path):
    db = Database(tmp_path / "t.db")
    _seed_source(db)
    _add_and_fold(db, "e1", "image_enhance_00001_.png", enhance_scale=2.0)
    _add_and_fold(db, "e2", "image_enhance_00002_.png", enhance_scale=3.0)

    assert [lvl.label for lvl in enhancement_versions(db.get_generation("src"))] == [
        "Enhancement 2/2", "Enhancement 1/2", "Original"]


def test_a_version_folded_before_settings_were_recorded_still_lists(tmp_path):
    db = Database(tmp_path / "t.db")
    _seed_source(db)
    _add_and_fold(db, "e1", "image_enhance_00001_.png", enhance_scale=2.0)
    db.update_generation("src", enhance_history=None)

    versions = enhancement_versions(db.get_generation("src"))
    assert [lvl.label for lvl in versions] == ["Enhancement 1/1", "Original"]
    assert versions[0].settings == ""


def test_enhance_history_survives_capture_and_restore(tmp_path):
    db = Database(tmp_path / "t.db")
    _seed_source(db)
    _add_and_fold(db, "e1", "image_enhance_00001_.png", enhance_steps=25)
    row = db.get_generation("src")
    db.delete_generation("src")
    db.restore_generation(row)
    assert db.get_generation("src")["enhance_history"] == row["enhance_history"]


def test_a_version_recorded_before_a_setting_existed_still_reads_as_a_duplicate(tmp_path):
    db = Database(tmp_path / "t.db")
    _seed_source(db)
    _add_and_fold(db, "e1", "image_enhance_00001_.png",
                  enhance_scale=2.0, enhance_steps=20, enhance_denoise=0.15,
                  checkpoint="anemone_v3.safetensors")
    row = db.get_generation("src")
    settings = EnhanceSettings(params={
        "enhance_scale": 2.0, "enhance_steps": 20, "enhance_denoise": 0.15,
        "checkpoint": "anemone_v3.safetensors",
    })
    assert version_matching_settings(row, settings) == 0
    assert version_matching_settings(
        row, EnhanceSettings(params=dict(settings.params,
                                         enhance_detail_fixes={"faces": 0.45}))
    ) is None


def test_describe_names_each_part_the_pass_redrew_at_its_own_denoise():
    assert describe_enhance_params({
        "enhance_scale": 2.0, "enhance_steps": 20, "enhance_denoise": 0.15,
        "enhance_detail_fixes": {"faces": 0.45, "hands": 0.6},
    }) == "2x · 20 steps · 0.15 redraw · faces 0.45 & hands 0.6"
    assert describe_enhance_params({
        "enhance_scale": 2.0, "enhance_detail_fixes": {"faces": 0}}) == "2x"


def test_describe_names_a_pinned_model_by_its_title_but_not_the_source_matching_default(
        titled_models):
    titled_models({"driftwood_v1": "Driftwood v1"})
    assert describe_enhance_params({
        "enhance_scale": 2.0, "enhance_steps": 20, "enhance_denoise": 0.15,
        "checkpoint": MATCH_SOURCE_MODEL,
    }) == "2x · 20 steps · 0.15 redraw"
    assert describe_enhance_params({
        "enhance_scale": 2.0, "checkpoint": "driftwood_v1.safetensors",
    }) == "2x · Driftwood v1"
    assert describe_enhance_params({}) == ""



def test_an_unenhanced_image_still_lists_its_one_file_as_the_original():
    (version,) = displayed_versions(_source_row())
    assert version.is_original
    assert version.file["filename"] == "sdxl_t2i_src.png"


def test_a_video_lists_no_versions():
    video = dict(_source_row(), output_files=json.dumps(
        [{"filename": "wan_00001.mp4", "subfolder": "video", "type": "output"}]))
    assert displayed_versions(video) == []


def test_a_video_evolver_upscaled_lists_the_upscale_over_the_video_itself(tmp_path):
    upscale = tmp_path / "wan_00001_topaz.mp4"
    video = dict(_source_row(), output_files=json.dumps(
        [{"filename": "wan_00001.mp4", "subfolder": "video", "type": "output"}]))

    evolved, original = displayed_versions(video, upscale)

    assert (evolved.label, original.label) == ("Evolved", "Original")
    assert gallery.output_file_path(evolved.file, OutputPlaces.in_one_folder(tmp_path / "output")) == upscale
    assert original.file["filename"] == "wan_00001.mp4"
    assert evolved.params == {}


def _folded(tmp_path, count=1):
    db = Database(tmp_path / "t.db")
    _seed_source(db)
    for i in range(1, count + 1):
        _add_and_fold(db, f"e{i}", f"image_enhance_0000{i}_.png",
                      enhance_scale=float(i + 1))
    return db.get_generation("src")


def test_removing_an_enhancement_leaves_the_others(tmp_path):
    row = _folded(tmp_path, count=2)
    updates = remove_enhance_versions(row, ["image_enhance_00002_.png"])
    after = dict(row, **updates)
    assert [lvl.label for lvl in enhancement_versions(after)] == ["Enhancement 1/1", "Original"]
    older = json.loads(row["enhance_history"])[1]
    assert older["filename"] == "image_enhance_00001_.png"
    assert older["params"] == {"enhance_scale": 2.0}
    assert json.loads(after["enhance_history"]) == [older]


def test_removing_the_last_enhancement_leaves_a_plain_image(tmp_path):
    row = _folded(tmp_path, count=1)
    after = dict(row, **remove_enhance_versions(row, ["image_enhance_00001_.png"]))
    assert after["original_files"] is None
    assert after["enhance_history"] is None
    assert not gallery.is_enhanced_row(after)
    assert enhancement_versions(after) == []


def test_removing_the_original_keeps_every_enhancement_named(tmp_path):
    row = _folded(tmp_path, count=2)
    after = dict(row, **remove_enhance_versions(row, ["sdxl_t2i_src.png"]))
    versions = enhancement_versions(after)
    assert [lvl.label for lvl in versions] == ["Enhancement 2/2", "Enhancement 1/2"]
    assert versions[0].params == {"enhance_scale": 3.0}
    assert gallery.is_enhanced_row(after)


def test_removing_an_inline_tails_enhancement_untags_its_base_render():
    row = dict(
        _source_row(),
        params_json=json.dumps({"enhance": False}),
        output_files=json.dumps([
            {"filename": "enhanced.png", "subfolder": "image"},
            {"filename": "base.png", "subfolder": "image", "role": "original"},
        ]),
    )
    after = dict(row, **remove_enhance_versions(row, ["enhanced.png"]))
    assert json.loads(after["output_files"]) == [
        {"filename": "base.png", "subfolder": "image"}
    ]
    assert not gallery.is_enhanced_row(after)


def test_removing_every_version_changes_nothing(tmp_path):
    row = _folded(tmp_path, count=1)
    assert remove_enhance_versions(
        row, ["image_enhance_00001_.png", "sdxl_t2i_src.png"]) == {}


def test_removing_a_name_the_row_never_held_changes_nothing(tmp_path):
    assert remove_enhance_versions(_folded(tmp_path), ["someone_elses.png"]) == {}


def test_describe_still_names_a_version_recorded_the_old_way():
    assert describe_enhance_params({
        "enhance_scale": 2.0, "enhance_steps": 20, "enhance_denoise": 0.15,
        "enhance_detail_fix": True, "enhance_detail_denoise": 0.45,
        "enhance_face_detector": "teeth_yolov8n.pt", "enhance_hand_detector": "",
    }) == "2x · 20 steps · 0.15 redraw · teeth 0.45"
    assert describe_enhance_params({
        "enhance_detail_fix": True, "enhance_detail_denoise": 0.45,
        "enhance_face_detector": "face_yolov8m.pt",
        "enhance_hand_detector": "hand_yolov8s.pt",
    }) == "faces 0.45 & hands 0.45"



def _spoken(text):
    parts = detail_parts.match_fix_command(text)
    assert parts
    return parts


def _install_detectors(monkeypatch, *files):
    monkeypatch.setattr(detail_parts, "list_detector_files", lambda: list(files))


def test_a_spoken_fix_redoes_the_latest_enhancement_with_the_parts_pass(
        tmp_path, monkeypatch):
    _install_detectors(monkeypatch, "teeth_yolov8n.pt", "face_yolov8m.pt")
    db = Database(tmp_path / "t.db")
    _seed_source(db)
    _add_and_fold(db, "e1", "image_enhance_00001_.png",
                  enhance_scale=3.0, enhance_steps=40, enhance_denoise=0.35,
                  checkpoint="driftwood_v1.safetensors")
    row = db.get_generation("src")

    params = fix_params_for(row, _spoken("fix teeth"),
                            EnhanceSettings(params={"enhance_scale": 1.5}))

    assert params["enhance_scale"] == 3.0
    assert params["enhance_steps"] == 40
    assert params["checkpoint"] == "driftwood_v1.safetensors"
    assert params["input_image"] == "image/sdxl_t2i_src.png [output]"
    assert params["enhance_detail_fixes"] == {"teeth": DEFAULT_FIX_DENOISE}


def test_a_spoken_fix_on_an_unenhanced_image_runs_at_the_current_settings(monkeypatch):
    _install_detectors(monkeypatch, "hand_yolov8s.pt")
    params = fix_params_for(_source_row(), _spoken("fix hands"),
                            EnhanceSettings(params={"enhance_steps": 33}))
    assert params["enhance_steps"] == 33
    assert params["enhance_detail_fixes"] == {"hands": DEFAULT_FIX_DENOISE}


def test_a_spoken_fix_runs_the_part_asked_for_and_not_the_panels_other_ticks(
        monkeypatch):
    _install_detectors(monkeypatch, "teeth_yolov8n.pt", "face_yolov8m.pt",
                       "hand_yolov8s.pt", "eyes_yolov8n.pt")
    pane = EnhanceSettings(params={"enhance_detail_fixes": {
        "faces": 0.4, "hands": 0.5, "teeth": 0.6, "eyes": 0.3}})

    params = fix_params_for(_source_row(), _spoken("fix teeth"), pane)

    assert params["enhance_detail_fixes"] == {"teeth": 0.6}


def test_a_spoken_fix_can_ask_for_several_parts_at_once(monkeypatch):
    _install_detectors(monkeypatch, "hand_yolov8s.pt", "teeth_yolov8n.pt")

    params = fix_params_for(_source_row(), _spoken("fix hands and teeth"))

    assert params["enhance_detail_fixes"] == {
        "hands": DEFAULT_FIX_DENOISE, "teeth": DEFAULT_FIX_DENOISE}


def test_a_part_with_nothing_to_find_it_is_dropped_from_a_combination(monkeypatch):
    _install_detectors(monkeypatch, "hand_yolov8s.pt")

    params = fix_params_for(_source_row(), _spoken("fix hands and mouth"))

    assert params["enhance_detail_fixes"] == {"hands": DEFAULT_FIX_DENOISE}


def test_a_spoken_fix_runs_the_part_at_the_number_the_panel_gives_it(monkeypatch):
    _install_detectors(monkeypatch, "hand_yolov8s.pt")
    params = fix_params_for(
        _source_row(), _spoken("fix hands"),
        EnhanceSettings(params={"enhance_detail_fixes": {"hands": 0.7}}))
    assert params["enhance_detail_fixes"] == {"hands": 0.7}


def test_a_spoken_fix_with_no_detector_for_the_part_declines(monkeypatch):
    _install_detectors(monkeypatch, "face_yolov8m.pt", "hand_yolov8s.pt")
    assert fix_params_for(_source_row(), _spoken("fix teeth")) is None


def test_successive_spoken_fixes_accumulate_rather_than_trade_away(
        tmp_path, monkeypatch):
    _install_detectors(monkeypatch, "eyes_yolov8n.pt", "teeth_yolov8n.pt")
    db = Database(tmp_path / "t.db")
    _seed_source(db)
    _add_and_fold(db, "e1", "image_enhance_00001_.png",
                  enhance_detail_fixes={"teeth": 0.5})

    params = fix_params_for(db.get_generation("src"), _spoken("fix eyes"))

    assert params["enhance_detail_fixes"] == {
        "teeth": 0.5, "eyes": DEFAULT_FIX_DENOISE}


def test_a_spoken_fix_accumulates_onto_a_version_recorded_the_old_way(
        tmp_path, monkeypatch):
    _install_detectors(monkeypatch, "eyes_yolov8n.pt", "teeth_yolov8n.pt")
    db = Database(tmp_path / "t.db")
    _seed_source(db)
    _add_and_fold(db, "e1", "image_enhance_00001_.png",
                  enhance_detail_fix=True, enhance_detail_denoise=0.45,
                  enhance_face_detector="teeth_yolov8n.pt",
                  enhance_hand_detector="")

    params = fix_params_for(db.get_generation("src"), _spoken("fix eyes"))

    assert params["enhance_detail_fixes"] == {
        "teeth": 0.45, "eyes": DEFAULT_FIX_DENOISE}


def test_asking_again_for_a_part_already_fixed_fixes_it_harder(tmp_path, monkeypatch):
    _install_detectors(monkeypatch, "hand_yolov8s.pt")
    db = Database(tmp_path / "t.db")
    _seed_source(db)
    _add_and_fold(db, "e1", "image_enhance_00001_.png",
                  enhance_detail_fixes={"hands": 0.45})

    params = fix_params_for(db.get_generation("src"), _spoken("fix hands"))

    assert params["enhance_detail_fixes"] == {"hands": 0.55}


def test_a_part_fixed_as_hard_as_a_fix_goes_reads_as_the_duplicate_it_is(
        tmp_path, monkeypatch):
    _install_detectors(monkeypatch, "eyes_yolov8n.pt", "teeth_yolov8n.pt")
    db = Database(tmp_path / "t.db")
    _seed_source(db)
    first = fix_params_for(db.get_generation("src"), _spoken("fix teeth"))
    first["enhance_detail_fixes"] = {"teeth": 1.0}
    _add_and_fold(db, "e1", "image_enhance_00001_.png",
                  **{k: first[k] for k in gallery.ENHANCE_SETTING_KEYS})
    row = db.get_generation("src")

    assert version_matching_params(row, fix_params_for(row, _spoken("fix teeth"))) == 0
    assert version_matching_params(row, fix_params_for(row, _spoken("fix eyes"))) is None


def test_the_prompts_a_fix_ran_with_are_part_of_what_its_version_is():
    hands = next(part for part in detail_parts.part_table() if part.name == "hands")
    ran = {"enhance_detail_fixes": {"hands": 0.45}, "enhance_fix_prompts": {}}
    edited = dict(ran, enhance_fix_prompts={"hands": {"prompt": "open palms", "avoid": "fists"}})

    assert version_settings(ran)["enhance_fix_prompts"] == {
        "hands": {"prompt": hands.prompt, "avoid": hands.avoid, "lora": "", "strength": 1.0}}
    assert version_settings(ran) != version_settings(edited)


def test_a_version_made_before_fixes_had_prompts_of_their_own_records_none():
    assert "enhance_fix_prompts" not in version_settings({"enhance_detail_fixes": {"hands": 0.45}})


def test_a_version_made_before_fixes_had_prompts_is_the_one_that_gives_each_part_its_own():
    before = {"enhance_detail_fixes": {"hands": 0.45}}

    assert full_settings(before) == full_settings(dict(before, enhance_fix_prompts={}))


def test_a_folders_prompts_for_a_fix_are_kept_with_its_settings():
    prompts = {"hands": {"prompt": "open palms", "avoid": "fists"}}
    stored = EnhanceSettings(params={"enhance_fix_prompts": prompts}).to_json()

    assert EnhanceSettings.parse(stored).params["enhance_fix_prompts"] == prompts


def test_a_spoken_fix_redraws_toward_the_prompts_the_panel_gives_that_part(monkeypatch):
    _install_detectors(monkeypatch, "hand_yolov8s.pt", "teeth_yolov8n.pt")
    pane = EnhanceSettings(params={"enhance_fix_prompts": {
        "hands": {"prompt": "open palms", "avoid": "fists"},
        "teeth": {"prompt": "even teeth", "avoid": "gaps"}}})

    params = fix_params_for(_source_row(), _spoken("fix hands"), pane)

    assert params["enhance_fix_prompts"] == {"hands": {"prompt": "open palms", "avoid": "fists"}}


def test_a_folder_stored_with_the_old_detail_pass_still_fixes_what_it_asked_for():
    raw = json.dumps({"auto": True, "params": {
        "enhance_detail_fix": True, "enhance_detail_denoise": 0.45,
        "enhance_face_detector": "teeth_yolov8n.pt"}})
    assert EnhanceSettings.parse(raw).params["enhance_detail_fixes"] == {"teeth": 0.45}
