from __future__ import annotations

from origenerator.workflows.base import ParamDef, ParamType
from origenerator.workflows.model_files import list_lora_files


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
