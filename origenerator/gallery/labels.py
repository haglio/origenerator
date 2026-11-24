from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from app_support.comfy_file_refs import frame_name, reference_basename, unannotated

from origenerator.content import as_sentence, item_words
from origenerator.display_names import in_parentheses, shown_name
from origenerator.gallery.enhance_settings import ENHANCE_WORKFLOW
from origenerator.gallery.keys import folder_id, settings_key
from origenerator.gallery.signatures import (
    _named_loras,
    settings_only,
    workflow_lora_keys,
    workflow_model_keys,
    workflow_output_type,
)
from origenerator.media import ItemType, MediaType
from origenerator.model_titles import model_title
from origenerator.workflows import RETIRED_WORKFLOW_NAMES, WORKFLOW_REGISTRY, workflow_named


def item_type_labels() -> dict[ItemType, str]:
    return {item_type: as_sentence(item_words(item_type)[1]) for item_type in ItemType}


def workflow_label(workflow_name: str | None) -> str:
    wf = workflow_named(workflow_name)
    if wf:
        return wf.display_name
    if workflow_name in (None, "", "unknown"):
        return in_parentheses("workflow")
    return RETIRED_WORKFLOW_NAMES.get(workflow_name) or shown_name(workflow_name)


def _joined_file_label(keys: tuple[str, ...], params: dict, fallback: str) -> str:
    parts = dict.fromkeys(model_title(params[key]) for key in keys if params.get(key))
    return " / ".join(parts) or fallback


def model_label(workflow_name: str | None, params: dict) -> str:
    return _joined_file_label(workflow_model_keys(workflow_name), params, in_parentheses("model"))


def lora_label(workflow_name: str | None, params: dict) -> str:
    keys = workflow_lora_keys(workflow_name)
    return _joined_file_label(keys, _named_loras(keys, params), "(no LoRA)")


_HEADLINE_CHARS = 60


def _prompt_headline(params: dict) -> str:
    prompt = " ".join((params.get("positive_prompt") or "").split())
    return prompt[:_HEADLINE_CHARS] + ("…" if len(prompt) > _HEADLINE_CHARS else "")


def generate_tab_title(workflow_name: str | None, params: dict) -> str:
    if not workflow_name:
        return "New generation"
    headline = _prompt_headline(settings_only(params))
    model = workflow_label(workflow_name)
    return f"{model} \u203a {headline}" if headline else model


def config_folder_key(workflow_name: str, signature: str) -> str:
    return settings_key(workflow_output_type(workflow_name) or MediaType.IMAGE,
                        workflow_name, signature)


def config_folder_name(workflow_name: str, signature: str,
                       folder_meta: dict | None = None) -> str:
    key = config_folder_key(workflow_name, signature)
    meta = (folder_meta or {}).get(key) or {}
    return meta.get("custom_name") or folder_id(key)


class JobKind(StrEnum):
    IMAGE = "Image"
    VIDEO = "Video"
    FLICK = "Flick"
    ENHANCE = "Enhance"
    TRAINING = "Training"


_MADE_BY_A_JOB = {JobKind.IMAGE: ItemType.IMAGE, JobKind.VIDEO: ItemType.VIDEO,
                  JobKind.FLICK: ItemType.FLICK}
_JOB_MAKING = {made: kind for kind, made in _MADE_BY_A_JOB.items()}


def made_by_a_job(job_kind: str) -> ItemType | None:
    return _MADE_BY_A_JOB.get(job_kind)


def job_kind_said(job_kind: str) -> str:
    return as_sentence(item_words(ItemType.FLICK)[0]) if job_kind == JobKind.FLICK else str(job_kind)


def job_kind_label(workflow_name: str | None) -> JobKind | str:
    if workflow_name == ENHANCE_WORKFLOW:
        return JobKind.ENHANCE
    workflow = WORKFLOW_REGISTRY.get(workflow_name or "")
    return _JOB_MAKING[workflow.item_type] if workflow is not None else ""


def _source_image_label(params: dict, image_index: dict,
                        name_of: Callable[[str], str]) -> str:
    input_image = params.get("input_image")
    frame = frame_name(input_image)
    if not frame:
        return "(no start image)"
    entry = (image_index or {}).get(frame)
    image = name_of(entry.prompt_id) if entry is not None else ""
    return image or reference_basename(unannotated(input_image))
