"""Human-facing folder names: how each tier of the tree is labelled for display.

Turns a row's raw params into the short strings the gallery shows — a workflow's
display name, the cleaned model/LoRA filenames, a settings group's prompt-led
headline, a Generate tab's default title, and a source image's folder name. Pure
presentation over the identity layer; depends only on :mod:`.signatures`.
"""

import json

from origenerator.gallery.signatures import (
    _basename,
    _frame_name,
    _named_loras,
    _registered,
    _unannotated,
    settings_only,
    workflow_lora_keys,
    workflow_model_keys,
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
    """A short, human-readable name for a settings group.

    Leads with the positive prompt, then appends the settings that set this
    group apart from its siblings so same-prompt folders stay tellable apart.
    """
    headline = _prompt_headline(params)
    detail_keys = [k for k in sorted(distinguishing_keys) if k != "positive_prompt"]
    if detail_keys:
        detail = ", ".join(f"{k} {_short_value(params.get(k))}" for k in detail_keys)
        return f"{headline} · {detail}" if headline else detail
    return headline or _settings_fallback(params)


def _source_image_label(params: dict, image_index: dict) -> str:
    """The name of the source-image folder a video's start frame belongs to.

    The image generation's own folder label when the frame is a known generation
    (so a video's source folder reads the same as the image it animates), else the
    frame's bare filename, and ``"(no input image)"`` when there is none.
    """
    input_image = params.get("input_image")
    name = _frame_name(input_image)
    if not name:
        return "(no input image)"
    entry = (image_index or {}).get(name)
    return entry.label if entry is not None else _basename(_unannotated(input_image))
