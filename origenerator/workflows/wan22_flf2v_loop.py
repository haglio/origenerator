from __future__ import annotations

from origenerator.workflows.base import (
    DURATION_OPTIONS,
    FRAME_RATE_OPTIONS,
    LONGEST_CLIP_FRAMES,
    ParamDef,
    WorkflowTemplate,
    scene_prompts,
)
from origenerator.workflows.frame_rate import (
    MAX_PLAYBACK_FPS,
    NATIVE_FPS,
    playback_rate,
)
from origenerator.workflows.model_arch import WAN
from origenerator.workflows.model_files import list_lora_files, list_model_files


class Wan22Flf2vLoopWorkflow(WorkflowTemplate):
    """WAN 2.2 first-last-frame loop: a single image drives both endpoints.

    The output resolution is derived in-graph from the input image (see
    :meth:`build_api_payload`): it keeps the image's aspect ratio at a fixed
    pixel budget rather than a hardcoded resolution. The decoded frames are
    interpolated up to the chosen playback rate before they are written
    (:meth:`~WorkflowTemplate.interpolation_nodes`), which leaves the loop's two
    matched endpoints exactly where the model put them. They also
    drive a HunyuanVideo-Foley pass (:meth:`~WorkflowTemplate.foley_audio_nodes`),
    whose synced audio ``VHS_VideoCombine`` muxes into the file — though a
    player restarting the loop restarts the track with it; only the frames
    loop seamlessly.
    """

    name = "wan22_flf2v_loop"
    version = "v009"
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
            "scene_frames": [21],
            "batch_size": 1,
            "steps": 4,
            "cfg": 1.0,
            "sampler_name": "euler",
            "scheduler": "simple",
            "shift_high": 5.0,
            "shift_low": 5.0,
            "lora_strength_high": 1.0,
            "lora_strength_low": 1.0,
            "frame_rate": NATIVE_FPS,
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
            ParamDef("positive_prompt", "Positive Prompt", "str", defaults["positive_prompt"], multiline=True),
            ParamDef("scene_frames", "Scenes", "scenes", defaults["scene_frames"], min_val=5,
                     max_val=LONGEST_CLIP_FRAMES, step=4, options=DURATION_OPTIONS,
                     unit="s", rate=NATIVE_FPS),
            ParamDef("negative_prompt", "Negative Prompt", "str", defaults["negative_prompt"], multiline=True),
            ParamDef("input_image", "Start Image", "image", defaults["input_image"]),
            ParamDef("audio_prompt", "Audio Prompt", "str", defaults["audio_prompt"], multiline=True),
            ParamDef("audio_negative_prompt", "Audio Negative Prompt", "str", defaults["audio_negative_prompt"], multiline=True),
            ParamDef("noise_seed", "Seed (High)", "seed", defaults["noise_seed"]),
            ParamDef("seed", "Seed (Low)", "seed", defaults["seed"]),
            ParamDef("audio_seed", "Audio Seed", "seed", defaults["audio_seed"]),
            ParamDef("frame_count", "Duration", "int", defaults["frame_count"], min_val=5, max_val=LONGEST_CLIP_FRAMES, step=4,
                     options=DURATION_OPTIONS, unit="s", rate=NATIVE_FPS),
            ParamDef("steps", "Steps", "int", defaults["steps"], min_val=1, max_val=100),
            ParamDef("cfg", "Prompt Strength", "float", defaults["cfg"], min_val=0.0, max_val=30.0, step=0.1),
            ParamDef("shift_high", "Shift (High)", "float", defaults["shift_high"], min_val=0.0, max_val=20.0, step=0.5),
            ParamDef("shift_low", "Shift (Low)", "float", defaults["shift_low"], min_val=0.0, max_val=20.0, step=0.5),
            ParamDef("unet_high", "Model (High)", "combo", defaults["unet_high"], options=high),
            ParamDef("unet_low", "Model (Low)", "combo", defaults["unet_low"], options=low),
            ParamDef("lora_high", "LoRA (High)", "combo", defaults["lora_high"], options=loras_high),
            ParamDef("lora_strength_high", "LoRA Strength (High)", "float", defaults["lora_strength_high"], min_val=0.0, max_val=2.0, step=0.05),
            ParamDef("lora_low", "LoRA (Low)", "combo", defaults["lora_low"], options=loras_low),
            ParamDef("lora_strength_low", "LoRA Strength (Low)", "float", defaults["lora_strength_low"], min_val=0.0, max_val=2.0, step=0.05),
            ParamDef("frame_rate", "Frame Rate", "float", defaults["frame_rate"],
                     min_val=NATIVE_FPS, max_val=MAX_PLAYBACK_FPS, step=NATIVE_FPS,
                     options=FRAME_RATE_OPTIONS, unit="fps"),
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
        # Size the loop off the input image: derived in-graph by default, or scaled
        # to the user's explicit WxH when the derived size was unlocked. Both
        # endpoints read the same scaled image.
        sized = self.image_size_nodes(["11", 0], params)
        size_nodes, frame_ref = sized.nodes, sized.image
        width_ref, height_ref = sized.width, sized.height

        # Each segment reads its own scene of the prompt and of the negative (a
        # --- line starts the next of each, which is how the scenes editor stores
        # them); nodes 9 and 10 below encode the first scene's, and any later
        # scene gets its own.
        scenes = scene_prompts(params["positive_prompt"])
        negatives = scene_prompts(params["negative_prompt"])

        def segment(index, scene, start, length, last, previous=None):
            flf_id, high_id, low_id, decode_id = (
                ("12", "13", "14", "15") if index == 0
                else tuple(f"s{index}_{name}" for name in ("flf", "high", "low", "decode"))
            )
            prompt_nodes, positive_ref = self.scene_prompt_nodes(index, scene, scenes, ["1", 0], ["9", 0])
            negative_nodes, negative_ref = self.scene_prompt_nodes(
                index, scene, negatives, ["1", 0], ["10", 0], role="negative")
            # Only the segment that ends the loop is told to end on its start
            # frame; an earlier one told so would close the loop and then have
            # to leave it again.
            endpoints = {"start_image": start, **({"end_image": frame_ref} if last else {})}
            nodes = {
                **prompt_nodes,
                **negative_nodes,
                flf_id: {
                    "class_type": "WanFirstLastFrameToVideo",
                    "inputs": {
                        "positive": positive_ref,
                        "negative": negative_ref,
                        "vae": ["2", 0],
                        **endpoints,
                        "width": width_ref,
                        "height": height_ref,
                        "length": length,
                        "batch_size": params["batch_size"],
                    },
                },
                high_id: {
                    "class_type": "KSamplerAdvanced",
                    "inputs": {
                        "model": ["7", 0],
                        "positive": [flf_id, 0],
                        "negative": [flf_id, 1],
                        "latent_image": [flf_id, 2],
                        "add_noise": "enable",
                        "noise_seed": params["noise_seed"] + index,
                        "steps": params["steps"],
                        "cfg": params["cfg"],
                        "sampler_name": params["sampler_name"],
                        "scheduler": params["scheduler"],
                        "start_at_step": 0,
                        "end_at_step": params["steps"] // 2,
                        "return_with_leftover_noise": "enable",
                    },
                },
                low_id: {
                    "class_type": "KSamplerAdvanced",
                    "inputs": {
                        "model": ["8", 0],
                        "positive": [flf_id, 0],
                        "negative": [flf_id, 1],
                        "latent_image": [high_id, 0],
                        "add_noise": "disable",
                        "noise_seed": params["seed"] + index,
                        "steps": params["steps"],
                        "cfg": params["cfg"],
                        "sampler_name": params["sampler_name"],
                        "scheduler": params["scheduler"],
                        "start_at_step": params["steps"] // 2,
                        "end_at_step": params["steps"],
                        "return_with_leftover_noise": "disable",
                    },
                },
                decode_id: {
                    "class_type": "VAEDecode",
                    "inputs": {"samples": [low_id, 0], "vae": ["2", 0]},
                },
            }
            return nodes, [decode_id, 0]

        # A loop longer than one segment is chained from each segment's last
        # frame (WorkflowTemplate.chain_segments); its frames come back joined.
        segments, decoded_ref, total_frames = self.chain_segments(params, frame_ref, segment)
        # Scored for the frames the scenes really add up to, which is what the
        # stored clip length says whenever the form wrote it.
        foley, audio_ref = self.foley_audio_nodes(
            "19", "20", "21", decoded_ref, {**params, "frame_count": total_frames})
        # Foley scores the decoded frames; VHS_VideoCombine writes the
        # interpolated ones. At the native rate they are the same frames.
        interpolate, frames_ref = self.interpolation_nodes("22", decoded_ref, params)
        return {
            **foley,
            **interpolate,
            **size_nodes,
            **segments,
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
                "inputs": {"clip": ["1", 0], "text": scenes[0]},
            },
            "10": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["1", 0], "text": negatives[0]},
            },
            "11": {
                "class_type": "LoadImage",
                "inputs": {"image": params["input_image"]},
            },
            "16": {
                "class_type": "VHS_VideoCombine",
                "inputs": {
                    "images": frames_ref,
                    "audio": audio_ref,
                    "frame_rate": playback_rate(params["frame_rate"]),
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
