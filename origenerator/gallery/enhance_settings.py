from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import MappingProxyType

from origenerator.model_titles import model_title
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.detail_parts import detail_fixes_of, fix_prompts, part_table

ENHANCE_WORKFLOW = "image_enhance"

ENHANCE_SETTING_KEYS = (
    "checkpoint", "upscale_model", "enhance_scale", "enhance_steps",
    "enhance_denoise", "enhance_detail_fixes", "enhance_fix_prompts",
)

MATCH_SOURCE_MODEL = "(match the source image)"

LABELS_ON_THE_ENHANCE_PANE = MappingProxyType({
    "checkpoint": "Model", "upscale_model": "Upscaler", "enhance_scale": "Scale",
    "enhance_steps": "Steps", "enhance_denoise": "Redraw amount",
})


def match_source_model_label() -> str:
    fallback = WORKFLOW_REGISTRY[ENHANCE_WORKFLOW].default_params()["checkpoint"]
    return f"(match the source image's model, or fall back to default model {model_title(fallback)})"


def default_enhance_params() -> dict:
    defaults = WORKFLOW_REGISTRY[ENHANCE_WORKFLOW].default_params()
    params = {k: defaults[k] for k in ENHANCE_SETTING_KEYS if k in defaults}
    params["checkpoint"] = MATCH_SOURCE_MODEL
    return params


def basic_enhance_settings() -> EnhanceSettings:
    defaults = WORKFLOW_REGISTRY[ENHANCE_WORKFLOW].default_params()
    return EnhanceSettings(params={
        "checkpoint": defaults["checkpoint"], "upscale_model": defaults["upscale_model"],
        "enhance_scale": 2.0, "enhance_steps": 20, "enhance_denoise": 0.0,
        "enhance_detail_fixes": {}, "enhance_fix_prompts": {},
    })


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
    said = _settings_said(params)
    fixes = detail_fixes_of(params)
    bits = [
        said.get("enhance_scale"),
        f"{said['enhance_steps']} steps" if "enhance_steps" in said else None,
        f"{said['enhance_denoise']} redraw" if "enhance_denoise" in said else None,
        " & ".join(f"{name} {value:g}" for name, value in fixes.items()),
        said.get("checkpoint"),
    ]
    return " · ".join(bit for bit in bits if bit)


def enhance_settings_fields(params: dict) -> list[tuple[str, str]]:
    said = _settings_said(params)
    return [(label, said[key]) for key, label in LABELS_ON_THE_ENHANCE_PANE.items() if key in said]


def fix_details(params: dict) -> dict[str, str]:
    amounts = detail_fixes_of(params)
    prompts = fix_prompts(params)
    drawn_in_order = [part.name for part in part_table() if part.name in amounts]
    return {name: _fix_detail(amounts[name], prompts.get(name, {}))
            for name in [*drawn_in_order, *(name for name in amounts if name not in drawn_in_order)]}


def _fix_detail(amount: float, own: dict) -> str:
    lora = own.get("lora")
    return f"{amount:g} · {model_title(lora)} {own['strength']:g}" if lora else f"{amount:g}"


def _settings_said(params: dict) -> dict[str, str]:
    said = {}
    scale = params.get("enhance_scale")
    if scale is not None:
        said["enhance_scale"] = f"{float(scale):g}x"
    steps = params.get("enhance_steps")
    if steps is not None:
        said["enhance_steps"] = str(steps)
    denoise = params.get("enhance_denoise")
    if denoise is not None:
        said["enhance_denoise"] = f"{float(denoise):g}"
    checkpoint = params.get("checkpoint")
    if checkpoint and checkpoint != MATCH_SOURCE_MODEL:
        said["checkpoint"] = model_title(checkpoint)
    upscaler = params.get("upscale_model")
    if upscaler:
        said["upscale_model"] = model_title(upscaler)
    return said
