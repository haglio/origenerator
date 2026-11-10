from __future__ import annotations

from origenerator.comfyui_inputs import ComfyFolders, file_named_by
from origenerator.generation_config import filled_params
from origenerator.setting_advice import named_models, not_installed, spoken_list
from origenerator.workflows import RETIRED_WORKFLOW_NAMES, workflow_named

MADE_ELSEWHERE_TIP = "Another site made this — Origenerator can't remake it"


def workflow_gone(workflow_name: str) -> str:
    retired = RETIRED_WORKFLOW_NAMES.get(workflow_name)
    return (f"{retired} has been retired" if retired
            else "Origenerator doesn't have the workflow this was made with")


def told_why_it_cannot_be_made_again(row: dict | None) -> str | None:
    return (row or {}).get("why_it_cannot_be_made_again") or None


def why_it_cannot_be_made_again(row: dict, folders: ComfyFolders) -> str | None:
    told = told_why_it_cannot_be_made_again(row)
    if told is not None:
        return told
    workflow_name = row.get("workflow_name") or ""
    workflow = workflow_named(workflow_name)
    if workflow is None:
        return f"{workflow_gone(workflow_name)}, so it can't be made again"
    if not workflow.generates_here:
        return MADE_ELSEWHERE_TIP
    params = filled_params(row, workflow)
    gone = [label for key, label in workflow.input_params
            if file_named_by(str(params.get(key) or "") or None, folders) is None]
    if gone:
        return f"Its {spoken_list(gone, 'and')} can't be found, so it can't be made again"
    models = list(not_installed(params, workflow.param_definitions(),
                                (*workflow.model_keys, *workflow.lora_keys)).values())
    if models:
        verb = "isn't" if len(models) == 1 else "aren't"
        return f"{named_models(models)} {verb} installed anymore, so it can't be made again"
    return None
