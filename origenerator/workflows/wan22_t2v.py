from __future__ import annotations

from origenerator.media import MediaType
from origenerator.workflows.base import (
    DURATION_OPTIONS,
    FRAME_RATE_OPTIONS,
    LONGEST_VIDEO_FRAMES,
    ParamDef,
    ParamType,
    WorkflowTemplate,
)
from origenerator.workflows.frame_rate import MAX_PLAYBACK_FPS, NATIVE_FPS
from origenerator.workflows.lora_rows import lora_defaults, picked_loras
from origenerator.workflows.model_arch import WAN, WAN_T2V
from origenerator.workflows.parts import Segment
from origenerator.workflows.prompt_readers import UMT5
from origenerator.workflows.video_writer import video_writer
from origenerator.workflows.wan22_i2v import wan_i2v_segment
from origenerator.workflows.wan_experts import (
    FIRST_PASS_LORA_KEYS,
    LORA_KEYS_OF_BOTH_PASSES,
    LORAS_KEYED_ONLY_WHEN_NAMED,
    SECOND_PASS_LORA_KEYS,
    wan_expert_lora_params,
    wan_expert_model_params,
    wan_expert_shift_param,
)

_CONTINUED_HIGH = ["28", 0]
_CONTINUED_LOW = ["29", 0]


