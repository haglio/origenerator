from origenerator.workflows.base import ParamDef, WorkflowTemplate
from origenerator.workflows.model_files import list_model_files

_DEFAULT_UNET = "ultrarealFineTune_v4_fp16.gguf"


class FluxT2iUpscaledWorkflow(WorkflowTemplate):
    """Flux text-to-image on a GGUF-quantized UNET, with a RealESRGAN upscale.

    Flux is guidance-distilled: it samples at cfg 1.0 with an empty negative, so
    the meaningful "prompt strength" knob is ``FluxGuidance``, not cfg. The GGUF
    diffusion model (loaded by ``UnetLoaderGGUF``) is what a user swaps between
    — three different Flux checkpoints in the imports this reproduces — so it's
    the model the gallery groups by. The decoded image is passed through an
    ``ImageUpscaleWithModel`` (RealESRGAN x4) before ``SaveImage``, which is what
    the ``flux_t2i_upscaled`` filename prefix records.

    The saved graph also carried a stray ``VRGDG_LLM_Multi`` prompt-enhancer node
    hanging off the side, unconnected to the sampling path; it isn't part of the
    pipeline (and needs a custom node plus an API key), so it's left out here.
    """

    name = "flux_t2i_upscaled"
    version = "v001"
    display_name = "Flux Text-to-Image (Upscaled)"
    output_type = "image"
    model_keys = ("unet",)
    output_node_id = "12"

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
            "unet": _DEFAULT_UNET,
            "clip_name1": "clip_l.safetensors",
            "clip_name2": "t5xxl_fp16.safetensors",
            "vae": "ae.safetensors",
            "upscale_model": "RealESRGAN_x4.pth",
            "filename_prefix": "image/flux_t2i_upscaled",
        }

    def param_definitions(self) -> list[ParamDef]:
        # GGUF Flux models live under diffusion_models, alongside the WAN UNETs.
        unets = list_model_files("diffusion_models", [_DEFAULT_UNET])
        return [
            ParamDef("positive_prompt", "Positive Prompt", "str", "", multiline=True),
            ParamDef("unet", "Model", "combo", _DEFAULT_UNET, options=unets),
            ParamDef("seed", "Seed", "seed", 0),
            ParamDef("width", "Width", "int", 720, min_val=64, max_val=4096, step=16),
            ParamDef("height", "Height", "int", 1280, min_val=64, max_val=4096, step=16),
            ParamDef("steps", "Steps", "int", 20, min_val=1, max_val=100),
            ParamDef("guidance", "Guidance (Flux)", "float", 4.5,
                     min_val=0.0, max_val=20.0, step=0.1),
            ParamDef("filename_prefix", "Output Prefix", "str", "image/flux_t2i_upscaled"),
        ]

    def build_api_payload(self, params: dict) -> dict:
        return {
            "1": {
                "class_type": "UnetLoaderGGUF",
                "inputs": {"unet_name": params["unet"]},
            },
            "2": {
                "class_type": "DualCLIPLoader",
                "inputs": {
                    "clip_name1": params["clip_name1"],
                    "clip_name2": params["clip_name2"],
                    "type": "flux",
                    "device": "default",
                },
            },
            "3": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": params["vae"]},
            },
            "4": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["2", 0], "text": params["positive_prompt"]},
            },
            "5": {
                "class_type": "FluxGuidance",
                "inputs": {"conditioning": ["4", 0], "guidance": params["guidance"]},
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["2", 0], "text": params["negative_prompt"]},
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
                    "model": ["1", 0],
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
            "10": {
                "class_type": "UpscaleModelLoader",
                "inputs": {"model_name": params["upscale_model"]},
            },
            "11": {
                "class_type": "ImageUpscaleWithModel",
                "inputs": {"upscale_model": ["10", 0], "image": ["9", 0]},
            },
            "12": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": ["11", 0],
                    "filename_prefix": params["filename_prefix"],
                },
            },
        }
