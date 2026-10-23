"""Human-facing folder names: how each tier of the tree is labelled for display.

Turns a row's raw params into the short strings the gallery shows — a workflow's
display name, the cleaned model/LoRA filenames, a settings group's prompt-led
description, a Generate tab's default title, and a source image's folder name.
Pure presentation over the identity layer.

A settings folder is *named* by its key rather than from here (see
:mod:`.keys`) — :func:`config_folder_key` is where a config's key is derived,
since the name is read straight off it. What :func:`settings_label` builds is
the description under that name, which the tree and the folder tiles show on
hover.
"""
from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from origenerator.gallery.enhance_settings import ENHANCE_WORKFLOW
from origenerator.gallery.keys import folder_id, settings_key
from origenerator.gallery.signatures import (
    _basename,
    _frame_name,
    _named_loras,
    _registered,
    _unannotated,
    settings_only,
    workflow_lora_keys,
    workflow_model_keys,
    workflow_output_type,
)
from origenerator.media import MediaType
from origenerator.workflows import RETIRED_WORKFLOW_NAMES

# File extensions stripped from a model filename to make a tidy folder label.
MODEL_EXTS = (".safetensors", ".ckpt", ".pt", ".pth", ".gguf", ".sft")

MEDIA_LABELS = {MediaType.IMAGE: "Images", MediaType.VIDEO: "Videos"}


def workflow_label(workflow_name: str | None) -> str:
    """Human-facing folder name for a workflow: its display name, else the key."""
    wf = _registered(workflow_name)
    if wf:
        return wf.display_name
    return RETIRED_WORKFLOW_NAMES.get(workflow_name or "") or workflow_name or "unknown"


def model_file_name(value) -> str:
    """A model file's display form: final path segment, model extension stripped."""
    base = _basename(str(value))
    for ext in MODEL_EXTS:
        if base.lower().endswith(ext):
            return base[: -len(ext)]
    return base


def _joined_file_label(keys: tuple[str, ...], params: dict, fallback: str) -> str:
    """Join the cleaned filenames a row recorded for ``keys``, else ``fallback``.

    Shared by the model and LoRA folder labels: both name a folder after one or
    more model-file params, differing only in which keys and the empty fallback.
    """
    parts = [model_file_name(params[key]) for key in keys if params.get(key)]
    return " / ".join(parts) or fallback


def model_label(workflow_name: str | None, params: dict) -> str:
    """Human-facing folder name for the model a row used.

    Joins each model param's cleaned filename. Falls back to ``"(unknown
    model)"`` when the workflow declares no model keys or the row recorded none
    of their values (e.g. an imported file whose graph didn't carry the model).
    """
    return _joined_file_label(workflow_model_keys(workflow_name), params, "(unknown model)")


def lora_label(workflow_name: str | None, params: dict) -> str:
    """Human-facing folder name for the LoRA(s) a row used.

    Joins each LoRA param's cleaned filename. Falls back to ``"(no LoRA)"`` when
    the row recorded no LoRA — none of the values (e.g. an older import that
    didn't carry the LoRA), or the "None" sentinel a run chose to bypass it.
    """
    keys = workflow_lora_keys(workflow_name)
    return _joined_file_label(keys, _named_loras(keys, params), "(no LoRA)")


def _prompt_headline(params: dict) -> str:
    """The positive prompt as a single trimmed line, or ``""`` if empty."""
    prompt = " ".join((params.get("positive_prompt") or "").split())
    return prompt[:60] + ("…" if len(prompt) > 60 else "")


def config_tab_title(workflow_name: str | None, params: dict) -> str:
    """A Generate tab's default name: the model (workflow) it runs, followed by
    the gallery folder (the prompt) its output would land in when there is one.

    Leads with the model so tabs stay grouped by pipeline; the prompt distinguishes
    same-model tabs. A blank config is named by its model alone — and one with no
    workflow picked yet is named for what it is, since :func:`workflow_label`'s
    "unknown" reads as a workflow the app failed to recognize rather than a
    question nobody has answered.
    """
    if not workflow_name:
        return "New generation"
    headline = _prompt_headline(settings_only(params))
    model = workflow_label(workflow_name)
    return f"{model} › {headline}" if headline else model


def config_folder_key(workflow_name: str, signature: str) -> str:
    """The key of the gallery folder a config would generate into.

    Takes the ``(workflow, signature)`` pair a config tab holds rather than a
    row, since a tab that has never run has no row to key off
    (:func:`~origenerator.gallery.tree.settings_folder_key` is the same question
    asked of one). It keys the same folder the tree does: a row with no file yet
    is classified by its workflow's declared type, which is what this reads, so
    a config and the generations it makes land on one key.
    """
    return settings_key(workflow_output_type(workflow_name) or MediaType.IMAGE,
                        workflow_name, signature)


def config_folder_name(workflow_name: str, signature: str,
                       folder_meta: dict | None = None) -> str:
    """The gallery folder a config would generate into, by the name it wears
    there: the one the user typed onto it, else its short code — so a config tab
    and its folder read as one thing."""
    key = config_folder_key(workflow_name, signature)
    meta = (folder_meta or {}).get(key) or {}
    return meta.get("custom_name") or folder_id(key)


class JobKind(StrEnum):
    IMAGE = "Image"
    VIDEO = "Video"
    ENHANCE = "Enhance"
    TRAINING = "Training"


def job_kind_label(workflow_name: str | None) -> str:
    """What kind of work a run of ``workflow_name`` is, in the queue's vocabulary.

    Three answers, because they are what a queued job costs: an "Image" is
    seconds, a "Video" is minutes, and an "Enhance" is a second pass over
    something already made. The workflow's own display name is beside this in
    the row and answers none of them — "WAN 2.2 Image-to-Video (Looping)" and
    "WAN 2.2 Image-to-Video" are the same kind of ask, at the same price.

    ``""`` for a workflow this build doesn't have registered — an old import,
    say. A row that says nothing about its kind is read as unknown; one that
    guesses "Image" at a video is read, wrongly, as seconds away.
    """
    if workflow_name == ENHANCE_WORKFLOW:
        return JobKind.ENHANCE
    output_type = workflow_output_type(workflow_name)
    if output_type is None:
        return ""
    return JobKind.VIDEO if output_type == MediaType.VIDEO else JobKind.IMAGE


def _source_image_label(params: dict, image_index: dict,
                        name_of: Callable[[str], str]) -> str:
    """The name of the source-image folder a video's start frame belongs to: the
    name of the picture it animates, or the frame's bare filename when the frame
    isn't a known generation, and ``"(no start image)"`` when there is none."""
    input_image = params.get("input_image")
    frame = _frame_name(input_image)
    if not frame:
        return "(no start image)"
    entry = (image_index or {}).get(frame)
    picture = name_of(entry.prompt_id) if entry is not None else ""
    return picture or _basename(_unannotated(input_image))
