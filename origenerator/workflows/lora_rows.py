from __future__ import annotations

from origenerator.workflows.base import ParamDef, ParamType
from origenerator.workflows.model_files import NO_LORA, is_no_lora, list_lora_files

_ROWS = 3


def numbered_lora_keys(suffix: str = "") -> tuple[str, ...]:
    first = f"lora{suffix}"
    return (first, *(f"{first}_{number}" for number in range(2, _ROWS + 1)))


LORA_KEYS = numbered_lora_keys()


def lora_defaults(keys) -> dict:
    defaults: dict = {}
    for key in keys:
        defaults.update({key: NO_LORA, strength_key_of(key): 1.0})
    return defaults


def strength_key_of(lora_key: str) -> str:
    return "lora_strength" + lora_key.removeprefix("lora")


def keys_with_strengths(keys) -> tuple[str, ...]:
    return tuple(name for key in keys for name in (key, strength_key_of(key)))


def picked_loras(params: dict, keys) -> list[tuple[str, float]]:
    return [(params[key], params[strength_key_of(key)]) for key in keys
            if not is_no_lora(params.get(key))]


def lora_strength(key: str, default: float, label: str = "") -> ParamDef:
    return ParamDef(key, f"LoRA Strength{label}", ParamType.FLOAT, default,
                    min_val=0.0, max_val=2.0, step=0.05, good=(0.6, 1.2))


def lora_rows(defaults: dict, keys, *, accepts, expert: str | None = None,
              qualifier: str = "") -> list[ParamDef]:
    rows: list[ParamDef] = []
    for number, key in enumerate(keys, start=1):
        label = _row_label(number, len(keys), qualifier)
        rows += [
            ParamDef(key, f"LoRA{label}", ParamType.COMBO, defaults[key],
                     options=list_lora_files([defaults[key]], accepts=accepts, expert=expert)),
            lora_strength(strength_key_of(key), defaults[strength_key_of(key)], label),
        ]
    return rows


def _row_label(number: int, count: int, qualifier: str) -> str:
    return f" {number}{qualifier}" if count > 1 else qualifier
