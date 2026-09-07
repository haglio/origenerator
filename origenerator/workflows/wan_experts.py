"""The WAN 2.2 expert pair, as the form rows that pick it.

WAN 2.2 samples in two stages against two halves of one model — a high-noise
expert and a low-noise one — and a slot must offer only its own half: a file
whose name claims the other is the one pick that is certainly wrong there.
That convention is what these rows encode, and it lives here rather than in
each workflow because both workflows that run the pair have to agree about it,
and a convention spelled out twice is a convention that can be changed in one
place only.

Two functions rather than one, because the order the rows come back in is the
order the Generate form shows and the gallery info pane groups by: the models
sit together and the LoRAs sit together, and one workflow has a third model
picker to slot in between them.
"""
from __future__ import annotations

from origenerator.workflows.base import ParamDef
from origenerator.workflows.model_arch import WAN
from origenerator.workflows.model_files import list_lora_files, list_model_files


def wan_expert_model_params(defaults: dict) -> list[ParamDef]:
    """The high/low UNET pickers, each offering only WAN and only its own
    expert. Names claiming neither half stay in both, since nothing inside a
    WAN 2.2 file distinguishes the two."""
    return [
        ParamDef("unet_high", "Model (High)", "combo", defaults["unet_high"],
                 options=list_model_files("diffusion_models", [defaults["unet_high"]],
                                          accepts=(WAN,), expert="high")),
        ParamDef("unet_low", "Model (Low)", "combo", defaults["unet_low"],
                 options=list_model_files("diffusion_models", [defaults["unet_low"]],
                                          accepts=(WAN,), expert="low")),
    ]


def wan_expert_lora_params(defaults: dict) -> list[ParamDef]:
    """The high/low LoRA pickers, each directly above its own strength — the
    same expert filter as the models, over the LoRA folder."""
    return [
        ParamDef("lora_high", "LoRA (High)", "combo", defaults["lora_high"],
                 options=list_lora_files([defaults["lora_high"]],
                                         accepts=(WAN,), expert="high")),
        ParamDef("lora_strength_high", "LoRA Strength (High)", "float",
                 defaults["lora_strength_high"], min_val=0.0, max_val=2.0, step=0.05),
        ParamDef("lora_low", "LoRA (Low)", "combo", defaults["lora_low"],
                 options=list_lora_files([defaults["lora_low"]],
                                         accepts=(WAN,), expert="low")),
        ParamDef("lora_strength_low", "LoRA Strength (Low)", "float",
                 defaults["lora_strength_low"], min_val=0.0, max_val=2.0, step=0.05),
    ]
