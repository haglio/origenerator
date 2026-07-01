from origenerator.workflows.base import ParamDef, WorkflowTemplate
from origenerator.workflows.model_files import list_model_files


class Wan22I2vWorkflow(WorkflowTemplate):
    """WAN 2.2 14B image-to-video, dual-noise (high/low) sampling.

    Reproduces the ``wan22_14b_i2v_dual_noise_template`` ComfyUI graph: a single
    input image is encoded with CLIP-Vision and fed to ``WanImageToVideo``, then
    denoised by two ``KSamplerAdvanced`` passes (high-noise model for the first
    half of the steps, low-noise model for the second) and written with the
    native ``CreateVideo`` + ``SaveVideo`` nodes. The output resolution is
    derived in-graph from the input image (see :meth:`build_api_payload`): it
    keeps the image's aspect ratio at a fixed pixel budget rather than a
    hardcoded size.
    """

    name = "wan22_i2v"
    version = "v002"
    display_name = "WAN 2.2 I2V (Image-to-Video)"
    output_type = "video"
    model_keys = ("unet_high", "unet_low")
    lora_keys = ("lora_high", "lora_low")
    output_node_id = "19"

    def default_params(self) -> dict:
        return {
            "positive_prompt": "",
            "negative_prompt": "",
            "input_image": "",
            "noise_seed": 0,
            "seed": 0,
            "frame_count": 121,
            "batch_size": 1,
            "steps": 20,
            "cfg": 3.5,
            "sampler_name": "euler",
            "scheduler": "simple",
            "shift_high": 8.0,
            "shift_low": 8.0,
            "lora_strength_high": 1.0,
            "lora_strength_low": 1.0,
            "frame_rate": 24.0,
            "filename_prefix": "video/wan22_i2v",
            "clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
            "vae_name": "wan_2.1_vae.safetensors",
            "clip_vision_name": "clip_vision_h.safetensors",
            "unet_high": "split_files\\diffusion_models\\wan2.2_i2v_high_noise_14B_fp16.safetensors",
            "unet_low": "split_files\\diffusion_models\\wan2.2_i2v_low_noise_14B_fp16.safetensors",
            "lora_high": "wan22-f4c3spl4sh-100epoc-high-k3nk.safetensors",
            "lora_low": "wan22-f4c3spl4sh-154epoc-low-k3nk.safetensors",
        }

    def param_definitions(self) -> list[ParamDef]:
        defaults = self.default_params()
        models = list_model_files("diffusion_models", [defaults["unet_high"], defaults["unet_low"]])
        loras = list_model_files("loras", [defaults["lora_high"], defaults["lora_low"]])
        return [
            ParamDef("positive_prompt", "Positive Prompt", "str", "", multiline=True),
            ParamDef("negative_prompt", "Negative Prompt", "str", "", multiline=True),
            ParamDef("input_image", "Input Image", "image", ""),
            ParamDef("noise_seed", "Noise Seed (Stage 1)", "seed", 0),
            ParamDef("seed", "Seed (Stage 2)", "seed", 0),
            ParamDef("frame_count", "Frames", "int", 121, min_val=5, max_val=161, step=4),
            ParamDef("steps", "Steps", "int", 20, min_val=1, max_val=50),
            ParamDef("cfg", "CFG Scale", "float", 3.5, min_val=0.0, max_val=30.0, step=0.1),
            ParamDef("shift_high", "Shift (High)", "float", 8.0, min_val=0.0, max_val=20.0, step=0.5),
            ParamDef("shift_low", "Shift (Low)", "float", 8.0, min_val=0.0, max_val=20.0, step=0.5),
            ParamDef("unet_high", "Model (High)", "combo", defaults["unet_high"], options=models),
            ParamDef("lora_high", "LoRA (High)", "combo", defaults["lora_high"], options=loras),
            ParamDef("lora_strength_high", "LoRA Strength (High)", "float", 1.0, min_val=0.0, max_val=2.0, step=0.05),
            ParamDef("unet_low", "Model (Low)", "combo", defaults["unet_low"], options=models),
            ParamDef("lora_low", "LoRA (Low)", "combo", defaults["lora_low"], options=loras),
            ParamDef("lora_strength_low", "LoRA Strength (Low)", "float", 1.0, min_val=0.0, max_val=2.0, step=0.05),
            ParamDef("frame_rate", "Frame Rate", "float", 24.0, min_val=1.0, max_val=60.0, step=1.0),
            ParamDef("filename_prefix", "Output Prefix", "str", "video/wan22_i2v"),
        ]

    def build_api_payload(self, params: dict) -> dict:
        half_steps = params["steps"] // 2
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
                "class_type": "CLIPVisionLoader",
                "inputs": {"clip_name": params["clip_vision_name"]},
            },
            "4": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": params["unet_high"], "weight_dtype": "default"},
            },
            "5": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": params["unet_low"], "weight_dtype": "default"},
            },
            "6": {
                "class_type": "LoraLoaderModelOnly",
                "inputs": {
                    "model": ["4", 0],
                    "lora_name": params["lora_high"],
                    "strength_model": params["lora_strength_high"],
                },
            },
            "7": {
                "class_type": "LoraLoaderModelOnly",
                "inputs": {
                    "model": ["5", 0],
                    "lora_name": params["lora_low"],
                    "strength_model": params["lora_strength_low"],
                },
            },
            "8": {
                "class_type": "ModelSamplingSD3",
                "inputs": {"model": ["6", 0], "shift": params["shift_high"]},
            },
            "9": {
                "class_type": "ModelSamplingSD3",
                "inputs": {"model": ["7", 0], "shift": params["shift_low"]},
            },
            "10": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["1", 0], "text": params["positive_prompt"]},
            },
            "11": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["1", 0], "text": params["negative_prompt"]},
            },
            "12": {
                "class_type": "LoadImage",
                "inputs": {"image": params["input_image"]},
            },
            "13": {
                "class_type": "CLIPVisionEncode",
                "inputs": {
                    "clip_vision": ["3", 0],
                    "image": ["12", 0],
                    "crop": "center",
                },
            },
            # Derive the output resolution from the input image: scale it to a
            # fixed pixel budget on WAN's /16 stride (keeping aspect), then read
            # the resulting size back to drive WanImageToVideo — so a portrait or
            # widescreen still yields a proportional video without a hardcoded WxH.
            "20": {
                "class_type": "ImageScaleToTotalPixels",
                "inputs": {
                    "image": ["12", 0],
                    "upscale_method": "lanczos",
                    "megapixels": 0.4,
                    "resolution_steps": 16,
                },
            },
            "21": {
                "class_type": "GetImageSize",
                "inputs": {"image": ["20", 0]},
            },
            "14": {
                "class_type": "WanImageToVideo",
                "inputs": {
                    "positive": ["10", 0],
                    "negative": ["11", 0],
                    "vae": ["2", 0],
                    "clip_vision_output": ["13", 0],
                    "start_image": ["20", 0],
                    "width": ["21", 0],
                    "height": ["21", 1],
                    "length": params["frame_count"],
                    "batch_size": params["batch_size"],
                },
            },
            "15": {
                "class_type": "KSamplerAdvanced",
                "inputs": {
                    "model": ["8", 0],
                    "positive": ["14", 0],
                    "negative": ["14", 1],
                    "latent_image": ["14", 2],
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
            "16": {
                "class_type": "KSamplerAdvanced",
                "inputs": {
                    "model": ["9", 0],
                    "positive": ["14", 0],
                    "negative": ["14", 1],
                    "latent_image": ["15", 0],
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
            "17": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["16", 0], "vae": ["2", 0]},
            },
            "18": {
                "class_type": "CreateVideo",
                "inputs": {"images": ["17", 0], "fps": params["frame_rate"]},
            },
            "19": {
                "class_type": "SaveVideo",
                "inputs": {
                    "video": ["18", 0],
                    "filename_prefix": params["filename_prefix"],
                    "format": "auto",
                    "codec": "auto",
                },
            },
        }
