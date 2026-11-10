from __future__ import annotations

from origenerator.media import MediaType
from origenerator.workflows.base import (
    SOURCE_MODEL_PREFIX,
    ParamDef,
    ParamType,
    WorkflowTemplate,
    prompt_conditioning,
)
from origenerator.workflows.lora_rows import (
    LORA_KEYS,
    lora_defaults,
    lora_rows,
    picked_loras,
    strength_key_of,
)
from origenerator.workflows.model_arch import KREA2
from origenerator.workflows.model_dropdowns import model_dropdown
from origenerator.workflows.parts import NodeRefs
from origenerator.workflows.prompt_readers import QWEN3VL


def _nothing_to_avoid(positive_ref: list) -> dict:
    return {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": positive_ref}}


def _negative_conditioning(negative_prompt: str) -> dict:
    if negative_prompt:
        return {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": negative_prompt}}
    return _nothing_to_avoid(["5", 0])


def _diffusion_model_loader(unet: str) -> dict:
    if unet.endswith(".gguf"):
        return {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": unet}}
    return {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}}


class Krea2T2iWorkflow(WorkflowTemplate):
    name = "krea2_t2i"
    version = "v002"
    display_name = "Krea 2 T2I"
    output_type = MediaType.IMAGE
    model_keys = ("unet",)
    lora_keys = LORA_KEYS
    text_reader = QWEN3VL
    prompts_take_weights = False
    loras_keyed_only_when_named = LORA_KEYS[1:]
    extra_enhance_keys = ("upscale_model",)
    redraw_model_key = "unet"
    redraw_keys = ("unet", "clip_name", "vae", "cfg", "sampler_name", "scheduler", *LORA_KEYS,
                   *map(strength_key_of, LORA_KEYS))
    output_node_id = "10"
    base_output_node_id = "11"

    def default_params(self) -> dict:
        return {
            "positive_prompt": "",
            "negative_prompt": "",
            "seed": 0,
            "steps": 8,
            "cfg": 1.0,
            "width": 720,
            "height": 1280,
            "batch_size": 1,
            "sampler_name": "euler",
            "scheduler": "simple",
            "unet": "krea2_turbo_fp8_scaled.safetensors",
            **lora_defaults(LORA_KEYS),
            "clip_name": "qwen3vl_4b_fp8_scaled.safetensors",
            "vae": "qwen_image_vae.safetensors",
            "enhance": False,
            "upscale_model": "4xFaceUpDAT.pth",
            "enhance_scale": 2.0,
            "enhance_steps": 20,
            "enhance_denoise": 0.15,
            "filename_prefix": "image/krea2_t2i",
        }

    def param_definitions(self) -> list[ParamDef]:
        defaults = self.default_params()
        return [
            ParamDef("positive_prompt", "Positive Prompt", ParamType.STR, defaults["positive_prompt"], multiline=True),
            ParamDef("negative_prompt", "Negative Prompt", ParamType.STR, defaults["negative_prompt"], multiline=True),
            model_dropdown("unet", "Model", defaults["unet"], "diffusion_models",
                         accepts=(KREA2,)),
            *lora_rows(defaults, LORA_KEYS, accepts=(KREA2,), beside_model="unet"),
            ParamDef("seed", "Seed", ParamType.SEED, defaults["seed"]),
            ParamDef("width", "Width", ParamType.INT, defaults["width"], min_val=512, max_val=2048, step=16),
            ParamDef("height", "Height", ParamType.INT, defaults["height"], min_val=512, max_val=2048, step=16),
            ParamDef("steps", "Steps", ParamType.INT, defaults["steps"], min_val=1, max_val=100, good=(8, 12)),
            ParamDef("cfg", "Prompt Strength", ParamType.FLOAT, defaults["cfg"], min_val=0.0, max_val=10.0, step=0.1, good=(1.0, 3.5)),
            ParamDef("enhance", "Enhance (upscale + re-sample)", ParamType.BOOL, defaults["enhance"]),
            ParamDef("enhance_scale", "Upscale Factor", ParamType.FLOAT, defaults["enhance_scale"],
                     min_val=1.0, max_val=4.0, step=0.25, good=(1.5, 2.0)),
            ParamDef("enhance_steps", "Enhance Steps", ParamType.INT, defaults["enhance_steps"], min_val=1, max_val=100, good=(15, 25)),
            ParamDef("enhance_denoise", "Enhance Redraw Amount", ParamType.FLOAT, defaults["enhance_denoise"],
                     min_val=0.0, max_val=1.0, step=0.05, good=(0.1, 0.2)),
        ]

    def _model_nodes(self, params: dict, prefix: str = "") -> tuple[dict, list]:
        loras = self.lora_chain(f"{prefix}4", [f"{prefix}1", 0], picked_loras(params, LORA_KEYS))
        return {
            f"{prefix}1": _diffusion_model_loader(params["unet"]),
            f"{prefix}2": {
                "class_type": "CLIPLoader",
                "inputs": {"clip_name": params["clip_name"], "type": "krea2", "device": "default"},
            },
            f"{prefix}3": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": params["vae"]},
            },
            **loras.nodes,
        }, loras.model

    def redraw_refs(self, params: dict, image_ref: list, positive: str,
                    negative: str) -> tuple[dict, NodeRefs]:
        prefix = SOURCE_MODEL_PREFIX
        nodes, model_ref = self._model_nodes(params, prefix)
        clip_ref = [f"{prefix}2", 0]
        positive_ref = [f"{prefix}positive", 0]
        negative_id = f"{prefix}negative"
        return {
            **nodes,
            **prompt_conditioning(positive_ref[0], clip_ref, positive),
            **(prompt_conditioning(negative_id, clip_ref, negative) if negative
               else {negative_id: _nothing_to_avoid(positive_ref)}),
        }, NodeRefs(image=image_ref, model=model_ref, positive=positive_ref,
                    negative=[negative_id, 0], vae=[f"{prefix}3", 0], clip_ref=clip_ref)

    def build_api_payload(self, params: dict) -> dict:
        model_nodes, model_ref = self._model_nodes(params)
        tail: dict = {}
        saved_ref = ["9", 0]
        if params.get("enhance"):
            enhanced = self.enhance_image_nodes(
                NodeRefs(image=["9", 0], model=model_ref, positive=["5", 0],
                         negative=["6", 0], vae=["3", 0]),
                params,
            )
            tail, saved_ref = enhanced.nodes, enhanced.image
        return {
            **model_nodes,
            "5": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["2", 0], "text": params["positive_prompt"]},
            },
            "6": _negative_conditioning(params["negative_prompt"]),
            "7": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "width": params["width"],
                    "height": params["height"],
                    "batch_size": params["batch_size"],
                },
            },
            "8": {
                "class_type": "KSampler",
                "inputs": {
                    "model": model_ref,
                    "positive": ["5", 0],
                    "negative": ["6", 0],
                    "latent_image": ["7", 0],
                    "seed": params["seed"],
                    "steps": params["steps"],
                    "cfg": params["cfg"],
                    "sampler_name": params["sampler_name"],
                    "scheduler": params["scheduler"],
                    "denoise": 1.0,
                },
            },
            "9": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["8", 0], "vae": ["3", 0]},
            },
            **tail,
            "10": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": saved_ref,
                    "filename_prefix": params["filename_prefix"],
                },
            },
            **self.base_save_node(self.base_output_node_id, ["9", 0], params),
        }
