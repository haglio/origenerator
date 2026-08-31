"""A folder's enhancement settings, and the levels an image accumulates.

Enhancement configuration belongs to the FOLDER — it is not one of the params
that decide which folder a run lands in — so it is stored beside the folder's
name and star, and met with a particular image only when an enhance is launched.
Each enhance folds in as another level, recording what made it, so an image that
has been enhanced twice at different settings can show which is which.
"""

import json

import pytest

from origenerator import gallery
from origenerator.db import Database
from origenerator.workflows import detail_parts
from origenerator.workflows.detail_parts import DEFAULT_FIX_DENOISE
from origenerator.gallery.enhance_fold import fold_enhancement
from origenerator.gallery.enhance import (
    MATCH_SOURCE_MODEL,
    EnhanceSettings,
    default_enhance_params,
    describe_enhance_params,
    displayed_levels,
    enhance_levels,
    enhance_params_for,
    fix_params_for,
    level_matching_params,
    level_matching_settings,
    remove_enhance_levels,
)


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


# --- the stored settings ---------------------------------------------------


def test_an_unconfigured_folder_reads_as_the_defaults_with_the_box_off():
    settings = EnhanceSettings.parse(None)
    assert settings.auto is False
    assert settings.params == default_enhance_params()
    # The model defaults to deferring to the image, not to a pinned checkpoint.
    assert settings.params["checkpoint"] == MATCH_SOURCE_MODEL


@pytest.mark.parametrize("raw", ["", "not json", "[]", "null"])
def test_unreadable_stored_settings_fall_back_to_the_defaults(raw):
    # A folder's settings must never be able to break the panel that shows them.
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
    # Keys the stored blob didn't carry still come back at their defaults.
    assert back.params["upscale_model"] == default_enhance_params()["upscale_model"]


def test_stored_settings_cannot_smuggle_in_params_outside_the_panel():
    # Only the knobs the subpanel offers are honored: a stored blob naming, say,
    # the input image must not be able to redirect what an enhance runs on.
    back = EnhanceSettings.parse(json.dumps(
        {"auto": True, "params": {"input_image": "elsewhere.png", "enhance_steps": 12}}
    ))
    assert "input_image" not in back.params
    assert back.params["enhance_steps"] == 12


# --- meeting a particular image --------------------------------------------


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
    # Untouched by the folder: what to enhance, and what steers the texture.
    assert params["input_image"] == "image/sdxl_t2i_src.png [output]"
    assert params["positive_prompt"] == "a lantern on a jetty"
    assert params["negative_prompt"] == "blurry"


def test_the_detail_pass_is_one_of_the_knobs_the_panel_sets():
    # It is part of what an enhancement IS, not a property of one image, so it
    # is set once on the panel and every enhance launched from there carries it.
    settings = EnhanceSettings(params={"enhance_detail_fixes": {"teeth": 0.5}})
    params = enhance_params_for(_source_row(), settings)
    assert params["enhance_detail_fixes"] == {"teeth": 0.5}
    # Left alone every part stays at zero, so nothing starts paying for a pass
    # by accident.
    unset = enhance_params_for(_source_row(), EnhanceSettings())
    assert unset["enhance_detail_fixes"] == {}


def test_the_default_model_leaves_the_source_image_its_own_checkpoint():
    # An enhanced image should stay in its own style, so the panel's default
    # defers to whichever checkpoint made the image rather than pinning one.
    params = enhance_params_for(_source_row(), EnhanceSettings())
    assert params["checkpoint"] == "anemone_v3.safetensors"


def test_pinning_a_model_in_the_folder_overrides_the_sources_own():
    settings = EnhanceSettings(params={"checkpoint": "driftwood_v1.safetensors"})
    params = enhance_params_for(_source_row(), settings)
    assert params["checkpoint"] == "driftwood_v1.safetensors"


def test_no_settings_at_all_still_yields_the_workflow_defaults():
    # Every caller that has no folder in hand (an import, a test) still gets a
    # runnable set of params.
    params = enhance_params_for(_source_row())
    defaults = gallery.default_enhance_params()
    assert params["enhance_scale"] == defaults["enhance_scale"]
    assert params["enhance_steps"] == defaults["enhance_steps"]


# --- the levels an image accumulates ---------------------------------------


def _enhance_row(prompt_id, filename, **knobs):
    params = {"input_image": "image/sdxl_t2i_src.png [output]", **knobs}
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


