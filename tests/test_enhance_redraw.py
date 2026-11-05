from __future__ import annotations

import json

import pytest

from origenerator import importer
from origenerator.db import Database, NewGeneration
from origenerator.gallery.enhance import (
    enhance_params_for,
    enhancement_versions,
    fix_params_for,
    version_matching_params,
)
from origenerator.gallery.enhance_fold import fold_enhancement
from origenerator.gallery.enhance_settings import MATCH_SOURCE_MODEL, EnhanceSettings
from origenerator.media import MediaType
from origenerator.workflows import WORKFLOW_REGISTRY, detail_parts
from origenerator.workflows.image_enhance import FORMS_THAT_REDRAW


def _classes(payload: dict) -> set[str]:
    return {node["class_type"] for node in payload.values()}


def _enhance_payload(**settings) -> dict:
    workflow = WORKFLOW_REGISTRY["image_enhance"]
    return workflow.build_api_payload(
        dict(workflow.default_params(), input_image="pick.png", **settings))


def test_no_redraw_saves_exactly_what_the_upscaler_gave_without_a_model():
    payload = _enhance_payload(enhance_denoise=0.0)

    assert _classes(payload) == {"LoadImage", "UpscaleModelLoader", "ImageUpscaleWithModel",
                                 "ImageScaleBy", "SaveImage"}


def test_the_upscaler_alone_is_saved_from_a_forms_own_enhance_at_no_redraw_too():
    workflow = WORKFLOW_REGISTRY["krea2_t2i"]
    payload = workflow.build_api_payload(dict(workflow.default_params(), enhance=True,
                                              enhance_denoise=0.0))

    assert payload[payload[workflow.output_node_id]["inputs"]["images"][0]]["class_type"] == "ImageScaleBy"


def _krea_row(**params) -> dict:
    return {"workflow_name": "krea2_t2i", "status": "completed",
            "positive_prompt": "scene one", "negative_prompt": "",
            "output_files": json.dumps([{"filename": "made_up_00001_.png", "subfolder": "",
                                         "type": "output"}]),
            "params_json": json.dumps({"positive_prompt": "scene one", "unet": "made_up_krea.safetensors",
                                       "cfg": 2.5, "sampler_name": "made_up_sampler",
                                       "scheduler": "made_up_scheduler", **params})}


def test_matching_the_source_of_a_krea_image_redraws_with_krea():
    params = enhance_params_for(_krea_row())
    payload = WORKFLOW_REGISTRY["image_enhance"].build_api_payload(params)

    sampler = next(node for node in payload.values() if node["class_type"] == "KSampler")
    model = payload[sampler["inputs"]["model"][0]]
    assert (model["class_type"], model["inputs"]["unet_name"]) == ("UNETLoader", "made_up_krea.safetensors")
    assert (sampler["inputs"]["cfg"], sampler["inputs"]["sampler_name"], sampler["inputs"]["scheduler"]) == (
        2.5, "made_up_sampler", "made_up_scheduler")
    encode = next(node for node in payload.values() if node["class_type"] == "VAEEncode")
    assert payload[encode["inputs"]["vae"][0]]["inputs"]["vae_name"] == "qwen_image_vae.safetensors"
    assert "CheckpointLoaderSimple" not in _classes(payload)


def _redraw_of(params: dict) -> tuple[dict, dict]:
    payload = WORKFLOW_REGISTRY["image_enhance"].build_api_payload(params)
    return payload, next(node for node in payload.values() if node["class_type"] == "KSampler")


def test_a_model_picked_on_the_pane_still_redraws_a_krea_image():
    params = enhance_params_for(_krea_row(), EnhanceSettings(params={"checkpoint": "made_up_sdxl.safetensors"}))
    payload, sampler = _redraw_of(params)

    assert payload[sampler["inputs"]["model"][0]]["inputs"]["ckpt_name"] == "made_up_sdxl.safetensors"
    assert sampler["inputs"]["cfg"] == WORKFLOW_REGISTRY["image_enhance"].default_params()["cfg"]


def test_krea_loras_on_the_source_stay_on_for_its_redraw():
    payload, sampler = _redraw_of(enhance_params_for(_krea_row(lora="made_up_look.safetensors", lora_strength=0.7)))

    lora = payload[sampler["inputs"]["model"][0]]
    assert (lora["class_type"], lora["inputs"]["lora_name"], lora["inputs"]["strength_model"]) == (
        "LoraLoaderModelOnly", "made_up_look.safetensors", 0.7)


