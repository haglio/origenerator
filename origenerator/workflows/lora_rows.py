from __future__ import annotations

from origenerator.workflows.base import ParamDef, ParamType
from origenerator.workflows.model_files import is_no_lora, list_lora_files


def strength_key_of(lora_key: str) -> str:
    return "lora_strength" + lora_key.removeprefix("lora")


def picked_loras(params: dict, keys) -> list[tuple[str, float]]:
    return [(params[key], params[strength_key_of(key)]) for key in keys
            if not is_no_lora(params.get(key))]


def lora_strength(key: str, default: float, label: str = "") -> ParamDef:
    return ParamDef(key, f"LoRA Strength{label}", ParamType.FLOAT, default,
                    min_val=0.0, max_val=2.0, step=0.05, good=(0.6, 1.2))


def lora_choice(defaults: dict, key: str, strength_key: str, *, accepts,
                expert: str | None = None, label: str = "") -> list[ParamDef]:
    return [
        ParamDef(key, f"LoRA{label}", ParamType.COMBO, defaults[key],
                 options=list_lora_files([defaults[key]], accepts=accepts, expert=expert)),
        lora_strength(strength_key, defaults[strength_key], label),
    ]
