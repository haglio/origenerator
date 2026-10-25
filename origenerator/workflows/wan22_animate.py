from __future__ import annotations

from app_support.funscript import read_actions

from origenerator import config
from origenerator.funscript import library_funscript_of, video_duration_seconds
from origenerator.media import MediaType, video_frame_size
from origenerator.workflows.base import (
    DURATION_OPTIONS,
    FRAME_RATE_OPTIONS,
    LONGEST_CLIP_FRAMES,
    ParamDef,
    ParamType,
    WorkflowTemplate,
    chained_frames,
)
from origenerator.workflows.derived_size import scale_to_total_pixels
from origenerator.workflows.driving_video import driven_actions, frames_within, start_frame
from origenerator.workflows.frame_rate import MAX_PLAYBACK_FPS, NATIVE_FPS
from origenerator.workflows.lora_rows import lora_rows, picked_loras
from origenerator.workflows.model_arch import WAN, WAN_ANIMATE
from origenerator.workflows.model_files import NO_LORA, list_model_files
from origenerator.workflows.video_writer import video_writer

# Comfy's own Animate template runs the model under this LoRA: six steps, no guidance.
DISTILL_LORA = "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors"
_PERSON_FINDER = "yolox_l.torchscript.pt"
_POSE_ESTIMATOR = "dw-ll_ucoco_384_bs5.torchscript.pt"
_SEAM_FRAMES = 1


