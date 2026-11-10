from __future__ import annotations

import json
from functools import cache, lru_cache

from app_support.comfy_file_refs import frame_name

from origenerator.media import MediaType
from origenerator.output_files import READINGS_KEPT
from origenerator.workflows import UNRECORDED_VERSIONS, WORKFLOW_REGISTRY, workflow_named
from origenerator.workflows.lora_rows import strength_key_of
from origenerator.workflows.model_files import is_no_lora

INSTANCE_KEYS = frozenset({"seed", "noise_seed", "audio_seed", "input_image"})

ENHANCE_KEYS = frozenset({"enhance", "enhance_scale", "enhance_steps", "enhance_denoise"})

GENERATION_SEED_KEYS = ("noise_seed", "seed")


def parse_params(params_json: str | None) -> dict:
    if not params_json:
        return {}
    try:
        params = json.loads(params_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    return params if isinstance(params, dict) else {}


def generation_seed(row: dict) -> str | None:
    params = parse_params(row.get("params_json"))
    for key in GENERATION_SEED_KEYS:
        if params.get(key) not in (None, ""):
            return str(params[key])
    return None if row.get("seed") is None else str(row["seed"])


def settings_only(params: dict) -> dict:
    return {k: v for k, v in params.items() if k not in INSTANCE_KEYS}


def _registered(workflow_name: str | None):
    return WORKFLOW_REGISTRY.get(workflow_name or "")


def _grouping_version(workflow_name: str | None, workflow_version: str | None) -> str:
    if workflow_version and workflow_version not in UNRECORDED_VERSIONS:
        return workflow_version
    wf = workflow_named(workflow_name)
    return wf.version if wf else ""


@cache
def _workflow_instance_keys(workflow_name: str) -> frozenset:
    return frozenset(workflow_named(workflow_name).seed_keys()) | INSTANCE_KEYS


@cache
def _workflow_enhance_keys(workflow_name: str) -> frozenset:
    return frozenset(workflow_named(workflow_name).enhance_keys())


def workflow_enhance_keys(workflow_name: str | None) -> frozenset:
    wf = workflow_named(workflow_name)
    return _workflow_enhance_keys(workflow_name) if wf is not None else ENHANCE_KEYS


def made_from_an_image(workflow_name: str | None) -> bool:
    wf = workflow_named(workflow_name)
    return wf is not None and wf.starts_from_an_image()


def is_image_conditioned(workflow_name: str | None) -> bool:
    return _registered(workflow_name) is not None and made_from_an_image(workflow_name)


def rerollable(row: dict) -> bool:
    wf = _registered(row.get("workflow_name"))
    return wf is not None and not wf.missing_inputs(parse_params(row.get("params_json")))


def canonical_settings(workflow_name: str | None, params: dict) -> dict:
    wf = workflow_named(workflow_name)
    if wf is None:
        return {k: v for k, v in settings_only(params).items() if k not in ENHANCE_KEYS}
    ungrouped = _workflow_instance_keys(workflow_name) | _workflow_enhance_keys(workflow_name)
    settings = {
        key: params.get(key, default)
        for key, default in wf.default_params().items()
        if key not in ungrouped
    }
    for key in wf.loras_keyed_only_when_named:
        if is_no_lora(settings.get(key)):
            settings.pop(key, None)
            settings.pop(strength_key_of(key), None)
    if "scene_frames" in settings and len(settings["scene_frames"] or []) <= 1:
        settings["scene_frames"] = [settings.get("frame_count", params.get("frame_count"))]
    return settings


def enhance_settings(workflow_name: str | None, params: dict) -> dict:
    keys = workflow_enhance_keys(workflow_name)
    wf = _registered(workflow_name)
    if wf is None:
        return {k: v for k, v in params.items() if k in keys}
    return {
        key: params.get(key, default)
        for key, default in wf.default_params().items()
        if key in keys
    }


def workflow_output_type(workflow_name: str | None) -> str | None:
    wf = _registered(workflow_name)
    return wf.output_type if wf else None


def workflow_model_keys(workflow_name: str | None) -> tuple[str, ...]:
    wf = workflow_named(workflow_name)
    return tuple(wf.model_keys) if wf else ()


def workflow_lora_keys(workflow_name: str | None) -> tuple[str, ...]:
    wf = workflow_named(workflow_name)
    return tuple(wf.lora_keys) if wf else ()


def _keyed_signature(keys: tuple[str, ...], params: dict) -> str:
    return json.dumps([params.get(key) for key in keys], default=str)


def _values_signature(keys: tuple[str, ...], params_json: str | None) -> str:
    return _keyed_signature(keys, parse_params(params_json))


def _named_loras(keys: tuple[str, ...], params: dict) -> dict:
    return {k: params.get(k) for k in keys if not is_no_lora(params.get(k))}


@lru_cache(maxsize=READINGS_KEPT)
def model_signature(workflow_name: str | None, params_json: str | None) -> str:
    return _values_signature(workflow_model_keys(workflow_name), params_json)


@lru_cache(maxsize=READINGS_KEPT)
def lora_signature(workflow_name: str | None, params_json: str | None) -> str:
    keys = workflow_lora_keys(workflow_name)
    named = _named_loras(keys, parse_params(params_json))
    wf = workflow_named(workflow_name)
    unkeyed = set(wf.loras_keyed_only_when_named) - named.keys() if wf else set()
    return _keyed_signature(tuple(key for key in keys if key not in unkeyed), named)




def _outputs_video(workflow_name: str | None) -> bool:
    wf = workflow_named(workflow_name)
    return wf is not None and wf.output_type == MediaType.VIDEO


def _input_image_config(input_image: str | None, image_index: dict | None,
                        *, identify: bool = False) -> str:
    name = frame_name(input_image)
    if not name:
        return ""
    entry = (image_index or {}).get(name)
    if entry is None:
        return name
    if identify:
        return entry.prompt_id or name
    return entry.signature


def rows_in_settings(rows, key, image_index=None):
    if key is None:
        return []
    workflow_name, signature = key
    return [
        row for row in rows
        if (row.get("workflow_name") or "") == workflow_name
        and settings_signature(workflow_name, row.get("params_json"), image_index,
                               workflow_version=row.get("workflow_version")) == signature
    ]


def settings_signature(
    workflow_name: str | None,
    params_json: str | None,
    image_index: dict | None = None,
    workflow_version: str | None = None,
) -> str:
    return _signature_of(workflow_name, params_json, workflow_version,
                         _frame_of(workflow_name, params_json, image_index), filed=False)


def folder_signature(
    workflow_name: str | None,
    params_json: str | None,
    image_index: dict | None = None,
    workflow_version: str | None = None,
) -> str:
    return _signature_of(workflow_name, params_json, workflow_version,
                         _frame_of(workflow_name, params_json, image_index), filed=True)


def _frame_of(workflow_name: str | None, params_json: str | None,
              image_index: dict | None) -> str | None:
    if not made_from_an_image(workflow_name):
        return None
    return _input_image_config(_input_image_of(params_json), image_index,
                               identify=_outputs_video(workflow_name))


def _unrecorded_choices(workflow_name: str | None, params: dict, settings: dict) -> dict:
    loras = workflow_lora_keys(workflow_name)
    return {key: None for key in (*workflow_model_keys(workflow_name), *loras)
            if key in settings and key not in params
            and not (key in loras and is_no_lora(settings[key]))}


@lru_cache(maxsize=READINGS_KEPT)
def _input_image_of(params_json: str | None):
    return parse_params(params_json).get("input_image")


@lru_cache(maxsize=READINGS_KEPT)
def _signature_of(workflow_name: str | None, params_json: str | None,
                  workflow_version: str | None, frame: str | None, *, filed: bool) -> str:
    params = parse_params(params_json)
    settings = canonical_settings(workflow_name, params)
    settings = {
        **settings,
        **(_unrecorded_choices(workflow_name, params, settings) if filed else {}),
        "workflow_version": _grouping_version(workflow_name, workflow_version),
    }
    if frame is not None:
        settings["input_image_config"] = frame
    return json.dumps(settings, sort_keys=True, default=str)
