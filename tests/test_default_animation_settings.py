from __future__ import annotations

import json
from unittest.mock import MagicMock

from origenerator import default_animation_settings, gallery
from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database, NewGeneration
from origenerator.workflows import WORKFLOW_REGISTRY
from tests.basic_enhancement import at_the_basic_settings
from tests.comfyui_folders import SUITE_FOLDERS

_I2V = WORKFLOW_REGISTRY["wan22_i2v"]
_IMAGE = "image/image_00001_.png [output]"
_ENHANCED = {"filename": "image_enhance_00001_.png", "subfolder": "image", "type": "output"}


def _client():
    client = ComfyUIClient(folders=SUITE_FOLDERS)
    client.submit_job = MagicMock(return_value="comfy-X")
    client.fetch_history = MagicMock(return_value={})
    client.forget_history = MagicMock()
    return client


def _library(tmp_path):
    db = Database(tmp_path / "t.db")
    db.insert_generation(NewGeneration(prompt_id="image", workflow_name="sdxl_t2i", workflow_version="v",
                         params_json="{}", workflow_json="{}"))
    db.update_generation("image", status="completed", output_files=json.dumps(
        [{"filename": "image_00001_.png", "subfolder": "image", "type": "output"}]))
    db.insert_generation(NewGeneration(prompt_id="sample", workflow_name=_I2V.name,
                         workflow_version=_I2V.version, workflow_json="{}",
                         params_json=json.dumps({**_I2V.default_params(),
                                                 "input_image": _IMAGE})))
    db.update_generation("sample", status="completed",
                         output_files=json.dumps([{"filename": "sample.mp4"}]))
    return db


def test_a_trial_from_an_image_never_enhanced_is_made_from_its_enhancement(qtbot, tmp_path):
    db = _library(tmp_path)
    client = _client()
    trial = default_animation_settings._launcher(db, client)

    said = trial(db.get_generation("sample"), "alpha", "beta")
    (enhance,) = [row for row in db.list_generations() if row["enhance_of"] == "image"]
    client.job_completed.emit(enhance["prompt_id"],
                              {"outputs": {"12": {"images": [_ENHANCED]}}})

    assert said == "Queued. Come back to this one once it has finished."
    assert at_the_basic_settings(enhance)
    assert gallery.row_output_files(db.get_generation("image"))[0] == _ENHANCED
    (trial_video,) = [row for row in db.list_generations()
                      if row["workflow_name"] == _I2V.name and row["prompt_id"] != "sample"]
    assert gallery.parse_params(trial_video["params_json"])["input_image"] \
        == "image/image_enhance_00001_.png [output]"


def test_a_trial_carries_the_prompts_as_edited_under_seeds_the_sample_did_not_use(qtbot, tmp_path):
    db = _library(tmp_path)
    client = _client()
    trial = default_animation_settings._launcher(db, client)

    trial(db.get_generation("sample"), "alpha", "beta")
    (enhance,) = [row for row in db.list_generations() if row["enhance_of"] == "image"]
    client.job_completed.emit(enhance["prompt_id"],
                              {"outputs": {"12": {"images": [_ENHANCED]}}})

    (video,) = [row for row in db.list_generations()
                if row["workflow_name"] == _I2V.name and row["prompt_id"] != "sample"]
    made = gallery.parse_params(video["params_json"])
    sample = gallery.parse_params(db.get_generation("sample")["params_json"])
    assert (made["positive_prompt"], made["negative_prompt"]) == ("alpha", "beta")
    assert all(made[key] != sample[key] for key in _I2V.seed_keys())