def _add_and_fold(db, prompt_id, filename, **knobs):
    db.insert_generation(
        prompt_id=prompt_id, workflow_name="image_enhance", workflow_version="v001",
        params_json=json.dumps({"input_image": "image/sdxl_t2i_src.png [output]", **knobs}),
        workflow_json="{}",
    )
    db.update_generation(prompt_id, status="completed", output_files=json.dumps(
        [{"filename": filename, "subfolder": "image", "type": "output"}]))
    return fold_enhancement(db, db.get_generation(prompt_id))


def test_an_unenhanced_image_has_no_levels():
    # Nothing has been applied, so there is nothing to list or choose between.
    assert enhance_levels(_source_row()) == []


def test_an_inline_enhanced_image_lists_the_one_enhancement_it_received():
    # Every image the green badge marks lists here — including the ones the
    # inline tail finished, which kept no original. There is one file and no
    # "before", so the list is that single enhancement, named by the knobs the
    # tail ran at so it can still be dragged onto the panel and reused.
    row = dict(_source_row(), params_json=json.dumps({
        "positive_prompt": "a lantern on a jetty",
        "enhance": True, "enhance_scale": 2.0, "enhance_steps": 20,
        "enhance_denoise": 0.15,
    }))
    (level,) = enhance_levels(row)
    assert level.label == "Enhance 1"
    assert level.settings == "2x · 20 steps · 0.15 denoise"
    assert level.file["filename"] == "sdxl_t2i_src.png"


def test_a_batch_the_tail_finished_lists_one_level_not_one_per_file():
    # A batch's files are siblings of each other, not versions of each other,
    # however many the run saved.
    row = dict(
        _source_row(),
        params_json=json.dumps({"enhance": True, "enhance_scale": 2.0}),
        output_files=json.dumps([
            {"filename": "sdxl_t2i_a.png", "subfolder": "image", "type": "output"},
            {"filename": "sdxl_t2i_b.png", "subfolder": "image", "type": "output"},
        ]),
    )
    assert [lvl.label for lvl in enhance_levels(row)] == ["Enhance 1"]


def test_a_batch_of_several_files_is_not_mistaken_for_levels():
    # A batch generation saves several files from one run, and none of them is a
    # level of any other — only original_files says a row has been enhanced.
    batch = dict(_source_row(), output_files=json.dumps([
        {"filename": "sdxl_t2i_a.png", "subfolder": "image", "type": "output"},
        {"filename": "sdxl_t2i_b.png", "subfolder": "image", "type": "output"},
    ]))
    assert enhance_levels(batch) == []


def test_each_fold_adds_a_level_naming_the_settings_that_made_it(tmp_path):
    db = Database(tmp_path / "t.db")
    _seed_source(db)
    _add_and_fold(db, "e1", "image_enhance_00001_.png",
                  enhance_scale=2.0, enhance_steps=20, enhance_denoise=0.15)
    _add_and_fold(db, "e2", "image_enhance_00002_.png",
                  enhance_scale=3.0, enhance_steps=40, enhance_denoise=0.35)

    levels = enhance_levels(db.get_generation("src"))
    # Most-enhanced first — which is also what the preview opens on.
    assert [lvl.label for lvl in levels] == ["Enhance 2", "Enhance 1", "Original"]
    assert levels[0].file["filename"] == "image_enhance_00002_.png"
    assert levels[0].settings == "3x · 40 steps · 0.35 denoise"
    assert levels[1].settings == "2x · 20 steps · 0.15 denoise"
    assert levels[2].settings == ""      # an original was not enhanced at anything
    assert levels[2].is_original


def test_a_level_folded_before_settings_were_recorded_still_lists(tmp_path):
    # Rows enhanced by an earlier version of the app have no enhance_history;
    # their levels must still appear, just without settings to name.
    db = Database(tmp_path / "t.db")
    _seed_source(db)
    _add_and_fold(db, "e1", "image_enhance_00001_.png", enhance_scale=2.0)
    db.update_generation("src", enhance_history=None)

    levels = enhance_levels(db.get_generation("src"))
    assert [lvl.label for lvl in levels] == ["Enhance 1", "Original"]
    assert levels[0].settings == ""


