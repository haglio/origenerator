"""The WAN 2.2 expert pair, as the form rows that pick it.

WAN 2.2 samples in two stages against two halves of one model — a high-noise
expert and a low-noise one — and a slot must offer only its own half: a file
whose name claims the other is the one pick that is certainly wrong there.
That convention is what these rows encode, and it lives here rather than in
each workflow because every workflow sampling in those two stages, WAN 2.1's
motion-tracked one included, has to agree about it, and a convention spelled
out twice is a convention that can be changed in one place only.

Two functions rather than one, because the order the rows come back in is the
order the Generate form shows and the gallery info pane groups by: the models
sit together and the LoRAs sit together, and one workflow has a third model
picker to slot in between them.
"""
from __future__ import annotations

from origenerator.workflows.base import ParamDef, ParamType
from origenerator.workflows.lora_choice import lora_choice
from origenerator.workflows.model_arch import WAN
from origenerator.workflows.model_files import list_model_files


def wan_expert_model_params(defaults: dict) -> list[ParamDef]:
    """The high/low UNET pickers, each offering only WAN and only its own
    expert. Names claiming neither half stay in both, since nothing inside a
    WAN 2.2 file distinguishes the two."""
    return [
        ParamDef("unet_high", "Model (First Pass)", ParamType.COMBO, defaults["unet_high"],
                 options=list_model_files("diffusion_models", [defaults["unet_high"]],
                                          accepts=(WAN,), expert="high")),
        ParamDef("unet_low", "Model (Second Pass)", ParamType.COMBO, defaults["unet_low"],
                 options=list_model_files("diffusion_models", [defaults["unet_low"]],
                                          accepts=(WAN,), expert="low")),
    ]


def wan_expert_shift_param(defaults: dict) -> ParamDef:
    """One Composition Focus for both passes: two values would hand the
    picture over at mismatched noise."""
    return ParamDef("shift_high", "Composition Focus", ParamType.FLOAT, defaults["shift_high"],
                    min_val=0.0, max_val=20.0, step=0.5, also_sets=("shift_low",), good=(5, 12))


def wan_expert_lora_params(defaults: dict) -> list[ParamDef]:
    """The high/low LoRA pickers, each directly above its own strength — the
    same expert filter as the models, over the LoRA folder."""
    return [
        *lora_choice(defaults, "lora_high", "lora_strength_high",
                     accepts=(WAN,), expert="high", label=" (First Pass)"),
        *lora_choice(defaults, "lora_low", "lora_strength_low",
                     accepts=(WAN,), expert="low", label=" (Second Pass)"),
    ]