class Wan22T2vWorkflow(WorkflowTemplate):
    name = "wan22_t2v"
    version = "v001"
    display_name = "T2V WAN 2.2"
    output_type = MediaType.VIDEO
    model_keys = ("unet_high", "unet_low")
    lora_keys = LORA_KEYS_OF_BOTH_PASSES
    text_reader = UMT5
    loras_keyed_only_when_named = LORAS_KEYED_ONLY_WHEN_NAMED
    keyed_only_when_on = ("enable_audio",)
    output_node_id = "19"

    def default_params(self) -> dict:
        return {
            "positive_prompt": "",
            "negative_prompt": "",
            "noise_seed": 0,
            "seed": 0,
            "width": 480,
            "height": 832,
            "frame_count": 81,
            "batch_size": 1,
            "steps": 20,
            "split_step": 0,
            "cfg_high": 3.5,
            "cfg_low": 3.5,
            "sampler_name": "euler",
            "scheduler": "simple",
            "shift_high": 8.0,
            "shift_low": 8.0,
            "frame_rate": NATIVE_FPS,
            "filename_prefix": "video/wan22_t2v",
            "clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
            "vae_name": "wan_2.1_vae.safetensors",
            "clip_vision_name": "clip_vision_h.safetensors",
            "unet_high": "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors",
            "unet_low": "wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors",
            "unet_continued_high": "split_files\\diffusion_models\\wan2.2_i2v_high_noise_14B_fp16.safetensors",
            "unet_continued_low": "split_files\\diffusion_models\\wan2.2_i2v_low_noise_14B_fp16.safetensors",
            **lora_defaults(LORA_KEYS_OF_BOTH_PASSES),
            "enable_audio": False,
            "audio_prompt": "",
            "audio_negative_prompt": "noisy, harsh",
            "audio_seed": 0,
            "foley_model": "hunyuanvideo_foley_fp8_e4m3fn.safetensors",
            "foley_vae": "vae_128d_48k_fp16.safetensors",
            "foley_synchformer": "synchformer_state_dict_fp16.safetensors",
        }

    def param_definitions(self) -> list[ParamDef]:
        defaults = self.default_params()
        return [
            ParamDef("positive_prompt", "Positive Prompt", ParamType.STR, defaults["positive_prompt"], multiline=True),
            ParamDef("negative_prompt", "Negative Prompt", ParamType.STR, defaults["negative_prompt"], multiline=True),
            ParamDef("enable_audio", "Enable Audio", ParamType.BOOL, defaults["enable_audio"], switch=True),
            ParamDef("audio_prompt", "Positive Prompt", ParamType.STR, defaults["audio_prompt"], multiline=True),
            ParamDef("audio_negative_prompt", "Negative Prompt", ParamType.STR, defaults["audio_negative_prompt"], multiline=True),
            ParamDef("noise_seed", "Seed", ParamType.SEED, defaults["noise_seed"]),
            ParamDef("audio_seed", "Audio Seed", ParamType.SEED, defaults["audio_seed"]),
            ParamDef("width", "Width", ParamType.INT, defaults["width"], min_val=64, max_val=2048, step=16),
            ParamDef("height", "Height", ParamType.INT, defaults["height"], min_val=64, max_val=2048, step=16),
            ParamDef("frame_count", "Duration", ParamType.INT, defaults["frame_count"], min_val=5, max_val=LONGEST_VIDEO_FRAMES, step=4,
                     options=DURATION_OPTIONS, unit="s", shown_in_seconds_at=NATIVE_FPS, good=(81, 161)),
            ParamDef("steps", "Steps", ParamType.INT, defaults["steps"], min_val=1, max_val=100, good=(20, 30)),
            ParamDef("split_step", "Handoff Step", ParamType.INT, defaults["split_step"], min_val=0, max_val=100),
            ParamDef("cfg_high", "Prompt Strength (First Pass)", ParamType.FLOAT, defaults["cfg_high"], min_val=0.0, max_val=30.0, step=0.1, good=(3, 4)),
            ParamDef("cfg_low", "Prompt Strength (Second Pass)", ParamType.FLOAT, defaults["cfg_low"], min_val=0.0, max_val=30.0, step=0.1, good=(3, 4)),
            wan_expert_shift_param(defaults),
            *wan_expert_model_params(defaults, accepts=(WAN_T2V,)),
            *wan_expert_lora_params(defaults, accepts=(WAN_T2V, WAN)),
            ParamDef("frame_rate", "Frame Rate", ParamType.FLOAT, defaults["frame_rate"],
                     min_val=NATIVE_FPS, max_val=MAX_PLAYBACK_FPS, step=NATIVE_FPS,
                     options=FRAME_RATE_OPTIONS, unit="fps"),
        ]

    def build_api_payload(self, params: dict) -> dict:
        split_step = params["split_step"] or params["steps"] // 2
        sampling = (params["cfg_high"], params["cfg_low"], split_step)
        loras_high = self.lora_chain("6", ["4", 0], picked_loras(params, FIRST_PASS_LORA_KEYS))
        loras_low = self.lora_chain("7", ["5", 0], picked_loras(params, SECOND_PASS_LORA_KEYS))
        size = (params["width"], params["height"])
        continued = len(self.scene_plan(params)) > 1

        def segment(at: Segment):
            if at.index:
                return wan_i2v_segment(at, (["10", 0], ["11", 0]), size, params,
                                       (_CONTINUED_HIGH, _CONTINUED_LOW), sampling)
            return self._from_text(at, params, sampling)

        segments, decoded_ref, total_frames = self.chain_segments(params, None, segment)
        foley, audio_ref = self.foley_audio_nodes(
            "22", "23", "24", decoded_ref, {**params, "frame_count": total_frames})
        interpolate, frames_ref = self.interpolation_nodes("25", decoded_ref, params)
        return {
            **foley,
            **interpolate,
            **segments,
            **loras_high.nodes,
            **loras_low.nodes,
            **(self._continuing_models(params) if continued else {}),
            "1": {"class_type": "CLIPLoader",
                  "inputs": {"clip_name": params["clip_name"], "type": "wan", "device": "default"}},
            "2": {"class_type": "VAELoader", "inputs": {"vae_name": params["vae_name"]}},
            "4": {"class_type": "UNETLoader",
                  "inputs": {"unet_name": params["unet_high"], "weight_dtype": "default"}},
            "5": {"class_type": "UNETLoader",
                  "inputs": {"unet_name": params["unet_low"], "weight_dtype": "default"}},
            "8": {"class_type": "ModelSamplingSD3",
                  "inputs": {"model": loras_high.model, "shift": params["shift_high"]}},
            "9": {"class_type": "ModelSamplingSD3",
                  "inputs": {"model": loras_low.model, "shift": params["shift_low"]}},
            "10": {"class_type": "CLIPTextEncode",
                   "inputs": {"clip": ["1", 0], "text": params["positive_prompt"]}},
            "11": {"class_type": "CLIPTextEncode",
                   "inputs": {"clip": ["1", 0], "text": params["negative_prompt"]}},
            self.output_node_id: video_writer(frames_ref, audio_ref, params),
        }

    @staticmethod
    def _from_text(at: Segment, params: dict, sampling) -> tuple[dict, list]:
        cfg_high, cfg_low, split_step = sampling
        shared = {"positive": ["10", 0], "negative": ["11", 0], "steps": params["steps"],
                  "sampler_name": params["sampler_name"], "scheduler": params["scheduler"]}
        return {
            "12": {"class_type": "EmptyHunyuanLatentVideo", "inputs": {
                "width": params["width"], "height": params["height"], "length": at.length,
                "batch_size": params["batch_size"]}},
            "15": {"class_type": "KSamplerAdvanced", "inputs": {
                **shared, "model": ["8", 0], "latent_image": ["12", 0], "add_noise": "enable",
                "noise_seed": params["noise_seed"], "cfg": cfg_high, "start_at_step": 0,
                "end_at_step": split_step, "return_with_leftover_noise": "enable"}},
            "16": {"class_type": "KSamplerAdvanced", "inputs": {
                **shared, "model": ["9", 0], "latent_image": ["15", 0], "add_noise": "disable",
                "noise_seed": params["seed"], "cfg": cfg_low, "start_at_step": split_step,
                "end_at_step": 10000, "return_with_leftover_noise": "disable"}},
            "17": {"class_type": "VAEDecode", "inputs": {"samples": ["16", 0], "vae": ["2", 0]}},
        }, ["17", 0]

    @staticmethod
    def _continuing_models(params: dict) -> dict:
        return {
            "3": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": params["clip_vision_name"]}},
            "26": {"class_type": "UNETLoader",
                   "inputs": {"unet_name": params["unet_continued_high"], "weight_dtype": "default"}},
            "27": {"class_type": "UNETLoader",
                   "inputs": {"unet_name": params["unet_continued_low"], "weight_dtype": "default"}},
            "28": {"class_type": "ModelSamplingSD3",
                   "inputs": {"model": ["26", 0], "shift": params["shift_high"]}},
            "29": {"class_type": "ModelSamplingSD3",
                   "inputs": {"model": ["27", 0], "shift": params["shift_low"]}},
        }