def test_enhance_history_survives_capture_and_restore(tmp_path):
    # The undoable-delete path restores rows verbatim; the levels' settings must
    # come back with them or a restored image forgets what it was enhanced at.
    db = Database(tmp_path / "t.db")
    _seed_source(db)
    _add_and_fold(db, "e1", "image_enhance_00001_.png", enhance_steps=25)
    row = db.get_generation("src")
    db.delete_generation("src")
    db.restore_generation(row)
    assert db.get_generation("src")["enhance_history"] == row["enhance_history"]


def test_a_level_recorded_before_a_knob_existed_still_reads_as_a_duplicate(tmp_path):
    # The knob list grows, and a level recorded before one existed was made with
    # it at its default — so it still matches settings that leave it there, and
    # the + Enhance card still knows it would only be making the same thing
    # twice. Turning the new knob on is a different enhancement, and does not.
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
    assert level_matching_settings(row, settings) == 0
    assert level_matching_settings(
        row, EnhanceSettings(params=dict(settings.params,
                                         enhance_detail_fixes={"faces": 0.45}))
    ) is None


def test_describe_names_each_part_the_pass_redrew_at_its_own_denoise():
    # Two versions of one image can differ by nothing but this, and the strip's
    # captions are the only place that difference is visible.
    assert describe_enhance_params({
        "enhance_scale": 2.0, "enhance_steps": 20, "enhance_denoise": 0.15,
        "enhance_detail_fixes": {"faces": 0.45, "hands": 0.6},
    }) == "2x · 20 steps · 0.15 denoise · faces 0.45 & hands 0.6"
    # A part at zero says nothing: it is the default rather than a choice, the
    # same reason a source-matched model goes unnamed.
    assert describe_enhance_params({
        "enhance_scale": 2.0, "enhance_detail_fixes": {"faces": 0}}) == "2x"


def test_describe_names_a_pinned_model_but_not_the_source_matching_default():
    assert describe_enhance_params({
        "enhance_scale": 2.0, "enhance_steps": 20, "enhance_denoise": 0.15,
        "checkpoint": MATCH_SOURCE_MODEL,
    }) == "2x · 20 steps · 0.15 denoise"
    assert describe_enhance_params({
        "enhance_scale": 2.0, "checkpoint": "driftwood_v1.safetensors",
    }) == "2x · driftwood_v1.safetensors"
    assert describe_enhance_params({}) == ""


# --- what the info pane lists, and what deleting a level leaves behind ------


def test_an_unenhanced_image_still_lists_its_one_file_as_the_original():
    # This is where an image's versions live, so it has to be somewhere you can
    # already see before the first enhancement makes a second one.
    (level,) = displayed_levels(_source_row())
    assert level.is_original
    assert level.file["filename"] == "sdxl_t2i_src.png"


def test_a_video_lists_no_versions():
    # The enhancer takes images, so a video's file stays in the block at the top.
    video = dict(_source_row(), output_files=json.dumps(
        [{"filename": "wan_00001.mp4", "subfolder": "video", "type": "output"}]))
    assert displayed_levels(video) == []


def _folded(tmp_path, count=1):
    db = Database(tmp_path / "t.db")
    _seed_source(db)
    for i in range(1, count + 1):
        _add_and_fold(db, f"e{i}", f"image_enhance_0000{i}_.png",
                      enhance_scale=float(i + 1))
    return db.get_generation("src")


def test_removing_an_enhancement_leaves_the_others(tmp_path):
    row = _folded(tmp_path, count=2)
    updates = remove_enhance_levels(row, ["image_enhance_00002_.png"])
    after = dict(row, **updates)
    assert [lvl.label for lvl in enhance_levels(after)] == ["Enhance 1", "Original"]
    # The surviving level keeps its own settings and its own run id — the id
    # rides with the level it belongs to, so binning the newer enhancement takes
    # the place on the Recents shelf it had lifted the image to along with it.
    older = json.loads(row["enhance_history"])[1]
    assert json.loads(after["enhance_history"]) == [
        {"filename": "image_enhance_00001_.png", "params": {"enhance_scale": 2.0},
         "run_id": older["run_id"]}
    ]


def test_removing_the_last_enhancement_leaves_a_plain_image(tmp_path):
    # An original still marked as one would read as an enhancement of itself.
    row = _folded(tmp_path, count=1)
    after = dict(row, **remove_enhance_levels(row, ["image_enhance_00001_.png"]))
    assert after["original_files"] is None
    assert after["enhance_history"] is None
    assert not gallery.is_enhanced_row(after)
    assert enhance_levels(after) == []


