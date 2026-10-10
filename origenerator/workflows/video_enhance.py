from __future__ import annotations

from origenerator.media import MediaType
from origenerator.workflows.base import (
    LONGEST_CLIP_FRAMES,
    SAMPLER_OPTIONS,
    SCHEDULER_OPTIONS,
    UPSCALE_MODEL_FACTOR,
    ParamDef,
    ParamType,
    WorkflowTemplate,
    resolution_param,
)
from origenerator.workflows.derived_size import DEFAULT_RESOLUTION
from origenerator.workflows.frame_rate import (
    MAX_PLAYBACK_FPS,
    NATIVE_FPS,
    playback_rate,
    rate_multiplier,
)
from origenerator.workflows.model_arch import WAN
from origenerator.workflows.model_files import (
    ANY,
    NO_LORA,
    list_lora_files,
    list_model_files,
)

# 1.5x is the biggest frame the card holds a whole 5-second stretch of at the
# redraw window below: measured at 64 MB a frame at 480p on the 16 GB card,
# which spills into shared memory past 250, so 200 leaves the model room.
ENHANCE_SCALE = 1.5
_REDRAW_WINDOW_AT_480P = 200


def refine_window_frames(source_megapixels: float) -> int:
    """How many frames the redraw takes together, for a video whose frames were
    made at ``source_megapixels`` and are enhanced at :data:`ENHANCE_SCALE`."""
    return WorkflowTemplate.single_window_frames(
        source_megapixels * ENHANCE_SCALE ** 2, _REDRAW_WINDOW_AT_480P)


