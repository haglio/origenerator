from origenerator.workflows.base import (
    DURATION_OPTIONS,
    FRAME_RATE_OPTIONS,
    ParamDef,
    WorkflowTemplate,
)
from origenerator.workflows.model_arch import WAN
from origenerator.workflows.model_files import list_lora_files, list_model_files


class Wan22I2vWorkflow(WorkflowTemplate):
    """WAN 2.2 14B image-to-video, dual-noise (high/low) sampling.

    Reproduces the ``wan22_14b_i2v_dual_noise_template`` ComfyUI graph: a single
    input image is encoded with CLIP-Vision and fed to ``WanImageToVideo``, then
    denoised by two ``KSamplerAdvanced`` passes (high-noise model first, low-noise
    model after) and written with the native ``CreateVideo`` + ``SaveVideo``
    nodes. The stages hand off at ``split_step`` (0 = half the steps), and each
    can run its own guidance via ``cfg_high``/``cfg_low`` (0 = the shared
    ``cfg``) — LoRA authors tune these per stage (motion lives in the high pass,
    texture in the low), so a recipe can follow their numbers exactly. The output resolution is
    derived in-graph from the input image (see :meth:`build_api_payload`): it
    keeps the image's aspect ratio at a fixed pixel budget rather than a
    hardcoded size. The decoded frames also drive a HunyuanVideo-Foley pass
    (:meth:`~WorkflowTemplate.foley_audio_nodes`), whose synced audio
    ``CreateVideo`` muxes into the file.
    """

    name = "wan22_i2v"
    version = "v004"
    display_name = "WAN 2.2 I2V (Image-to-Video)"
    output_type = "video"
    derives_size_from_input = True
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
            "split_step": 0,
            "cfg": 3.5,
            "cfg_high": 0.0,
            "cfg_low": 0.0,
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
            "audio_prompt": "",
            "audio_negative_prompt": "noisy, harsh",
            "audio_seed": 0,
            "foley_model": "hunyuanvideo_foley_fp8_e4m3fn.safetensors",
            "foley_vae": "vae_128d_48k_fp16.safetensors",
            "foley_synchformer": "synchformer_state_dict_fp16.safetensors",
        }

    def param_definitions(self) -> list[ParamDef]:
        defaults = self.default_params()
        # Each slot offers only WAN, and only the expert it fills: a file whose
        # name claims the other half is the one pick that is certainly wrong
        # here. Names claiming neither stay in both, since nothing inside a
        # WAN 2.2 file distinguishes the two experts.
        high = list_model_files(
            "diffusion_models", [defaults["unet_high"]], accepts=(WAN,), expert="high",
        )
        low = list_model_files(
            "diffusion_models", [defaults["unet_low"]], accepts=(WAN,), expert="low",
        )
        loras_high = list_lora_files([defaults["lora_high"]], accepts=(WAN,), expert="high")
        loras_low = list_lora_files([defaults["lora_low"]], accepts=(WAN,), expert="low")
        return [
            ParamDef("positive_prompt", "Positive Prompt", "str", "", multiline=True),
            ParamDef("negative_prompt", "Negative Prompt", "str", "", multiline=True),
            ParamDef("input_image", "Start Image", "image", ""),
            ParamDef("audio_prompt", "Audio Prompt", "str", "", multiline=True),
            ParamDef("audio_negative_prompt", "Audio Negative Prompt", "str", "noisy, harsh", multiline=True),
            ParamDef("noise_seed", "Seed (High)", "seed", 0),
            ParamDef("seed", "Seed (Low)", "seed", 0),
            ParamDef("audio_seed", "Audio Seed", "seed", 0),
            ParamDef("frame_count", "Duration", "int", 121, min_val=5, max_val=161, step=4,
                     options=DURATION_OPTIONS, unit="s", rate_key="frame_rate"),
            ParamDef("steps", "Steps", "int", 20, min_val=1, max_val=50),
            ParamDef("split_step", "Handoff Step (0 = half)", "int", 0, min_val=0, max_val=50),
            ParamDef("cfg", "Prompt Strength", "float", 3.5, min_val=0.0, max_val=30.0, step=0.1),
            ParamDef("cfg_high", "Prompt Strength (High)", "float", 0.0, min_val=0.0, max_val=30.0, step=0.1),
            ParamDef("cfg_low", "Prompt Strength (Low)", "float", 0.0, min_val=0.0, max_val=30.0, step=0.1),
            ParamDef("shift_high", "Shift (High)", "float", 8.0, min_val=0.0, max_val=20.0, step=0.5),
            ParamDef("shift_low", "Shift (Low)", "float", 8.0, min_val=0.0, max_val=20.0, step=0.5),
            ParamDef("unet_high", "Model (High)", "combo", defaults["unet_high"], options=high),
            ParamDef("unet_low", "Model (Low)", "combo", defaults["unet_low"], options=low),
            ParamDef("lora_high", "LoRA (High)", "combo", defaults["lora_high"], options=loras_high),
            ParamDef("lora_strength_high", "LoRA Strength (High)", "float", 1.0, min_val=0.0, max_val=2.0, step=0.05),
            ParamDef("lora_low", "LoRA (Low)", "combo", defaults["lora_low"], options=loras_low),
            ParamDef("lora_strength_low", "LoRA Strength (Low)", "float", 1.0, min_val=0.0, max_val=2.0, step=0.05),
            ParamDef("frame_rate", "Frame Rate", "float", 24.0, min_val=1.0, max_val=120.0, step=1.0,
                     options=FRAME_RATE_OPTIONS, unit="fps"),
        ]

    def build_api_payload(self, params: dict) -> dict:
        split_step = params["split_step"] or params["steps"] // 2
        cfg_high = params["cfg_high"] or params["cfg"]
        cfg_low = params["cfg_low"] or params["cfg"]
        # Each LoRA is optional: "None" adds no LoraLoader for that stage, so its
        # sampler runs the base UNET unmodified (WorkflowTemplate.lora_model_input).
        lora_high, model_high = self.lora_model_input(
            "6", ["4", 0], params["lora_high"], params["lora_strength_high"]
        )
        lora_low, model_low = self.lora_model_input(
            "7", ["5", 0], params["lora_low"], params["lora_strength_low"]
        )
        foley, audio_ref = self.foley_audio_nodes("22", "23", "24", ["17", 0], params)
        # Size the video off the input image: derived in-graph by default, or
        # scaled to the user's explicit WxH when the derived size was unlocked.
        size_nodes, start_ref, width_ref, height_ref = self.image_size_nodes(
            "20", "21", ["12", 0], params
        )
        return {
            **foley,
            **size_nodes,
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
            **lora_high,
            **lora_low,
            "8": {
                "class_type": "ModelSamplingSD3",
                "inputs": {"model": model_high, "shift": params["shift_high"]},
            },
            "9": {
                "class_type": "ModelSamplingSD3",
                "inputs": {"model": model_low, "shift": params["shift_low"]},
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
            "14": {
                "class_type": "WanImageToVideo",
                "inputs": {
                    "positive": ["10", 0],
                    "negative": ["11", 0],
                    "vae": ["2", 0],
                    "clip_vision_output": ["13", 0],
                    "start_image": start_ref,
                    "width": width_ref,
                    "height": height_ref,
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
                    "cfg": cfg_high,
                    "sampler_name": params["sampler_name"],
                    "scheduler": params["scheduler"],
                    "start_at_step": 0,
                    "end_at_step": split_step,
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
                    "cfg": cfg_low,
                    "sampler_name": params["sampler_name"],
                    "scheduler": params["scheduler"],
                    "start_at_step": split_step,
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
                "inputs": {
                    "images": ["17", 0],
                    "fps": params["frame_rate"],
                    "audio": audio_ref,
                },
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
