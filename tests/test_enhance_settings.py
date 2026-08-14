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
from origenerator.gallery.enhance import (
    MATCH_SOURCE_MODEL,
    EnhanceSettings,
    default_enhance_params,
    describe_enhance_params,
    enhance_levels,
    enhance_params_for,
    fold_enhancement,
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


def test_describe_names_a_pinned_model_but_not_the_source_matching_default():
    assert describe_enhance_params({
        "enhance_scale": 2.0, "enhance_steps": 20, "enhance_denoise": 0.15,
        "checkpoint": MATCH_SOURCE_MODEL,
    }) == "2x · 20 steps · 0.15 denoise"
    assert describe_enhance_params({
        "enhance_scale": 2.0, "checkpoint": "driftwood_v1.safetensors",
    }) == "2x · driftwood_v1.safetensors"
    assert describe_enhance_params({}) == ""
