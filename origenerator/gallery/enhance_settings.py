from __future__ import annotations

import json
from dataclasses import dataclass, field

from origenerator.model_titles import model_title
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.detail_parts import detail_fixes_of, fix_prompts

ENHANCE_WORKFLOW = "image_enhance"

ENHANCE_SETTING_KEYS = (
    "checkpoint", "upscale_model", "enhance_scale", "enhance_steps",
    "enhance_denoise", "enhance_detail_fixes", "enhance_fix_prompts",
)

MATCH_SOURCE_MODEL = "(match the source image)"


def default_enhance_params() -> dict:
    defaults = WORKFLOW_REGISTRY[ENHANCE_WORKFLOW].default_params()
    params = {k: defaults[k] for k in ENHANCE_SETTING_KEYS if k in defaults}
    params["checkpoint"] = MATCH_SOURCE_MODEL
    return params


def version_settings(params: dict) -> dict:
    settings = {k: v for k, v in params.items() if k in ENHANCE_SETTING_KEYS}
    if params.get("source_model"):
        settings["checkpoint"] = MATCH_SOURCE_MODEL
    fixes = detail_fixes_of(params)
    if fixes:
        settings["enhance_detail_fixes"] = fixes
    else:
        settings.pop("enhance_detail_fixes", None)
    if "enhance_fix_prompts" in params:
        settings["enhance_fix_prompts"] = fix_prompts(params)
    return settings


def full_settings(params: dict) -> dict:
    full = {**default_enhance_params(), **version_settings(params)}
    full["enhance_fix_prompts"] = fix_prompts(full)
    return full


@dataclass(frozen=True)
class EnhanceSettings:
    auto: bool = False
    params: dict = field(default_factory=default_enhance_params)

    @classmethod
    def parse(cls, raw: str | None) -> EnhanceSettings:
        try:
            data = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, TypeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        stored = data.get("params")
        params = default_enhance_params()
        if isinstance(stored, dict):
            params.update({k: v for k, v in stored.items() if k in ENHANCE_SETTING_KEYS})
            params["enhance_detail_fixes"] = detail_fixes_of(stored)
        return cls(auto=bool(data.get("auto")), params=params)

    def to_json(self) -> str:
        return json.dumps({"auto": self.auto, "params": self.params})


def describe_enhance_params(params: dict) -> str:
    bits = []
    scale = params.get("enhance_scale")
    if scale is not None:
        bits.append(f"{float(scale):g}x")
    steps = params.get("enhance_steps")
    if steps is not None:
        bits.append(f"{steps} steps")
    denoise = params.get("enhance_denoise")
    if denoise is not None:
        bits.append(f"{float(denoise):g} redraw")
    fixes = detail_fixes_of(params)
    if fixes:
        bits.append(" & ".join(f"{name} {value:g}"
                               for name, value in fixes.items()))
    checkpoint = params.get("checkpoint")
    if checkpoint and checkpoint != MATCH_SOURCE_MODEL:
        bits.append(model_title(checkpoint))
    return " · ".join(bits)