def _krea_item_enhanced_by_matching_it(tmp_path) -> tuple[Database, dict]:
    db = Database(tmp_path / "made_up.db")
    row = _krea_row()
    db.insert_generation(NewGeneration(prompt_id="src", workflow_name="krea2_t2i", workflow_version="v002",
                                       positive_prompt="scene one", seed=1, params_json=row["params_json"],
                                       workflow_json="{}"))
    db.update_generation("src", status="completed", output_files=row["output_files"])
    wanted = enhance_params_for(db.get_generation("src"))
    db.insert_generation(NewGeneration(prompt_id="e1", workflow_name="image_enhance", workflow_version="v005",
                                       params_json=json.dumps(wanted), workflow_json="{}"))
    db.update_generation("e1", status="completed", output_files=json.dumps(
        [{"filename": "made_up_00002_.png", "subfolder": "", "type": "output"}]))
    fold_enhancement(db, db.get_generation("e1"))
    return db, wanted


def test_an_item_enhanced_by_matching_its_source_reads_as_already_made(tmp_path):
    db, wanted = _krea_item_enhanced_by_matching_it(tmp_path)

    assert version_matching_params(db.get_generation("src"), wanted) == 0


def test_an_enhancement_by_matching_its_source_shows_as_matching_it(tmp_path):
    db, _wanted = _krea_item_enhanced_by_matching_it(tmp_path)

    assert enhancement_versions(db.get_generation("src"))[0].params["checkpoint"] == MATCH_SOURCE_MODEL


def test_a_fix_after_an_enhancement_stays_on_the_model_that_made_the_item(tmp_path, monkeypatch):
    monkeypatch.setattr(detail_parts, "list_detector_files", lambda: ["teeth_yolov8n.pt"])
    db, _wanted = _krea_item_enhanced_by_matching_it(tmp_path)

    params = fix_params_for(db.get_generation("src"), detail_parts.match_fix_command("fix teeth"))

    assert params["source_model"]["model"] == "made_up_krea.safetensors"
    payload, _sampler = _redraw_of(params)
    assert any(node["class_type"] == "DetailerForEach" for node in payload.values())
    assert "CheckpointLoaderSimple" not in _classes(payload)


def test_a_fix_at_no_redraw_still_has_a_model_to_fix_with(monkeypatch):
    monkeypatch.setattr(detail_parts, "list_detector_files", lambda: ["teeth_yolov8n.pt"])
    params = dict(enhance_params_for(_krea_row()), enhance_denoise=0.0,
                  enhance_detail_fixes={"teeth": 0.4})
    workflow = WORKFLOW_REGISTRY["image_enhance"]
    payload = workflow.build_api_payload(params)

    assert "VAEEncode" not in _classes(payload)
    assert "UNETLoader" in _classes(payload)


@pytest.mark.parametrize(("form", "model_key", "loader"), [
    ("flux_t2i_upscaled", "unet", "UnetLoaderGGUF"),
    ("wan22_t2i", "unet_low", "UNETLoader"),
])
def test_matching_the_source_of_the_other_forms_redraws_with_them(form, model_key, loader):
    row = {**_krea_row(), "workflow_name": form,
           "params_json": json.dumps({model_key: "made_up_model.gguf"})}
    payload, _sampler = _redraw_of(enhance_params_for(row))

    assert any(node["class_type"] == loader and node["inputs"]["unet_name"] == "made_up_model.gguf"
               for node in payload.values())
    assert "CheckpointLoaderSimple" not in _classes(payload)


@pytest.mark.parametrize("form", ["krea2_t2i", "flux_t2i_upscaled", "wan22_t2i"])
def test_a_redraw_by_another_form_is_still_read_as_an_enhancement(form):
    key = WORKFLOW_REGISTRY[form].redraw_model_key
    row = {**_krea_row(), "workflow_name": form, "params_json": json.dumps({key: "made_up_model.safetensors"})}
    payload, _sampler = _redraw_of(enhance_params_for(row))

    assert importer._reconciled("image_enhance", importer._workflow_from_nodes(payload),
                                MediaType.IMAGE) == "image_enhance"


def test_every_form_making_images_with_no_checkpoint_can_redraw():
    without = {name for name, workflow in WORKFLOW_REGISTRY.items()
               if workflow.output_type == MediaType.IMAGE and "checkpoint" not in workflow.default_params()
               and workflow.generates_here}

    assert without == set(FORMS_THAT_REDRAW)