class VideoEnhanceWorkflow(WorkflowTemplate):
    """Enhance an existing video: every frame upscaled, then redrawn with more
    detail by WAN 2.2's second-pass model, which draws a whole stretch of
    frames together, guided by the start picture and the prompt. Machinery,
    like the picture enhancer: a finished run folds into the video it enhanced.
    """

    name = "video_enhance"
    version = "v001"
    display_name = "Video Enhance"
    output_type = MediaType.VIDEO
    selectable = False
    model_keys = ("unet_low",)
    lora_keys = ("lora_low",)
    output_node_id = "save"

    def default_params(self) -> dict:
        return {
            "input_video": "",
            "start_image": "",
            "positive_prompt": "",
            "negative_prompt": "",
            "seed": 0,
            "frame_count": 81,
            "frame_rate": NATIVE_FPS,
            "resolution": DEFAULT_RESOLUTION,
            "enhance_scale": ENHANCE_SCALE,
            "enhance_steps": 20,
            "enhance_denoise": 0.2,
            "cfg_low": 3.5,
            "shift_low": 8.0,
            "sampler_name": "euler",
            "scheduler": "simple",
            "unet_low": "split_files\\diffusion_models\\wan2.2_i2v_low_noise_14B_fp16.safetensors",
            "lora_low": NO_LORA,
            "lora_strength_low": 1.0,
            "upscale_model": "4xUltrasharp_4xUltrasharpV10.pt",
            "clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
            "vae_name": "wan_2.1_vae.safetensors",
            "clip_vision_name": "clip_vision_h.safetensors",
            "filename_prefix": "video/video_enhance",
        }

    def param_definitions(self) -> list[ParamDef]:
        defaults = self.default_params()
        return [
            ParamDef("input_video", "Video", ParamType.STR, defaults["input_video"]),
            ParamDef("start_image", "Start Image", ParamType.IMAGE, defaults["start_image"]),
            ParamDef("positive_prompt", "Positive Prompt", ParamType.STR, defaults["positive_prompt"], multiline=True),
            ParamDef("negative_prompt", "Negative Prompt", ParamType.STR, defaults["negative_prompt"], multiline=True),
            ParamDef("seed", "Seed", ParamType.SEED, defaults["seed"]),
            ParamDef("frame_count", "Duration", ParamType.INT, defaults["frame_count"], min_val=5,
                     max_val=LONGEST_CLIP_FRAMES, step=4, unit="s", rate=NATIVE_FPS),
            ParamDef("frame_rate", "Frame Rate", ParamType.FLOAT, defaults["frame_rate"],
                     min_val=NATIVE_FPS, max_val=MAX_PLAYBACK_FPS, step=NATIVE_FPS, unit="fps"),
            resolution_param(defaults),
            ParamDef("enhance_scale", "Upscale Factor", ParamType.FLOAT, defaults["enhance_scale"],
                     min_val=1.0, max_val=ENHANCE_SCALE, step=0.25),
            ParamDef("enhance_steps", "Enhance Steps", ParamType.INT, defaults["enhance_steps"], min_val=1, max_val=100),
            ParamDef("enhance_denoise", "Enhance Redraw Amount", ParamType.FLOAT, defaults["enhance_denoise"],
                     min_val=0.0, max_val=1.0, step=0.05),
            ParamDef("cfg_low", "Prompt Strength (Second Pass)", ParamType.FLOAT, defaults["cfg_low"], min_val=0.0, max_val=30.0, step=0.1),
            ParamDef("shift_low", "Composition Focus (Second Pass)", ParamType.FLOAT, defaults["shift_low"], min_val=0.0, max_val=20.0, step=0.5),
            ParamDef("sampler_name", "Drawing Method", ParamType.COMBO, defaults["sampler_name"], options=SAMPLER_OPTIONS),
            ParamDef("scheduler", "Step Spacing", ParamType.COMBO, defaults["scheduler"], options=SCHEDULER_OPTIONS),
            ParamDef("unet_low", "Model (Second Pass)", ParamType.COMBO, defaults["unet_low"],
                     options=list_model_files("diffusion_models", [defaults["unet_low"]],
                                              accepts=(WAN,), expert="low")),
            ParamDef("lora_low", "Add-on (Second Pass)", ParamType.COMBO, defaults["lora_low"],
                     options=list_lora_files([defaults["lora_low"]], accepts=(WAN,), expert="low")),
            ParamDef("lora_strength_low", "Add-on Strength (Second Pass)", ParamType.FLOAT,
                     defaults["lora_strength_low"], min_val=0.0, max_val=2.0, step=0.05),
            ParamDef("upscale_model", "Upscaler", ParamType.COMBO, defaults["upscale_model"],
                     options=list_model_files("upscale_models", [defaults["upscale_model"]], accepts=ANY)),
        ]

    def build_api_payload(self, params: dict) -> dict:
        lora, model = self.lora_model_input(
            "lora", ["unet", 0], params["lora_low"], params["lora_strength_low"])
        nodes = {
            "load": {"class_type": "LoadVideo", "inputs": {"file": params["input_video"]}},
            "parts": {"class_type": "GetVideoComponents", "inputs": {"video": ["load", 0]}},
            "clip": {
                "class_type": "CLIPLoader",
                "inputs": {"clip_name": params["clip_name"], "type": "wan", "device": "default"},
            },
            "vae": {"class_type": "VAELoader", "inputs": {"vae_name": params["vae_name"]}},
            "vision": {
                "class_type": "CLIPVisionLoader",
                "inputs": {"clip_name": params["clip_vision_name"]},
            },
            "unet": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": params["unet_low"], "weight_dtype": "default"},
            },
            **lora,
            "shift": {
                "class_type": "ModelSamplingSD3",
                "inputs": {"model": model, "shift": params["shift_low"]},
            },
            "positive": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["clip", 0], "text": params["positive_prompt"]},
            },
            "negative": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["clip", 0], "text": params["negative_prompt"]},
            },
            "upscaler": {
                "class_type": "UpscaleModelLoader",
                "inputs": {"model_name": params["upscale_model"]},
            },
        }
        frames = ["parts", 0]
        multiplier = rate_multiplier(params["frame_rate"])
        if multiplier > 1:
            nodes["native"] = {
                "class_type": "VHS_SelectEveryNthImage",
                "inputs": {"images": frames, "select_every_nth": multiplier,
                           "skip_first_images": 0},
            }
            frames = ["native", 0]
        windows = self.segment_lengths(
            int(params["frame_count"]), refine_window_frames(self.pixel_budget(params)))
        joined, first_frame = None, 0
        for index, length in enumerate(windows):
            stretch, redrawn = self._redrawn_stretch(
                index, frames, first_frame, length, len(windows) == 1, params)
            nodes.update(stretch)
            if joined is None:
                joined = redrawn
            else:
                joined = self.join_after_the_shared_frame(nodes, f"w{index}_", joined, redrawn, length)
            first_frame += length - 1
        smoothed, frames_ref = self.interpolation_nodes("smooth", joined, params)
        return {
            **nodes,
            **smoothed,
            "create": {
                "class_type": "CreateVideo",
                "inputs": {"images": frames_ref, "fps": playback_rate(params["frame_rate"]),
                           "audio": ["parts", 1]},
            },
            "save": {
                "class_type": "SaveVideo",
                "inputs": {"video": ["create", 0], "filename_prefix": params["filename_prefix"],
                           "format": "auto", "codec": "auto"},
            },
        }

    def _redrawn_stretch(self, index, frames, first_frame, length, whole, params):
        """One stretch upscaled, encoded and redrawn, the model told it starts
        on the start picture (the first stretch, when there is one) or on the
        stretch's own first frame."""
        prefix = f"w{index}_"
        nodes = {}
        if whole:
            stretch = frames
        else:
            nodes[prefix + "frames"] = {
                "class_type": "ImageFromBatch",
                "inputs": {"image": frames, "batch_index": first_frame, "length": length},
            }
            stretch = [prefix + "frames", 0]
        nodes[prefix + "upscale"] = {
            "class_type": "ImageUpscaleWithModel",
            "inputs": {"upscale_model": ["upscaler", 0], "image": stretch},
        }
        nodes[prefix + "rescale"] = {
            "class_type": "ImageScaleBy",
            "inputs": {"image": [prefix + "upscale", 0], "upscale_method": "lanczos",
                       "scale_by": params["enhance_scale"] / UPSCALE_MODEL_FACTOR},
        }
        if index == 0:
            nodes["size"] = {"class_type": "GetImageSize", "inputs": {"image": [prefix + "rescale", 0]}}
        nodes[prefix + "encode"] = {
            "class_type": "VAEEncode",
            "inputs": {"pixels": [prefix + "rescale", 0], "vae": ["vae", 0]},
        }
        if index == 0 and params["start_image"]:
            nodes["picture"] = {"class_type": "LoadImage", "inputs": {"image": params["start_image"]}}
            nodes["fitted"] = {
                "class_type": "ImageScale",
                "inputs": {"image": ["picture", 0], "upscale_method": "lanczos",
                           "width": ["size", 0], "height": ["size", 1], "crop": "disabled"},
            }
            start = ["fitted", 0]
        else:
            nodes[prefix + "start"] = {
                "class_type": "ImageFromBatch",
                "inputs": {"image": [prefix + "rescale", 0], "batch_index": 0, "length": 1},
            }
            start = [prefix + "start", 0]
        nodes[prefix + "seen"] = {
            "class_type": "CLIPVisionEncode",
            "inputs": {"clip_vision": ["vision", 0], "image": start, "crop": "center"},
        }
        nodes[prefix + "i2v"] = {
            "class_type": "WanImageToVideo",
            "inputs": {
                "positive": ["positive", 0],
                "negative": ["negative", 0],
                "vae": ["vae", 0],
                "clip_vision_output": [prefix + "seen", 0],
                "start_image": start,
                "width": ["size", 0],
                "height": ["size", 1],
                "length": length,
                "batch_size": 1,
            },
        }
        nodes[prefix + "sampler"] = {
            "class_type": "KSampler",
            "inputs": {
                "model": ["shift", 0],
                "positive": [prefix + "i2v", 0],
                "negative": [prefix + "i2v", 1],
                "latent_image": [prefix + "encode", 0],
                "seed": params["seed"] + index,
                "steps": params["enhance_steps"],
                "cfg": params["cfg_low"],
                "sampler_name": params["sampler_name"],
                "scheduler": params["scheduler"],
                "denoise": params["enhance_denoise"],
            },
        }
        nodes[prefix + "decode"] = {
            "class_type": "VAEDecode",
            "inputs": {"samples": [prefix + "sampler", 0], "vae": ["vae", 0]},
        }
        return nodes, [prefix + "decode", 0]
