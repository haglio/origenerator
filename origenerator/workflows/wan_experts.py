"""ComfyUI samples WAN 2.2 in two stages against a high-noise and a low-noise expert half of one model, so a dropdown offers only its own half and one shift serves both passes."""
from __future__ import annotations

from origenerator.workflows.base import ParamDef, ParamType
from origenerator.workflows.lora_rows import lora_defaults, lora_rows, numbered_lora_keys
from origenerator.workflows.model_arch import WAN
from origenerator.workflows.model_dropdowns import model_dropdown

FIRST_PASS_LORA_KEYS = numbered_lora_keys("_high")
SECOND_PASS_LORA_KEYS = numbered_lora_keys("_low")
LORA_KEYS_OF_BOTH_PASSES = (*FIRST_PASS_LORA_KEYS, *SECOND_PASS_LORA_KEYS)
LORAS_KEYED_ONLY_WHEN_NAMED = (*FIRST_PASS_LORA_KEYS[1:], *SECOND_PASS_LORA_KEYS[1:])


def wan_expert_lora_defaults() -> dict:
    return lora_defaults(LORAS_KEYED_ONLY_WHEN_NAMED)


def wan_expert_model_params(defaults: dict, accepts=(WAN,)) -> list[ParamDef]:
    return [
        model_dropdown("unet_high", "Model (First Pass)", defaults["unet_high"],
                     "diffusion_models", accepts=accepts, expert="high"),
        model_dropdown("unet_low", "Model (Second Pass)", defaults["unet_low"],
                     "diffusion_models", accepts=accepts, expert="low"),
    ]


def wan_expert_shift_param(defaults: dict) -> ParamDef:
    return ParamDef("shift_high", "Composition Focus", ParamType.FLOAT, defaults["shift_high"],
                    min_val=0.0, max_val=20.0, step=0.5, also_sets=("shift_low",), good=(5, 12))


def wan_expert_lora_params(defaults: dict, accepts=(WAN,)) -> list[ParamDef]:
    return [
        *lora_rows(defaults, FIRST_PASS_LORA_KEYS, accepts=accepts, expert="high",
                   qualifier=" (First Pass)"),
        *lora_rows(defaults, SECOND_PASS_LORA_KEYS, accepts=accepts, expert="low",
                   qualifier=" (Second Pass)"),
    ]
