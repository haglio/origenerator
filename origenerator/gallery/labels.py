"""Human-facing folder names: how each tier of the tree is labelled for display.

Turns a row's raw params into the short strings the gallery shows — a workflow's
display name, the cleaned model/LoRA filenames, a settings group's prompt-led
description, a Generate tab's default title, and a source image's folder name.
Pure presentation over the identity layer.

A settings folder is *named* by its key rather than from here (see
:mod:`.keys`); what :func:`settings_label` builds is the description behind that
name, which the tree and the folder tiles show on hover.
"""

import json

from origenerator.gallery.enhance import ENHANCE_WORKFLOW
from origenerator.gallery.keys import folder_id, settings_key
from origenerator.gallery.output import row_output_files
from origenerator.gallery.signatures import (
    _basename,
    _frame_name,
    _named_loras,
    _registered,
    _unannotated,
    is_image_conditioned,
    settings_only,
    workflow_lora_keys,
    workflow_model_keys,
    workflow_output_type,
)

# File extensions stripped from a model filename to make a tidy folder label.
MODEL_EXTS = (".safetensors", ".ckpt", ".pt", ".pth", ".gguf", ".sft")


def workflow_label(workflow_name: str | None) -> str:
    """Human-facing folder name for a workflow: its display name, else the key."""
    wf = _registered(workflow_name)
    return wf.display_name if wf else (workflow_name or "unknown")


def _model_name(value) -> str:
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
    parts = [_model_name(params[key]) for key in keys if params.get(key)]
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


def item_label(row: dict | None) -> str:
    """The name one generation wears where a single item has to be named — a
    Generate tab's, say. The file it produced, which is what the info block
    calls it by too, so an item reads the same wherever it is named.

    ``""`` for a row with nothing on disk — a run still in flight, or one whose
    files are gone — leaving the caller to name it by the folder it sits in
    instead (:func:`config_folder_name`).
    """
    for file in row_output_files(row or {}):
        name = _basename(file.get("filename") or "")
        if name:
            return name
    return ""


def config_folder_name(workflow_name: str, signature: str,
                       folder_meta: dict | None = None) -> str:
    """The gallery folder a config would generate into, by the name it wears
    there: the one the user typed onto it, else its short code.

    Takes the ``(workflow, signature)`` pair a config tab holds rather than a
    row, since a tab that has never run has no row to key off — but keys the
    same folder the tree does, so a tab and its folder wear one name.
    """
    key = settings_key(workflow_output_type(workflow_name) or "image",
                       workflow_name, signature)
    meta = (folder_meta or {}).get(key) or {}
    return meta.get("custom_name") or folder_id(key)


def job_kind_label(workflow_name: str | None) -> str:
    """What kind of work a run of ``workflow_name`` is, in the queue's vocabulary.

    Four answers, because they are what a queued job costs and what it needs
    before it can start: an "Image" is seconds, a "T2V" is minutes out of words
    alone, an "I2V" is minutes out of a picture that has to exist first, and an
    "Enhance" is a second pass over something already made. The workflow's own
    display name is beside this in the row and answers none of them — "WAN 2.2
    FLF2V Loop" and "WAN 2.2 I2V" are the same kind of ask, at the same price.

    ``""`` for a workflow this build doesn't have registered — an old import,
    say. A row that says nothing about its kind is read as unknown; one that
    guesses "Image" at a video is read, wrongly, as seconds away.
    """
    if workflow_name == ENHANCE_WORKFLOW:
        return "Enhance"
    output_type = workflow_output_type(workflow_name)
    if output_type is None:
        return ""
    if output_type == "video":
        return "I2V" if is_image_conditioned(workflow_name) else "T2V"
    return "Image"


def _short_value(value) -> str:
    text = str(value)
    return text[:24] + ("…" if len(text) > 24 else "")


def _settings_fallback(params: dict) -> str:
    """A name for a prompt-less, otherwise-undistinguished settings group."""
    bits = []
    if "width" in params and "height" in params:
        bits.append(f"{params['width']}×{params['height']}")
    for key in ("steps", "cfg"):
        if key in params:
            bits.append(f"{key} {params[key]}")
    return ", ".join(bits) or "(default settings)"


def _distinguishing_keys(settings_list: list[dict]) -> set[str]:
    """Setting keys whose value is not identical across every group."""
    if len(settings_list) <= 1:
        return set()
    keys = set().union(*settings_list)
    return {
        key for key in keys
        if len({
            json.dumps(s[key], sort_keys=True, default=str) if key in s else "\x00"
            for s in settings_list
        }) > 1
    }


def settings_label(params: dict, distinguishing_keys=()) -> str:
    """A short, human-readable description of a settings group.

    Leads with the positive prompt, then appends the settings that set this
    group apart from its siblings so same-prompt folders stay tellable apart.
    Rides the folder's tooltip rather than its name — the name is a code, so this
    is what says which folder you are hovering over.
    """
    headline = _prompt_headline(params)
    detail_keys = [k for k in sorted(distinguishing_keys) if k != "positive_prompt"]
    if detail_keys:
        detail = ", ".join(f"{k} {_short_value(params.get(k))}" for k in detail_keys)
        return f"{headline} · {detail}" if headline else detail
    return headline or _settings_fallback(params)


def _source_image_label(params: dict, image_index: dict) -> str:
    """The name of the source-image folder a video's start frame belongs to.

    The frame's own filename leads, then the code of the image generation's own
    folder — so a video's source folder names *which* picture it animates, and
    reads as the same folder that picture sits in over in the Images tree. The
    filename comes first because the tier is one frame per folder, and two draws
    of one prompt land in one settings folder, so they would otherwise wear the
    same code. Falls back to the bare filename when the frame isn't a known
    generation — there is no folder to borrow a code from — and ``"(no input
    image)"`` when there is none.
    """
    input_image = params.get("input_image")
    name = _frame_name(input_image)
    if not name:
        return "(no input image)"
    filename = _basename(_unannotated(input_image))
    entry = (image_index or {}).get(name)
    return f"{filename} · {entry.label}" if entry is not None else filename