def test_removing_the_original_keeps_every_enhancement_named(tmp_path):
    # Binning the pre-enhance file is a fair thing to want; what is left is
    # still two enhancements, and each still says what made it.
    row = _folded(tmp_path, count=2)
    after = dict(row, **remove_enhance_levels(row, ["sdxl_t2i_src.png"]))
    levels = enhance_levels(after)
    assert [lvl.label for lvl in levels] == ["Enhance 2", "Enhance 1"]
    assert levels[0].params == {"enhance_scale": 3.0}
    assert gallery.is_enhanced_row(after)   # still an enhanced image, badge and all


def test_removing_an_inline_tails_enhancement_untags_its_base_render():
    # An inline run tags the base render it kept; left tagged with nothing ahead
    # of it, that one file would read as an enhancement of itself.
    row = dict(
        _source_row(),
        params_json=json.dumps({"enhance": False}),
        output_files=json.dumps([
            {"filename": "enhanced.png", "subfolder": "image"},
            {"filename": "base.png", "subfolder": "image", "role": "original"},
        ]),
    )
    after = dict(row, **remove_enhance_levels(row, ["enhanced.png"]))
    assert json.loads(after["output_files"]) == [
        {"filename": "base.png", "subfolder": "image"}
    ]
    assert not gallery.is_enhanced_row(after)


def test_removing_every_version_changes_nothing(tmp_path):
    # A generation with no file is a generation deleted, which is a bigger
    # delete than a version list should make.
    row = _folded(tmp_path, count=1)
    assert remove_enhance_levels(
        row, ["image_enhance_00001_.png", "sdxl_t2i_src.png"]) == {}


def test_removing_a_name_the_row_never_held_changes_nothing(tmp_path):
    assert remove_enhance_levels(_folded(tmp_path), ["someone_elses.png"]) == {}


def test_describe_still_names_a_level_recorded_the_old_way():
    # Every enhancement in the library predates the per-part numbers, and its
    # caption must go on reading as what it did — a targeted fix by its part,
    # the generic pass as the pair it ran.
    assert describe_enhance_params({
        "enhance_scale": 2.0, "enhance_steps": 20, "enhance_denoise": 0.15,
        "enhance_detail_fix": True, "enhance_detail_denoise": 0.45,
        "enhance_face_detector": "teeth_yolov8n.pt", "enhance_hand_detector": "",
    }) == "2x · 20 steps · 0.15 denoise · teeth 0.45"
    assert describe_enhance_params({
        "enhance_detail_fix": True, "enhance_detail_denoise": 0.45,
        "enhance_face_detector": "face_yolov8m.pt",
        "enhance_hand_detector": "hand_yolov8s.pt",
    }) == "faces 0.45 & hands 0.45"


# --- a spoken "fix <part>": the latest enhancement plus a targeted pass -----


def _spoken(text):
    parts = gallery.match_fix_command(text)
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

    # Equivalent to the LATEST enhancement — not to whatever the panel says now.
    assert params["enhance_scale"] == 3.0
    assert params["enhance_steps"] == 40
    assert params["checkpoint"] == "driftwood_v1.safetensors"
    # Re-derived from the original, like any re-enhance, with the one pass on.
    assert params["input_image"] == "image/sdxl_t2i_src.png [output]"
    assert params["enhance_detail_fixes"] == {"teeth": DEFAULT_FIX_DENOISE}


def test_a_spoken_fix_on_an_unenhanced_image_runs_at_the_current_settings(monkeypatch):
    _install_detectors(monkeypatch, "hand_yolov8s.pt")
    params = fix_params_for(_source_row(), _spoken("fix hands"),
                            EnhanceSettings(params={"enhance_steps": 33}))
    assert params["enhance_steps"] == 33
    assert params["enhance_detail_fixes"] == {"hands": DEFAULT_FIX_DENOISE}


