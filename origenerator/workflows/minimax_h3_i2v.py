from __future__ import annotations

from origenerator.media import MediaType
from origenerator.workflows.base import (
    DURATION_OPTIONS,
    ParamDef,
    ParamType,
    WorkflowTemplate,
)
from origenerator.workflows.frame_rate import MAX_PLAYBACK_FPS, rate_options
from origenerator.workflows.lora_rows import LORA_KEYS, lora_defaults, lora_rows, picked_loras
from origenerator.workflows.model_arch import MINIMAX_H3
from origenerator.workflows.model_dropdowns import model_dropdown
from origenerator.workflows.parts import Segment
from origenerator.workflows.prompt_readers import QWEN3VL
from origenerator.workflows.video_writer import video_writer

H3_FPS = 24.0
_FIRST_FRAMES = 5
_FRAMES_PER_STEP = 17
_LONGEST_IT_WAS_TRAINED_ON = 362
_MEGAPIXELS = 0.6
_SIZE_STEPS = 32


def frames_on_the_models_steps(frames: int) -> int:
    steps_past_the_first = -(-max(0, frames - _FIRST_FRAMES) // _FRAMES_PER_STEP)
    return _FIRST_FRAMES + steps_past_the_first * _FRAMES_PER_STEP


_LONGEST_FRAMES = frames_on_the_models_steps(int(max(DURATION_OPTIONS) * H3_FPS))


class MiniMaxH3I2vWorkflow(WorkflowTemplate):
    name = "minimax_h3_i2v"
    version = "v001"
    display_name = "MiniMax H3 I2V"
    output_type = MediaType.VIDEO
    derives_size_from_input = True
    native_fps = H3_FPS
    video_model = "MiniMax H3"
    model_keys = ("unet",)
    lora_keys = LORA_KEYS
    text_reader = QWEN3VL
    loras_keyed_only_when_named = LORA_KEYS[1:]
    output_node_id = "19"

    def default_params(self) -> dict:
        return {
            "positive_prompt": "",
            "input_image": "",
            "noise_seed": 0,
            "frame_count": frames_on_the_models_steps(int(5 * H3_FPS)),
            "steps": 20,
            "sampler_name": "res_multistep",
            "scheduler": "simple",
            "frame_rate": H3_FPS,
            "unet": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
            **lora_defaults(LORA_KEYS),
            "clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
            "vae_name": "minimax_h3_video_vae_fp16.safetensors",
            "audio_vae_name": "minimax_h3_audio_vae_fp32.safetensors",
            "filename_prefix": "video/minimax_h3_i2v",
        }

    def param_definitions(self) -> list[ParamDef]:
        defaults = self.default_params()
        rates = rate_options(H3_FPS)
        return [
            ParamDef("positive_prompt", "Positive Prompt", ParamType.STR, defaults["positive_prompt"], multiline=True),
            ParamDef("input_image", "Start Image", ParamType.IMAGE, defaults["input_image"]),
            ParamDef("noise_seed", "Seed", ParamType.SEED, defaults["noise_seed"]),
            ParamDef("frame_count", "Duration", ParamType.INT, defaults["frame_count"], min_val=_FIRST_FRAMES,
                     max_val=_LONGEST_FRAMES, step=_FRAMES_PER_STEP, options=DURATION_OPTIONS,
                     unit="s", shown_in_seconds_at=H3_FPS, good=(124, _LONGEST_IT_WAS_TRAINED_ON)),
            ParamDef("steps", "Steps", ParamType.INT, defaults["steps"], min_val=1, max_val=100, good=(6, 20)),
            model_dropdown("unet", "Model", defaults["unet"], "diffusion_models", accepts=(MINIMAX_H3,)),
            *lora_rows(defaults, LORA_KEYS, accepts=(MINIMAX_H3,)),
            ParamDef("frame_rate", "Frame Rate", ParamType.FLOAT, defaults["frame_rate"],
                     min_val=H3_FPS, max_val=min(MAX_PLAYBACK_FPS, max(rates)), step=H3_FPS,
                     options=rates, unit="fps"),
        ]

    @staticmethod
    def segment_lengths(frame_count: int) -> list[int]:
        lengths = [frames_on_the_models_steps(min(frame_count, _LONGEST_IT_WAS_TRAINED_ON))]
        made = lengths[0]
        while made < frame_count:
            lengths.append(frames_on_the_models_steps(
                min(_LONGEST_IT_WAS_TRAINED_ON, frame_count - made + 1)))
            made += lengths[-1] - 1
        return lengths

    def build_api_payload(self, params: dict) -> dict:
        loras = self.lora_chain("4", ["1", 0], picked_loras(params, LORA_KEYS))
        sized = self.image_size_nodes(["12", 0], params, _MEGAPIXELS, _SIZE_STEPS)
        sounds: list[list] = []

        def segment(at: Segment):
            prefix = "" if at.index == 0 else f"s{at.index}_"
            ids = {part: prefix + part for part in ("h3", "noise", "schedule", "guide", "sample",
                                                    "decode", "sound")}
            sounds.append([ids["sound"], 0])
            return {
                ids["h3"]: {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
                    "clip": ["2", 0], "vae": ["3", 0], "prompt": params["positive_prompt"],
                    "width": sized.width, "height": sized.height, "length": at.length,
                    "first_frame": at.start}},
                ids["noise"]: {"class_type": "RandomNoise",
                               "inputs": {"noise_seed": params["noise_seed"] + at.index}},
                ids["schedule"]: {"class_type": "BasicScheduler", "inputs": {
                    "model": loras.model, "scheduler": params["scheduler"], "steps": params["steps"],
                    "denoise": 1.0}},
                ids["guide"]: {"class_type": "BasicGuider",
                               "inputs": {"model": loras.model, "conditioning": [ids["h3"], 0]}},
                ids["sample"]: {"class_type": "SamplerCustomAdvanced", "inputs": {
                    "noise": [ids["noise"], 0], "guider": [ids["guide"], 0], "sampler": ["15", 0],
                    "sigmas": [ids["schedule"], 0], "latent_image": [ids["h3"], 1]}},
                ids["decode"]: {"class_type": "VAEDecode",
                                "inputs": {"samples": [ids["sample"], 0], "vae": ["3", 0]}},
                ids["sound"]: {"class_type": "VAEDecodeAudio",
                               "inputs": {"samples": [ids["sample"], 0], "vae": ["5", 0]}},
            }, [ids["decode"], 0]

        segments, decoded_ref, _frames = self.chain_segments(params, sized.image, segment)
        sound_nodes, sound_ref = self._joined(sounds)
        interpolate, frames_ref = self.interpolation_nodes("25", decoded_ref, params)
        return {
            **sized.nodes,
            **loras.nodes,
            **segments,
            **sound_nodes,
            **interpolate,
            "1": {"class_type": "UNETLoader",
                  "inputs": {"unet_name": params["unet"], "weight_dtype": "default"}},
            "2": {"class_type": "CLIPLoader",
                  "inputs": {"clip_name": params["clip_name"], "type": "minimax", "device": "default"}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": params["vae_name"]}},
            "5": {"class_type": "VAELoader", "inputs": {"vae_name": params["audio_vae_name"]}},
            "12": {"class_type": "LoadImage", "inputs": {"image": params["input_image"]}},
            "15": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": params["sampler_name"]}},
            self.output_node_id: video_writer(frames_ref, sound_ref, params, H3_FPS),
        }

    @staticmethod
    def _joined(sounds: list[list]) -> tuple[dict, list]:
        nodes: dict = {}
        joined = sounds[0]
        for index, sound in enumerate(sounds[1:], start=1):
            node_id = f"s{index}_sound_join"
            nodes[node_id] = {"class_type": "AudioConcat",
                              "inputs": {"audio1": joined, "audio2": sound, "direction": "after"}}
            joined = [node_id, 0]
        return nodes, joined