class Wan22AnimateWorkflow(WorkflowTemplate):
    """WAN 2.2 Animate: the person in the image performs a library video's movements.

    ComfyUI's own ``video_wan2_2_14B_animate`` template in its animation mode, the
    run shaped like the video and the image fitted into it, never cropped; the
    video's sound and script (:meth:`authored_actions`) come along."""

    name = "wan22_animate"
    version = "v001"
    display_name = "WAN 2.2 I2V (Moves from a Library Video)"
    output_type = MediaType.VIDEO
    derives_size_from_input = True
    derived_size_source = "video"
    model_keys = ("unet",)
    lora_keys = ("lora",)
    output_node_id = "24"

    def default_params(self) -> dict:
        return {
            "positive_prompt": "",
            "negative_prompt": "",
            "input_image": "",
            "video": "",
            "video_start": 0.0,
            "seed": 0,
            "frame_count": 81,
            "batch_size": 1,
            "steps": 6,
            "cfg": 1.0,
            "sampler_name": "euler",
            "scheduler": "simple",
            "shift": 8.0,
            "frame_rate": NATIVE_FPS,
            "filename_prefix": "video/wan22_animate",
            "clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
            "vae_name": "wan_2.1_vae.safetensors",
            "clip_vision_name": "clip_vision_h.safetensors",
            "unet": "Wan2_2-Animate-14B_fp8_scaled_e4m3fn_KJ_v2.safetensors",
            "lora": NO_LORA,
            "lora_strength": 1.0,
        }

    def param_definitions(self) -> list[ParamDef]:
        defaults = self.default_params()
        models = list_model_files("diffusion_models", [defaults["unet"]], accepts=(WAN_ANIMATE,))
        return [
            ParamDef("positive_prompt", "Positive Prompt", ParamType.STR, defaults["positive_prompt"], multiline=True),
            ParamDef("negative_prompt", "Negative Prompt", ParamType.STR, defaults["negative_prompt"], multiline=True),
            ParamDef("input_image", "Image", ParamType.IMAGE, defaults["input_image"]),
            ParamDef("video", "Video to Perform", ParamType.VIDEO, defaults["video"],
                     browse_dir=config.LIBRARY_VIDEOS_DIR),
            ParamDef("video_start", "Start in the Video (s)", ParamType.FLOAT, defaults["video_start"],
                     min_val=0.0, step=1.0),
            ParamDef("seed", "Seed", ParamType.SEED, defaults["seed"]),
            ParamDef("frame_count", "Duration", ParamType.INT, defaults["frame_count"], min_val=5,
                     max_val=LONGEST_CLIP_FRAMES, step=4, options=DURATION_OPTIONS, unit="s",
                     rate=NATIVE_FPS, good=(81, 161)),
            ParamDef("steps", "Steps", ParamType.INT, defaults["steps"], min_val=1, max_val=100, good=(4, 8)),
            ParamDef("cfg", "Prompt Strength", ParamType.FLOAT, defaults["cfg"], min_val=0.0, max_val=30.0, step=0.1,
                     good=(1.0, 1.0)),
            ParamDef("shift", "Composition Focus", ParamType.FLOAT, defaults["shift"], min_val=0.0, max_val=20.0,
                     step=0.5, good=(5, 12)),
            ParamDef("unet", "Model", ParamType.COMBO, defaults["unet"], options=models),
            *lora_rows(defaults, ("lora",), accepts=(WAN,)),
            ParamDef("frame_rate", "Frame Rate", ParamType.FLOAT, defaults["frame_rate"],
                     min_val=NATIVE_FPS, max_val=MAX_PLAYBACK_FPS, step=NATIVE_FPS,
                     options=FRAME_RATE_OPTIONS, unit="fps"),
        ]

    def derived_display_size(self, params: dict) -> tuple[int, int] | None:
        size = video_frame_size(params.get("video") or "")
        return scale_to_total_pixels(*size) if size else None

    def authored_actions(self, params: dict) -> list[dict] | None:
        script = library_funscript_of(params.get("video") or "", videos_dir=config.LIBRARY_VIDEOS_DIR,
                                      scripts_dir=config.LIBRARY_SCRIPTS_DIR)
        actions = read_actions(script)
        if not actions:
            return None
        params = self._within_the_video(params)
        return driven_actions(actions, start_ms=_ms(start_frame(params["video_start"])),
                              length_ms=_ms(self.clip_frames(self.scene_plan(params))))

    @staticmethod
    def _within_the_video(params: dict) -> dict:
        seconds = video_duration_seconds(params["video"]) if params.get("video") else None
        frames = frames_within(int(params["frame_count"]), video_seconds=seconds,
                               start=start_frame(params["video_start"]))
        return {**params, "frame_count": frames} if frames != params["frame_count"] else params

    def build_api_payload(self, params: dict) -> dict:
        params = self._within_the_video(params)
        plan = self.scene_plan(params)
        offsets = [chained_frames([length for length, _ in plan[:index]]) if index else 0
                   for index in range(len(plan))]
        loras = self.lora_chain("6", ["5", 0], picked_loras(params, ("lora",)))
        sized = self.image_size_nodes(["13", 0], params)
        width, height = sized.width, sized.height

        def segment(index, scene, start, length, last, previous=None):
            animate_id, sample_id, trim_id, decode_id = (
                ("19", "20", "21", "22") if index == 0
                else tuple(f"s{index}_{name}" for name in ("animate", "sample", "trim", "decode")))
            conditioning = {
                "positive": ["8", 0],
                "negative": ["9", 0],
                "vae": ["2", 0],
                "width": width,
                "height": height,
                "length": length,
                "batch_size": params["batch_size"],
                "clip_vision_output": ["11", 0],
                "reference_image": ["15", 0],
                "face_video": ["18", 0],
                "pose_video": ["17", 0],
                "continue_motion_max_frames": _SEAM_FRAMES,
                "video_frame_offset": offsets[index],
            }
            if index:
                conditioning["continue_motion"] = start
            nodes = {
                animate_id: {"class_type": "WanAnimateToVideo", "inputs": conditioning},
                sample_id: {
                    "class_type": "KSampler",
                    "inputs": {
                        "model": ["7", 0],
                        "positive": [animate_id, 0],
                        "negative": [animate_id, 1],
                        "latent_image": [animate_id, 2],
                        "seed": params["seed"] + index,
                        "steps": params["steps"],
                        "cfg": params["cfg"],
                        "sampler_name": params["sampler_name"],
                        "scheduler": params["scheduler"],
                        "denoise": 1.0,
                    },
                },
                trim_id: {
                    "class_type": "TrimVideoLatent",
                    "inputs": {"samples": [sample_id, 0], "trim_amount": [animate_id, 3]},
                },
                decode_id: {
                    "class_type": "VAEDecode",
                    "inputs": {"samples": [trim_id, 0], "vae": ["2", 0]},
                },
            }
            return nodes, [decode_id, 0]

        segments, decoded_ref, total_frames = self.chain_segments(params, None, segment)
        interpolate, frames_ref = self.interpolation_nodes("23", decoded_ref, params)
        return {
            **interpolate,
            **sized.nodes,
            **segments,
            "1": {
                "class_type": "CLIPLoader",
                "inputs": {"clip_name": params["clip_name"], "type": "wan", "device": "default"},
            },
            "2": {"class_type": "VAELoader", "inputs": {"vae_name": params["vae_name"]}},
            "3": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": params["clip_vision_name"]}},
            "4": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": params["unet"], "weight_dtype": "default"},
            },
            "5": {
                "class_type": "LoraLoaderModelOnly",
                "inputs": {"model": ["4", 0], "lora_name": DISTILL_LORA, "strength_model": 1.0},
            },
            **loras.nodes,
            "7": {"class_type": "ModelSamplingSD3", "inputs": {"model": loras.model, "shift": params["shift"]}},
            "8": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 0], "text": params["positive_prompt"]}},
            "9": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 0], "text": params["negative_prompt"]}},
            "10": {"class_type": "LoadImage", "inputs": {"image": params["input_image"]}},
            "11": {
                "class_type": "CLIPVisionEncode",
                "inputs": {"clip_vision": ["3", 0], "image": ["10", 0], "crop": "none"},
            },
            "12": {
                "class_type": "VHS_LoadVideoPath",
                "inputs": {
                    "video": params["video"],
                    "force_rate": NATIVE_FPS,
                    "custom_width": 0,
                    "custom_height": 0,
                    "frame_load_cap": total_frames,
                    "skip_first_frames": start_frame(params["video_start"]),
                    "select_every_nth": 1,
                    "format": "None",
                },
            },
            "13": {
                "class_type": "ImageFromBatch",
                "inputs": {"image": ["12", 0], "batch_index": 0, "length": 1},
            },
            "14": {
                "class_type": "ImageScale",
                "inputs": {"image": ["12", 0], "upscale_method": "lanczos",
                           "width": width, "height": height, "crop": "center"},
            },
            "15": {
                "class_type": "ImageResizeKJv2",
                "inputs": {"image": ["10", 0], "width": width, "height": height,
                           "upscale_method": "lanczos", "keep_proportion": "pillarbox_blur",
                           "pad_color": "0, 0, 0", "crop_position": "center", "divisible_by": 1},
            },
            "16": {
                "class_type": "PixelPerfectResolution",
                "inputs": {"original_image": ["14", 0], "image_gen_width": width,
                           "image_gen_height": height, "resize_mode": "Just Resize"},
            },
            "17": self._pose_reader(["14", 0], ["16", 0], face="disable"),
            "18": self._pose_reader(["14", 0], ["16", 0], face="enable"),
            self.output_node_id: video_writer(frames_ref, ["12", 2], params),
        }

    @staticmethod
    def _pose_reader(frames_ref, resolution_ref, *, face: str) -> dict:
        body = "disable" if face == "enable" else "enable"
        return {
            "class_type": "DWPreprocessor",
            "inputs": {
                "image": frames_ref,
                "detect_hand": body,
                "detect_body": body,
                "detect_face": face,
                "resolution": resolution_ref,
                "bbox_detector": _PERSON_FINDER,
                "pose_estimator": _POSE_ESTIMATOR,
                "scale_stick_for_xinsr_cn": "disable",
            },
        }


def _ms(frames: int) -> int:
    return round(frames / NATIVE_FPS * 1000)
