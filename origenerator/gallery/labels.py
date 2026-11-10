from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from app_support.comfy_file_refs import frame_name, reference_basename, unannotated

from origenerator.gallery.enhance_settings import ENHANCE_WORKFLOW
from origenerator.gallery.keys import folder_id, settings_key
from origenerator.gallery.signatures import (
    _named_loras,
    settings_only,
    workflow_lora_keys,
    workflow_model_keys,
    workflow_output_type,
)
from origenerator.media import MediaType
from origenerator.model_titles import model_title
from origenerator.workflows import RETIRED_WORKFLOW_NAMES, workflow_named

MEDIA_LABELS = {MediaType.IMAGE: "Images", MediaType.VIDEO: "Videos"}


def workflow_label(workflow_name: str | None) -> str:
    wf = workflow_named(workflow_name)
    if wf:
        return wf.display_name
    return RETIRED_WORKFLOW_NAMES.get(workflow_name or "") or workflow_name or "unknown"


def _joined_file_label(keys: tuple[str, ...], params: dict, fallback: str) -> str:
    parts = [model_title(params[key]) for key in keys if params.get(key)]
    return " / ".join(parts) or fallback


def model_label(workflow_name: str | None, params: dict) -> str:
    return _joined_file_label(workflow_model_keys(workflow_name), params, "(unknown model)")


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
    ENHANCE = "Enhance"
    TRAINING = "Training"


def job_kind_label(workflow_name: str | None) -> str:
    if workflow_name == ENHANCE_WORKFLOW:
        return JobKind.ENHANCE
    output_type = workflow_output_type(workflow_name)
    if output_type is None:
        return ""
    return JobKind.VIDEO if output_type == MediaType.VIDEO else JobKind.IMAGE


def _source_image_label(params: dict, image_index: dict,
                        name_of: Callable[[str], str]) -> str:
    input_image = params.get("input_image")
    frame = frame_name(input_image)
    if not frame:
        return "(no start image)"
    entry = (image_index or {}).get(frame)
    image = name_of(entry.prompt_id) if entry is not None else ""
    return image or reference_basename(unannotated(input_image))
