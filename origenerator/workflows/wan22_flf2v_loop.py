from origenerator.workflows.base import ParamDef, WorkflowTemplate
from origenerator.workflows.model_arch import WAN
from origenerator.workflows.model_files import list_lora_files, list_model_files


class Wan22Flf2vLoopWorkflow(WorkflowTemplate):
    """WAN 2.2 first-last-frame loop: a single image drives both endpoints.

    The output resolution is derived in-graph from the input image (see
    :meth:`build_api_payload`): it keeps the image's aspect ratio at a fixed
    pixel budget rather than a hardcoded resolution. The decoded frames also
    drive a HunyuanVideo-Foley pass (:meth:`~WorkflowTemplate.foley_audio_nodes`),
    whose synced audio ``VHS_VideoCombine`` muxes into the file — though a
    player restarting the loop restarts the track with it; only the frames
    loop seamlessly.
    """

    name = "wan22_flf2v_loop"
    version = "v006"
    display_name = "WAN 2.2 FLF2V Loop (Image-to-Video)"
    output_type = "video"
    looping = True
    derives_size_from_input = True
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
            "audio_prompt": "",
            "audio_negative_prompt": "noisy, harsh",
            "audio_seed": 0,
            "foley_model": "hunyuanvideo_foley_fp8_e4m3fn.safetensors",
            "foley_vae": "vae_128d_48k_fp16.safetensors",
            "foley_synchformer": "synchformer_state_dict_fp16.safetensors",
        }

    def param_definitions(self) -> list[ParamDef]:
        defaults = self.default_params()
        # One slot, one expert — see Wan22I2vWorkflow.param_definitions.
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
            ParamDef("input_image", "Input Image", "image", ""),
            ParamDef("audio_prompt", "Audio Prompt", "str", "", multiline=True),
            ParamDef("audio_negative_prompt", "Audio Negative Prompt", "str", "noisy, harsh", multiline=True),
            ParamDef("noise_seed", "Noise Seed (Stage 1)", "seed", 0),
            ParamDef("seed", "Seed (Stage 2)", "seed", 0),
            ParamDef("audio_seed", "Audio Seed", "seed", 0),
            ParamDef("frame_count", "Frames", "int", 21, min_val=5, max_val=81, step=4),
            ParamDef("steps", "Steps", "int", 4, min_val=1, max_val=50),
            ParamDef("cfg", "CFG Scale", "float", 1.0, min_val=0.0, max_val=30.0, step=0.1),
            ParamDef("shift_high", "Shift (High)", "float", 5.0, min_val=0.0, max_val=20.0, step=0.5),
            ParamDef("shift_low", "Shift (Low)", "float", 5.0, min_val=0.0, max_val=20.0, step=0.5),
            ParamDef("unet_high", "Model (High)", "combo", defaults["unet_high"], options=high),
            ParamDef("unet_low", "Model (Low)", "combo", defaults["unet_low"], options=low),
            ParamDef("lora_high", "LoRA (High)", "combo", defaults["lora_high"], options=loras_high),
            ParamDef("lora_strength_high", "LoRA Strength (High)", "float", 1.0, min_val=0.0, max_val=2.0, step=0.05),
            ParamDef("lora_low", "LoRA (Low)", "combo", defaults["lora_low"], options=loras_low),
            ParamDef("lora_strength_low", "LoRA Strength (Low)", "float", 1.0, min_val=0.0, max_val=2.0, step=0.05),
            ParamDef("frame_rate", "Frame Rate", "float", 16.0, min_val=1.0, max_val=60.0, step=1.0),
            ParamDef("crf", "Video Quality (CRF)", "int", 19, min_val=0, max_val=51),
            ParamDef("filename_prefix", "Output Prefix", "str", "video/flf2v_loop"),
        ]

    def build_api_payload(self, params: dict) -> dict:
        # Each LoRA is optional: "None" adds no LoraLoader for that stage, so its
        # sampler runs the base UNET unmodified (WorkflowTemplate.lora_model_input).
        lora_high, model_high = self.lora_model_input(
            "5", ["3", 0], params["lora_high"], params["lora_strength_high"]
        )
        lora_low, model_low = self.lora_model_input(
            "6", ["4", 0], params["lora_low"], params["lora_strength_low"]
        )
        foley, audio_ref = self.foley_audio_nodes("19", "20", "21", ["15", 0], params)
        # Size the loop off the input image: derived in-graph by default, or scaled
        # to the user's explicit WxH when the derived size was unlocked. Both
        # endpoints read the same scaled image.
        size_nodes, frame_ref, width_ref, height_ref = self.image_size_nodes(
            "17", "18", ["11", 0], params
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
            **lora_high,
            **lora_low,
            "7": {
                "class_type": "ModelSamplingSD3",
                "inputs": {"model": model_high, "shift": params["shift_high"]},
            },
            "8": {
                "class_type": "ModelSamplingSD3",
                "inputs": {"model": model_low, "shift": params["shift_low"]},
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
            "12": {
                "class_type": "WanFirstLastFrameToVideo",
                "inputs": {
                    "positive": ["9", 0],
                    "negative": ["10", 0],
                    "vae": ["2", 0],
                    "start_image": frame_ref,
                    "end_image": frame_ref,
                    "width": width_ref,
                    "height": height_ref,
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
                    "audio": audio_ref,
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
