from __future__ import annotations

from origenerator.media import MediaType
from origenerator.workflows.base import (
    ParamDef,
    ParamType,
    WorkflowTemplate,
    prompt_conditioning,
    sampler_params,
)
from origenerator.workflows.lora_rows import LORA_KEYS, lora_defaults, lora_rows, picked_loras
from origenerator.workflows.model_arch import SDXL
from origenerator.workflows.model_dropdowns import model_dropdown
from origenerator.workflows.model_files import ANY
from origenerator.workflows.parts import NodeRefs
from origenerator.workflows.prompt_readers import CLIP


class SdxlT2iWorkflow(WorkflowTemplate):
    name = "sdxl_t2i"
    version = "v004"
    display_name = "SDXL T2I"
    output_type = MediaType.IMAGE
    model_keys = ("checkpoint",)
    lora_keys = loras_keyed_only_when_named = LORA_KEYS
    text_reader = CLIP
    extra_enhance_keys = ("upscale_model",)
    output_node_id = "7"
    base_output_node_id = "15"

    def default_params(self) -> dict:
        return {
            "positive_prompt": "",
            "negative_prompt": "",
            "seed": 0,
            "steps": 50,
            "cfg": 7.5,
            "width": 1280,
            "height": 720,
            "batch_size": 1,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1.0,
            "checkpoint": "reapony_v80.safetensors",
            **lora_defaults(LORA_KEYS),
            "vae": "sdxl_vae.safetensors",
            "enhance": False,
            "upscale_model": "4xUltrasharp_4xUltrasharpV10.pt",
            "enhance_scale": 2.0,
            "enhance_steps": 20,
            "enhance_denoise": 0.15,
            "filename_prefix": "image/sdxl_t2i",
        }

    def param_definitions(self) -> list[ParamDef]:
        defaults = self.default_params()
        return [
            ParamDef("positive_prompt", "Positive Prompt", ParamType.STR, defaults["positive_prompt"], multiline=True),
            ParamDef("negative_prompt", "Negative Prompt", ParamType.STR, defaults["negative_prompt"], multiline=True),
            model_dropdown("checkpoint", "Model", defaults["checkpoint"], "checkpoints",
                         accepts=(SDXL,)),
            *lora_rows(defaults, LORA_KEYS, accepts=(SDXL,)),
            ParamDef("seed", "Seed", ParamType.SEED, defaults["seed"]),
            ParamDef("width", "Width", ParamType.INT, defaults["width"], min_val=64, max_val=4096, step=64),
            ParamDef("height", "Height", ParamType.INT, defaults["height"], min_val=64, max_val=4096, step=64),
            ParamDef("steps", "Steps", ParamType.INT, defaults["steps"], min_val=1, max_val=200, good=(25, 50)),
            ParamDef("cfg", "Prompt Strength", ParamType.FLOAT, defaults["cfg"], min_val=0.0, max_val=30.0, step=0.5, good=(3, 8)),
            *sampler_params(defaults),
            ParamDef("enhance", "Enhance (upscale + re-sample)", ParamType.BOOL, defaults["enhance"]),
            model_dropdown("upscale_model", "Upscaler", defaults["upscale_model"],
                         "upscale_models", accepts=ANY),
            ParamDef("enhance_scale", "Upscale Factor", ParamType.FLOAT, defaults["enhance_scale"],
                     min_val=1.0, max_val=4.0, step=0.25, good=(1.5, 2.0)),
            ParamDef("enhance_steps", "Enhance Steps", ParamType.INT, defaults["enhance_steps"], min_val=1, max_val=100, good=(15, 25)),
            ParamDef("enhance_denoise", "Enhance Redraw Amount", ParamType.FLOAT, defaults["enhance_denoise"],
                     min_val=0.0, max_val=1.0, step=0.05, good=(0.1, 0.2)),
        ]

    def build_api_payload(self, params: dict) -> dict:
        loras = self.lora_chain("16", ["1", 0], picked_loras(params, LORA_KEYS), clip_ref=["1", 1])
        enhance_nodes: dict = {}
        enhanced_ref = ["6", 0]
        if params.get("enhance"):
            tail = self.enhance_image_nodes(
                NodeRefs(image=["6", 0], model=loras.model, positive=["2", 0],
                         negative=["3", 0], vae=["8", 0]),
                params,
            )
            enhance_nodes, enhanced_ref = tail.nodes, tail.image
        return {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": params["checkpoint"]},
            },
            **loras.nodes,
            **prompt_conditioning("2", loras.clip_ref, params["positive_prompt"]),
            **prompt_conditioning("3", loras.clip_ref, params["negative_prompt"]),
            "4": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "width": params["width"],
                    "height": params["height"],
                    "batch_size": params["batch_size"],
                },
            },
            "5": {
                "class_type": "KSampler",
                "inputs": {
                    "model": loras.model,
                    "positive": ["2", 0],
                    "negative": ["3", 0],
                    "latent_image": ["4", 0],
                    "seed": params["seed"],
                    "steps": params["steps"],
                    "cfg": params["cfg"],
                    "sampler_name": params["sampler_name"],
                    "scheduler": params["scheduler"],
                    "denoise": 1.0,
                },
            },
            "6": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["5", 0], "vae": ["8", 0]},
            },
            "7": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": enhanced_ref,
                    "filename_prefix": params["filename_prefix"],
                },
            },
            "8": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": params["vae"]},
            },
            **enhance_nodes,
            **self.base_save_node(self.base_output_node_id, ["6", 0], params),
        }
