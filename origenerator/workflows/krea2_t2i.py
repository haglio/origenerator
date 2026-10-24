from __future__ import annotations

from origenerator.media import MediaType
from origenerator.workflows.base import ParamDef, ParamType, WorkflowTemplate
from origenerator.workflows.lora_choice import lora_choice
from origenerator.workflows.model_arch import KREA2
from origenerator.workflows.model_files import NO_LORA, list_model_files


def _diffusion_model_loader(unet: str) -> dict:
    if unet.endswith(".gguf"):
        return {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": unet}}
    return {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}}


class Krea2T2iWorkflow(WorkflowTemplate):
    name = "krea2_t2i"
    version = "v001"
    display_name = "Krea 2 T2I"
    output_type = MediaType.IMAGE
    model_keys = ("unet",)
    lora_keys = ("lora",)
    extra_enhance_keys = ("upscale_model",)
    output_node_id = "10"
    base_output_node_id = "11"

    def default_params(self) -> dict:
        return {
            "positive_prompt": "",
            "seed": 0,
            "steps": 8,
            "cfg": 1.0,
            "width": 720,
            "height": 1280,
            "batch_size": 1,
            "sampler_name": "euler",
            "scheduler": "simple",
            "unet": "krea2_turbo_fp8_scaled.safetensors",
            "lora": NO_LORA,
            "lora_strength": 1.0,
            "clip_name": "qwen3vl_4b_fp8_scaled.safetensors",
            "vae": "qwen_image_vae.safetensors",
            "enhance": False,
            "upscale_model": "4xUltrasharp_4xUltrasharpV10.pt",
            "enhance_scale": 2.0,
            "enhance_steps": 20,
            "enhance_denoise": 0.15,
            "filename_prefix": "image/krea2_t2i",
        }

    def param_definitions(self) -> list[ParamDef]:
        defaults = self.default_params()
        unets = list_model_files("diffusion_models", [defaults["unet"]], accepts=(KREA2,))
        return [
            ParamDef("positive_prompt", "Positive Prompt", ParamType.STR, defaults["positive_prompt"], multiline=True),
            ParamDef("unet", "Model", ParamType.COMBO, defaults["unet"], options=unets),
            *lora_choice(defaults, "lora", "lora_strength", accepts=(KREA2,)),
            ParamDef("seed", "Seed", ParamType.SEED, defaults["seed"]),
            ParamDef("width", "Width", ParamType.INT, defaults["width"], min_val=512, max_val=2048, step=16),
            ParamDef("height", "Height", ParamType.INT, defaults["height"], min_val=512, max_val=2048, step=16),
            ParamDef("steps", "Steps", ParamType.INT, defaults["steps"], min_val=1, max_val=50, good=(8, 12)),
            ParamDef("enhance", "Enhance (upscale + re-sample)", ParamType.BOOL, defaults["enhance"]),
            ParamDef("enhance_scale", "Upscale Factor", ParamType.FLOAT, defaults["enhance_scale"],
                     min_val=1.0, max_val=4.0, step=0.25, good=(1.5, 2.0)),
            ParamDef("enhance_steps", "Enhance Steps", ParamType.INT, defaults["enhance_steps"], min_val=1, max_val=100, good=(15, 25)),
            ParamDef("enhance_denoise", "Enhance Redraw Amount", ParamType.FLOAT, defaults["enhance_denoise"],
                     min_val=0.0, max_val=1.0, step=0.05, good=(0.1, 0.2)),
        ]

    def build_api_payload(self, params: dict) -> dict:
        lora, model_ref = self.lora_model_input(
            "4", ["1", 0], params["lora"], params["lora_strength"])
        tail: dict = {}
        saved_ref = ["9", 0]
        if params.get("enhance"):
            enhanced = self.enhance_image_nodes(
                image_ref=["9", 0], model_ref=model_ref,
                positive_ref=["5", 0], negative_ref=["6", 0], vae_ref=["3", 0],
                params=params,
            )
            tail, saved_ref = enhanced.nodes, enhanced.image
        return {
            "1": _diffusion_model_loader(params["unet"]),
            "2": {
                "class_type": "CLIPLoader",
                "inputs": {"clip_name": params["clip_name"], "type": "krea2", "device": "default"},
            },
            "3": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": params["vae"]},
            },
            **lora,
            "5": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["2", 0], "text": params["positive_prompt"]},
            },
            "6": {
                "class_type": "ConditioningZeroOut",
                "inputs": {"conditioning": ["5", 0]},
            },
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
