from __future__ import annotations

from origenerator.media import MediaType
from origenerator.workflows.base import (
    GENTLE_ENHANCE_DENOISE,
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
from origenerator.workflows.model_arch import FLUX
from origenerator.workflows.model_dropdowns import model_dropdown
from origenerator.workflows.parts import NodeRefs
from origenerator.workflows.prompt_readers import T5


class FluxT2iUpscaledWorkflow(WorkflowTemplate):
    """Flux is guidance-distilled: it samples at a cfg of 1 with an empty negative, and FluxGuidance is its prompt strength.

    The ComfyUI graph this follows also carried a VRGDG_LLM_Multi prompt-enhancer node, which fed nothing and needs a custom node and an API key.
    """
    name = "flux_t2i_upscaled"
    version = "v002"
    display_name = "Flux T2I"
    output_type = MediaType.IMAGE
    model_keys = ("unet",)
    lora_keys = LORA_KEYS
    text_reader = T5
    loras_keyed_only_when_named = LORA_KEYS[1:]
    redraw_model_key = "unet"
    redraw_keys = ("unet", "clip_name1", "clip_name2", "vae", "guidance", "cfg", "sampler_name",
                   "scheduler", *LORA_KEYS, *map(strength_key_of, LORA_KEYS))
    output_node_id = "12"
    base_output_node_id = "17"

    def default_params(self) -> dict:
        return {
            "positive_prompt": "",
            "negative_prompt": "",
            "seed": 0,
            "steps": 20,
            "cfg": 1.0,
            "guidance": 4.5,
            "width": 720,
            "height": 1280,
            "batch_size": 1,
            "sampler_name": "euler",
            "scheduler": "simple",
            "denoise": 1.0,
            "unet": "ultrarealFineTune_v4_fp16.gguf",
            **lora_defaults(LORA_KEYS),
            "clip_name1": "clip_l.safetensors",
            "clip_name2": "t5xxl_fp16.safetensors",
            "vae": "ae.safetensors",
            "upscale_model": "RealESRGAN_x4.pth",
            "enhance": False,
            "enhance_scale": 2.0,
            "enhance_steps": 20,
            "enhance_denoise": GENTLE_ENHANCE_DENOISE,
            "filename_prefix": "image/flux_t2i_upscaled",
        }

    def param_definitions(self) -> list[ParamDef]:
        # ComfyUI keeps GGUF Flux models under diffusion_models beside the WAN UNETs and others.
        defaults = self.default_params()
        return [
            ParamDef("positive_prompt", "Positive Prompt", ParamType.STR, defaults["positive_prompt"], multiline=True),
            model_dropdown("unet", "Model", defaults["unet"], "diffusion_models",
                         accepts=(FLUX,)),
            *lora_rows(defaults, LORA_KEYS, accepts=(FLUX,)),
            ParamDef("seed", "Seed", ParamType.SEED, defaults["seed"]),
            ParamDef("width", "Width", ParamType.INT, defaults["width"], min_val=64, max_val=4096, step=16),
            ParamDef("height", "Height", ParamType.INT, defaults["height"], min_val=64, max_val=4096, step=16),
            ParamDef("steps", "Steps", ParamType.INT, defaults["steps"], min_val=1, max_val=100, good=(20, 30)),
            ParamDef("guidance", "Prompt Strength", ParamType.FLOAT, defaults["guidance"],
                     min_val=0.0, max_val=20.0, step=0.1, good=(2.5, 4.5)),
            ParamDef("enhance", "Enhance (upscale + re-sample)", ParamType.BOOL, defaults["enhance"]),
            ParamDef("enhance_scale", "Upscale Factor", ParamType.FLOAT, defaults["enhance_scale"],
                     min_val=1.0, max_val=4.0, step=0.25, good=(1.5, 2.0)),
            ParamDef("enhance_steps", "Enhance Steps", ParamType.INT, defaults["enhance_steps"], min_val=1, max_val=100, good=(15, 25)),
            ParamDef("enhance_denoise", "Enhance Redraw Amount", ParamType.FLOAT, defaults["enhance_denoise"],
                     min_val=0.0, max_val=1.0, step=0.05, good=(0.1, 0.2)),
        ]

    def _model_nodes(self, params: dict, prefix: str = "", lora_id: str = "13"):
        loras = self.lora_chain(f"{prefix}{lora_id}", [f"{prefix}1", 0],
                                picked_loras(params, LORA_KEYS), clip_ref=[f"{prefix}2", 0])
        return {
            f"{prefix}1": {
                "class_type": "UnetLoaderGGUF",
                "inputs": {"unet_name": params["unet"]},
            },
            f"{prefix}2": {
                "class_type": "DualCLIPLoader",
                "inputs": {
                    "clip_name1": params["clip_name1"],
                    "clip_name2": params["clip_name2"],
                    "type": "flux",
                    "device": "default",
                },
            },
            f"{prefix}3": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": params["vae"]},
            },
            **loras.nodes,
        }, loras

    def redraw_refs(self, params: dict, image_ref: list, positive: str,
                    negative: str) -> tuple[dict, NodeRefs]:
        prefix = SOURCE_MODEL_PREFIX
        nodes, loras = self._model_nodes(params, prefix)
        positive_id, guided_id, negative_id = f"{prefix}positive", f"{prefix}guided", f"{prefix}negative"
        return {
            **nodes,
            **prompt_conditioning(positive_id, loras.clip_ref, positive),
            guided_id: {
                "class_type": "FluxGuidance",
                "inputs": {"conditioning": [positive_id, 0], "guidance": params["guidance"]},
            },
            **prompt_conditioning(negative_id, loras.clip_ref, negative),
        }, NodeRefs(image=image_ref, model=loras.model, positive=[guided_id, 0],
                    negative=[negative_id, 0], vae=[f"{prefix}3", 0], clip_ref=loras.clip_ref)

    def build_api_payload(self, params: dict) -> dict:
        model_nodes, loras = self._model_nodes(params)
        model_ref, clip_ref = loras.model, loras.clip_ref
        if params.get("enhance"):
            enhanced = self.enhance_image_nodes(
                NodeRefs(image=["9", 0], model=model_ref, positive=["5", 0],
                         negative=["6", 0], vae=["3", 0]),
                params,
            )
            tail, saved_ref, upscaled_ref = enhanced.nodes, enhanced.image, enhanced.upscaled
        else:
            tail = {
                "10": {
                    "class_type": "UpscaleModelLoader",
                    "inputs": {"model_name": params["upscale_model"]},
                },
                "11": {
                    "class_type": "ImageUpscaleWithModel",
                    "inputs": {"upscale_model": ["10", 0], "image": ["9", 0]},
                },
            }
            saved_ref = upscaled_ref = ["11", 0]
        return {
            **model_nodes,
            "4": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": clip_ref, "text": params["positive_prompt"]},
            },
            "5": {
                "class_type": "FluxGuidance",
                "inputs": {"conditioning": ["4", 0], "guidance": params["guidance"]},
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": clip_ref, "text": params["negative_prompt"]},
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
                    "denoise": params["denoise"],
                },
            },
            "9": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["8", 0], "vae": ["3", 0]},
            },
            **tail,
            "12": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": saved_ref,
                    "filename_prefix": params["filename_prefix"],
                },
            },
            **self.base_save_node(self.base_output_node_id, upscaled_ref, params),
        }
