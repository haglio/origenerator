from __future__ import annotations

import json

from origenerator.comfyui_inputs import ComfyFolders
from origenerator.output_places import OutputPlaces
from origenerator.regeneration import MADE_ELSEWHERE_TIP, why_it_cannot_be_made_again
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.outside import outside_workflow


def _folders(tmp_path):
    return ComfyFolders(input=tmp_path / "input", places=OutputPlaces.in_one_folder(tmp_path / "out"),
                        temp=tmp_path / "temp")


def _row(workflow_name, **params):
    return {"workflow_name": workflow_name, "params_json": json.dumps(params)}


def _name_and_workflow_from_an_image():
    return next((name, workflow) for name, workflow in WORKFLOW_REGISTRY.items()
                if workflow.generates_here and workflow.input_params)


def test_a_workflow_origenerator_no_longer_has_cannot_be_made_again(tmp_path):
    reason = why_it_cannot_be_made_again(_row("made up"), _folders(tmp_path))

    assert reason == ("Origenerator doesn't have the workflow this was made with, "
                      "so it can't be made again")


def test_what_another_site_made_cannot_be_made_again(tmp_path):
    reason = why_it_cannot_be_made_again(_row(outside_workflow("Sample Site")), _folders(tmp_path))

    assert reason == MADE_ELSEWHERE_TIP


def test_a_model_that_is_not_installed_is_named(tmp_path):
    workflow = WORKFLOW_REGISTRY["sdxl_t2i"]
    row = _row("sdxl_t2i", **dict.fromkeys(workflow.model_keys, "sample made up model.safetensors"))

    reason = why_it_cannot_be_made_again(row, _folders(tmp_path))

    assert "sample made up model" in reason
    assert reason.endswith("installed anymore, so it can't be made again")


def test_a_start_image_that_cannot_be_found_is_named(tmp_path):
    name, workflow = _name_and_workflow_from_an_image()
    key, label = workflow.input_params[0]

    reason = why_it_cannot_be_made_again(_row(name, **{key: "gone.png [output]"}), _folders(tmp_path))

    assert label in reason
    assert reason.endswith("can't be found, so it can't be made again")


def test_a_start_image_still_on_disk_is_no_reason(tmp_path):
    name, workflow = _name_and_workflow_from_an_image()
    (tmp_path / "out").mkdir()
    picks = {}
    for key, _label in workflow.input_params:
        (tmp_path / "out" / f"{key}.png").write_bytes(b"x")
        picks[key] = f"{key}.png [output]"

    reason = why_it_cannot_be_made_again(_row(name, **picks), _folders(tmp_path))

    assert "can't be found" not in (reason or "")


def test_nothing_missing_is_no_reason_at_all(tmp_path):
    assert why_it_cannot_be_made_again(_row("sdxl_t2i"), _folders(tmp_path)) is None


def test_an_item_told_why_it_cannot_be_made_again_gives_that_reason_first(tmp_path):
    row = {**_row("sdxl_t2i"), "why_it_cannot_be_made_again": "Its settings were lost"}

    assert why_it_cannot_be_made_again(row, _folders(tmp_path)) == "Its settings were lost"
