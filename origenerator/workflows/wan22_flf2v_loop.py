from origenerator.workflows.base import ParamDef, WorkflowTemplate
from origenerator.workflows.model_files import list_model_files


class Wan22Flf2vLoopWorkflow(WorkflowTemplate):
    """WAN 2.2 first-last-frame loop: a single image drives both endpoints.

    The output resolution is derived in-graph from the input image (see
    :meth:`build_api_payload`): it keeps the image's aspect ratio at a fixed
    pixel budget rather than a hardcoded resolution.
    """

    name = "wan22_flf2v_loop"
    version = "v005"
    display_name = "WAN 2.2 FLF2V Loop (Image-to-Video)"
    output_type = "video"
    model_keys = ("unet_high", "unet_low")
    lora_keys = ("lora_high", "lora_low")
    output_node_id = "16"
    output_key = "gifs"

    def default_params(self) -> dict:
        return {
            "positive_prompt": "",
            "negative_prompt": "",
            "input_image": "",
            "noise_seed": 0,
            "seed": 0,
            "frame_count": 21,
            "batch_size": 1,
            "steps": 4,
            "cfg": 1.0,
            "sampler_name": "euler",
            "scheduler": "simple",
            "shift_high": 5.0,
            "shift_low": 5.0,
            "lora_strength_high": 1.0,
            "lora_strength_low": 1.0,
            "frame_rate": 16.0,
            "crf": 19,
            "filename_prefix": "video/flf2v_loop",
            "clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
            "vae_name": "wan_2.1_vae.safetensors",
            "unet_high": "wan22EnhancedNSFWSVICamera_nolightningSVICfFp8H.safetensors",
            "unet_low": "wan22EnhancedNSFWSVICamera_nolightningSVICfFp8L.safetensors",
            "lora_high": "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
            "lora_low": "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
        }

    def param_definitions(self) -> list[ParamDef]:
        defaults = self.default_params()
        loras = list_model_files("loras", [defaults["lora_high"], defaults["lora_low"]])
        return [
            ParamDef("positive_prompt", "Positive Prompt", "str", "", multiline=True),
            ParamDef("negative_prompt", "Negative Prompt", "str", "", multiline=True),
            ParamDef("input_image", "Input Image", "image", ""),
            ParamDef("noise_seed", "Noise Seed (Stage 1)", "seed", 0),
            ParamDef("seed", "Seed (Stage 2)", "seed", 0),
            ParamDef("frame_count", "Frames", "int", 21, min_val=5, max_val=81, step=4),
            ParamDef("steps", "Steps", "int", 4, min_val=1, max_val=50),
            ParamDef("cfg", "CFG Scale", "float", 1.0, min_val=0.0, max_val=30.0, step=0.1),
            ParamDef("shift_high", "Shift (High)", "float", 5.0, min_val=0.0, max_val=20.0, step=0.5),
            ParamDef("shift_low", "Shift (Low)", "float", 5.0, min_val=0.0, max_val=20.0, step=0.5),
            ParamDef("lora_high", "LoRA (High)", "combo", defaults["lora_high"], options=loras),
            ParamDef("lora_strength_high", "LoRA Strength (High)", "float", 1.0, min_val=0.0, max_val=2.0, step=0.05),
            ParamDef("lora_low", "LoRA (Low)", "combo", defaults["lora_low"], options=loras),
            ParamDef("lora_strength_low", "LoRA Strength (Low)", "float", 1.0, min_val=0.0, max_val=2.0, step=0.05),
            ParamDef("frame_rate", "Frame Rate", "float", 16.0, min_val=1.0, max_val=60.0, step=1.0),
            ParamDef("crf", "Video Quality (CRF)", "int", 19, min_val=0, max_val=51),
            ParamDef("filename_prefix", "Output Prefix", "str", "video/flf2v_loop"),
        ]

    def build_api_payload(self, params: dict) -> dict:
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
                "inputs": {
                    "unet_name": params["unet_high"],
                    "weight_dtype": "default",
                },
            },
            "4": {
                "class_type": "UNETLoader",
                "inputs": {
                    "unet_name": params["unet_low"],
                    "weight_dtype": "default",
                },
            },
            "5": {
                "class_type": "LoraLoaderModelOnly",
                "inputs": {
                    "model": ["3", 0],
                    "lora_name": params["lora_high"],
                    "strength_model": params["lora_strength_high"],
                },
            },
            "6": {
                "class_type": "LoraLoaderModelOnly",
                "inputs": {
                    "model": ["4", 0],
                    "lora_name": params["lora_low"],
                    "strength_model": params["lora_strength_low"],
                },
            },
            "7": {
                "class_type": "ModelSamplingSD3",
                "inputs": {"model": ["5", 0], "shift": params["shift_high"]},
            },
            "8": {
                "class_type": "ModelSamplingSD3",
                "inputs": {"model": ["6", 0], "shift": params["shift_low"]},
            },
            "9": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["1", 0], "text": params["positive_prompt"]},
            },
            "10": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["1", 0], "text": params["negative_prompt"]},
            },
            "11": {
                "class_type": "LoadImage",
                "inputs": {"image": params["input_image"]},
            },
            # Derive the output resolution from the input image: scale it to a
            # fixed pixel budget on WAN's /16 stride (keeping aspect), then read
            # the resulting size back to drive the video node — so a portrait or
            # widescreen still yields a proportional loop without a hardcoded WxH.
            "17": {
                "class_type": "ImageScaleToTotalPixels",
                "inputs": {
                    "image": ["11", 0],
                    "upscale_method": "lanczos",
                    "megapixels": 0.4,
                    "resolution_steps": 16,
                },
            },
            "18": {
                "class_type": "GetImageSize",
                "inputs": {"image": ["17", 0]},
            },
            "12": {
                "class_type": "WanFirstLastFrameToVideo",
                "inputs": {
                    "positive": ["9", 0],
                    "negative": ["10", 0],
                    "vae": ["2", 0],
                    "start_image": ["17", 0],
                    "end_image": ["17", 0],
                    "width": ["18", 0],
                    "height": ["18", 1],
                    "length": params["frame_count"],
                    "batch_size": params["batch_size"],
                },
            },
            "13": {
                "class_type": "KSamplerAdvanced",
                "inputs": {
                    "model": ["7", 0],
                    "positive": ["12", 0],
                    "negative": ["12", 1],
                    "latent_image": ["12", 2],
                    "add_noise": "enable",
                    "noise_seed": params["noise_seed"],
                    "steps": params["steps"],
                    "cfg": params["cfg"],
                    "sampler_name": params["sampler_name"],
                    "scheduler": params["scheduler"],
                    "start_at_step": 0,
                    "end_at_step": params["steps"] // 2,
                    "return_with_leftover_noise": "enable",
                },
            },
            "14": {
                "class_type": "KSamplerAdvanced",
                "inputs": {
                    "model": ["8", 0],
                    "positive": ["12", 0],
                    "negative": ["12", 1],
                    "latent_image": ["13", 0],
                    "add_noise": "disable",
                    "noise_seed": params["seed"],
                    "steps": params["steps"],
                    "cfg": params["cfg"],
                    "sampler_name": params["sampler_name"],
                    "scheduler": params["scheduler"],
                    "start_at_step": params["steps"] // 2,
                    "end_at_step": params["steps"],
                    "return_with_leftover_noise": "disable",
                },
            },
            "15": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["14", 0], "vae": ["2", 0]},
            },
            "16": {
                "class_type": "VHS_VideoCombine",
                "inputs": {
                    "images": ["15", 0],
                    "frame_rate": params["frame_rate"],
                    "loop_count": 0,
                    "filename_prefix": params["filename_prefix"],
                    "format": "video/h264-mp4",
                    "pix_fmt": "yuv420p",
                    "crf": params["crf"],
                    "save_metadata": True,
                    "trim_to_audio": False,
                    "pingpong": False,
                    "save_output": True,
                },
            },
        }