def test_a_spoken_fix_runs_the_part_asked_for_and_not_the_panels_other_boxes(
        monkeypatch):
    # The bug this is here for: a folder set to fix every part turned a spoken
    # "fix teeth" into a pass over all of them — a redraw of the whole picture
    # in answer to a command about one part of it. The panel's ticks configure
    # what an *enhancement* fixes; a spoken fix says its own parts out loud.
    _install_detectors(monkeypatch, "teeth_yolov8n.pt", "face_yolov8m.pt",
                       "hand_yolov8s.pt", "eyes_yolov8n.pt")
    panel = EnhanceSettings(params={"enhance_detail_fixes": {
        "faces": 0.4, "hands": 0.5, "teeth": 0.6, "eyes": 0.3}})

    params = fix_params_for(_source_row(), _spoken("fix teeth"), panel)

    # Its own number for that part, since nobody says a denoise out loud — and
    # nothing else the panel happens to have ticked.
    assert params["enhance_detail_fixes"] == {"teeth": 0.6}


def test_a_spoken_fix_can_ask_for_several_parts_at_once(monkeypatch):
    _install_detectors(monkeypatch, "hand_yolov8s.pt", "teeth_yolov8n.pt")

    params = fix_params_for(_source_row(), _spoken("fix hands and mouth"))

    assert params["enhance_detail_fixes"] == {
        "hands": DEFAULT_FIX_DENOISE, "teeth": DEFAULT_FIX_DENOISE}


def test_a_part_with_nothing_to_find_it_is_dropped_from_a_combination(monkeypatch):
    # The hands still get fixed; a missing teeth detector would otherwise have
    # ComfyUI reject the whole prompt.
    _install_detectors(monkeypatch, "hand_yolov8s.pt")

    params = fix_params_for(_source_row(), _spoken("fix hands and mouth"))

    assert params["enhance_detail_fixes"] == {"hands": DEFAULT_FIX_DENOISE}


def test_a_spoken_fix_runs_the_part_at_the_number_the_panel_gives_it(monkeypatch):
    # Nobody says a denoise out loud, so the panel's own number for that part is
    # what the command means — its default only where the panel leaves it alone.
    _install_detectors(monkeypatch, "hand_yolov8s.pt")
    params = fix_params_for(
        _source_row(), _spoken("fix hands"),
        EnhanceSettings(params={"enhance_detail_fixes": {"hands": 0.7}}))
    assert params["enhance_detail_fixes"] == {"hands": 0.7}


def test_a_spoken_fix_with_no_detector_for_the_part_declines(monkeypatch):
    # The caller answers "install one" out loud; a pass that finds nothing is
    # not a fix.
    _install_detectors(monkeypatch, "face_yolov8m.pt", "hand_yolov8s.pt")
    assert fix_params_for(_source_row(), _spoken("fix teeth")) is None


def test_successive_spoken_fixes_accumulate_rather_than_trade_away(
        tmp_path, monkeypatch):
    # Every enhance re-derives from the original, so a "fix eyes" that dropped
    # the teeth pass would undo the mended teeth on screen. The latest level's
    # passes ride along instead.
    _install_detectors(monkeypatch, "eyes_yolov8n.pt", "teeth_yolov8n.pt")
    db = Database(tmp_path / "t.db")
    _seed_source(db)
    _add_and_fold(db, "e1", "image_enhance_00001_.png",
                  enhance_detail_fixes={"teeth": 0.5})

    params = fix_params_for(db.get_generation("src"), _spoken("fix eyes"))

    assert params["enhance_detail_fixes"] == {
        "teeth": 0.5, "eyes": DEFAULT_FIX_DENOISE}


def test_a_spoken_fix_accumulates_onto_a_level_recorded_the_old_way(
        tmp_path, monkeypatch):
    # The level being added to is whatever the library already holds, and that
    # is the old shape everywhere: its passes must ride along all the same.
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


def test_a_repeated_spoken_fix_reads_as_the_duplicate_it_is(tmp_path, monkeypatch):
    _install_detectors(monkeypatch, "eyes_yolov8n.pt", "teeth_yolov8n.pt")
    db = Database(tmp_path / "t.db")
    _seed_source(db)
    first = fix_params_for(db.get_generation("src"), _spoken("fix teeth"))
    _add_and_fold(db, "e1", "image_enhance_00001_.png",
                  **{k: first[k] for k in gallery.ENHANCE_SETTING_KEYS})
    row = db.get_generation("src")

    # Asking again would remake the level it already has; a different part is a
    # different enhancement and runs.
    assert level_matching_params(row, fix_params_for(row, _spoken("fix teeth"))) == 0
    assert level_matching_params(row, fix_params_for(row, _spoken("fix eyes"))) is None
