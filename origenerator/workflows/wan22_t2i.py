from __future__ import annotations

from origenerator.media import MediaType
from origenerator.workflows.base import ParamDef, ParamType, WorkflowTemplate
from origenerator.workflows.prompt_readers import UMT5
from origenerator.workflows.wan_experts import wan_expert_shift_param


class Wan22T2iWorkflow(WorkflowTemplate):
    name = "wan22_t2i"
    version = "v002"
    display_name = "WAN 2.2 T2I"
    output_type = MediaType.IMAGE
    model_keys = ("unet_high", "unet_low")
    text_reader = UMT5
    extra_enhance_keys = ("upscale_model",)
    output_node_id = "14"
    base_output_node_id = "21"

    def default_params(self) -> dict:
        return {
            "positive_prompt": "",
            "negative_prompt": "",
            "noise_seed": 0,
            "seed": 0,
            "width": 1088,
            "height": 1920,
            "length": 5,
            "batch_size": 1,
            "steps": 20,
            "cfg": 3.5,
            "sampler_name": "euler",
            "scheduler": "simple",
            "shift_high": 8.0,
            "shift_low": 8.0,
            "enhance": False,
            "upscale_model": "4xUltrasharp_4xUltrasharpV10.pt",
            "enhance_scale": 2.0,
            "enhance_steps": 20,
            "enhance_denoise": 0.15,
            "filename_prefix": "image/wan22_t2i",
            "clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
            "vae_name": "wan_2.1_vae.safetensors",
            "unet_high": "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors",
            "unet_low": "wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors",
        }

    def param_definitions(self) -> list[ParamDef]:
        defaults = self.default_params()
        return [
            ParamDef("positive_prompt", "Positive Prompt", ParamType.STR, defaults["positive_prompt"], multiline=True),
            ParamDef("negative_prompt", "Negative Prompt", ParamType.STR, defaults["negative_prompt"], multiline=True),
            ParamDef("noise_seed", "Seed", ParamType.SEED, defaults["noise_seed"]),
            ParamDef("width", "Width", ParamType.INT, defaults["width"], min_val=64, max_val=2048, step=16),
            ParamDef("height", "Height", ParamType.INT, defaults["height"], min_val=64, max_val=2048, step=16),
            ParamDef("steps", "Steps", ParamType.INT, defaults["steps"], min_val=1, max_val=50, good=(20, 30)),
            ParamDef("cfg", "Prompt Strength", ParamType.FLOAT, defaults["cfg"], min_val=0.0, max_val=30.0, step=0.1, good=(3, 5)),
            wan_expert_shift_param(defaults),
            ParamDef("enhance", "Enhance (upscale + re-sample)", ParamType.BOOL, defaults["enhance"]),
            ParamDef("enhance_scale", "Upscale Factor", ParamType.FLOAT, defaults["enhance_scale"],
                     min_val=1.0, max_val=4.0, step=0.25, good=(1.5, 2.0)),
            ParamDef("enhance_steps", "Enhance Steps", ParamType.INT, defaults["enhance_steps"], min_val=1, max_val=100, good=(15, 25)),
            ParamDef("enhance_denoise", "Enhance Redraw Amount", ParamType.FLOAT, defaults["enhance_denoise"],
                     min_val=0.0, max_val=1.0, step=0.05, good=(0.1, 0.2)),
        ]

    def build_api_payload(self, params: dict) -> dict:
        half_steps = params["steps"] // 2
        enhance_nodes: dict = {}
        enhanced_ref = ["13", 0]
        if params.get("enhance"):
            tail = self.enhance_image_nodes(
                image_ref=["13", 0], model_ref=["6", 0],
                positive_ref=["7", 0], negative_ref=["8", 0], vae_ref=["2", 0],
                params=params,
            )
            enhance_nodes, enhanced_ref = tail.nodes, tail.image
        return {
            "1": {
                "class_type": "CLIPLoader",
                "inputs": {
                    "clip_name": params["clip_name"],
                    "type": "wan",
                    "device": "default",
                },
            },
            "2": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": params["vae_name"]},
            },
            "3": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": params["unet_high"], "weight_dtype": "default"},
            },
            "4": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": params["unet_low"], "weight_dtype": "default"},
            },
            "5": {
                "class_type": "ModelSamplingSD3",
                "inputs": {"model": ["3", 0], "shift": params["shift_high"]},
            },
            "6": {
                "class_type": "ModelSamplingSD3",
                "inputs": {"model": ["4", 0], "shift": params["shift_low"]},
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["1", 0], "text": params["positive_prompt"]},
            },
            "8": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["1", 0], "text": params["negative_prompt"]},
            },
            "9": {
                "class_type": "EmptyHunyuanLatentVideo",
                "inputs": {
                    "width": params["width"],
                    "height": params["height"],
                    "length": params["length"],
                    "batch_size": params["batch_size"],
                },
            },
            "10": {
                "class_type": "KSamplerAdvanced",
                "inputs": {
                    "model": ["5", 0],
                    "positive": ["7", 0],
                    "negative": ["8", 0],
                    "latent_image": ["9", 0],
                    "add_noise": "enable",
                    "noise_seed": params["noise_seed"],
                    "steps": params["steps"],
                    "cfg": params["cfg"],
                    "sampler_name": params["sampler_name"],
                    "scheduler": params["scheduler"],
                    "start_at_step": 0,
                    "end_at_step": half_steps,
                    "return_with_leftover_noise": "enable",
                },
            },
            "11": {
                "class_type": "KSamplerAdvanced",
                "inputs": {
                    "model": ["6", 0],
                    "positive": ["7", 0],
                    "negative": ["8", 0],
                    "latent_image": ["10", 0],
                    "add_noise": "disable",
                    "noise_seed": params["seed"],
                    "steps": params["steps"],
                    "cfg": params["cfg"],
                    "sampler_name": params["sampler_name"],
                    "scheduler": params["scheduler"],
                    "start_at_step": half_steps,
                    "end_at_step": 10000,
                    "return_with_leftover_noise": "disable",
                },
            },
            "12": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["11", 0], "vae": ["2", 0]},
            },
            "13": {
                "class_type": "ImageFromBatch",
                "inputs": {"image": ["12", 0], "batch_index": 0, "length": 1},
            },
            "14": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": enhanced_ref,
                    "filename_prefix": params["filename_prefix"],
                },
            },
            **enhance_nodes,
            **self.base_save_node(self.base_output_node_id, ["13", 0], params),
        }
