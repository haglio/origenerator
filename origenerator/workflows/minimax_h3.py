"""What MiniMax H3's two video workflows share: one model, one pass, the
picture and its stereo sound made together, so no foley pass and no frames
filled in between the model's own."""
from __future__ import annotations

from origenerator.comfy_graph import TURBO_TITLE
from origenerator.media import MediaType
from origenerator.workflows.base import ParamDef, ParamType, SizedInput, WorkflowTemplate
from origenerator.workflows.lora_choice import lora_choice
from origenerator.workflows.model_arch import MINIMAX_H3
from origenerator.workflows.model_files import NO_LORA, list_model_files
from origenerator.workflows.video_writer import video_writer

# H3 paces its motion at 24 frames a second on a 17k+5 frame grid, trained
# from 124 frames (five seconds) to 362 (fifteen).
H3_FPS = 24.0
H3_FRAME_STEP = 17
H3_SHORTEST_FRAMES = 5
H3_LONGEST_FRAMES = 362
H3_DURATION_OPTIONS = [5, 10, 15]

_SAMPLER = "res_multistep"
_SCHEDULER = "simple"
_CONDITIONING_ID = "8"


class MiniMaxH3Workflow(WorkflowTemplate):
    output_type = MediaType.VIDEO
    derives_size_from_input = True
    size_stride = 32
    native_fps = H3_FPS
    model_keys = ("unet",)
    lora_keys = ("lora",)
    output_node_id = "16"

    mode: str
    checkpoint: str
    turbo_lora: str
    turbo: bool
    steps: int
    good_steps: tuple[int, int]
    picture_label: str

    def default_params(self) -> dict:
        return {
            "positive_prompt": "",
            "input_image": "",
            "seed": 0,
            "frame_count": 124,
            "steps": self.steps,
            "turbo": self.turbo,
            "lora_strength": 1.0,
            "filename_prefix": f"video/{self.name}",
            "unet": self.checkpoint,
            "lora": NO_LORA,
            "turbo_lora": self.turbo_lora,
            "clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
            "vae_name": "minimax_h3_video_vae_int8_convrot.safetensors",
            "audio_vae_name": "minimax_h3_audio_vae_fp32.safetensors",
            **self.own_defaults(),
        }

    def own_defaults(self) -> dict:
        return {}

    def param_definitions(self) -> list[ParamDef]:
        defaults = self.default_params()
        models = list_model_files("diffusion_models", [defaults["unet"]],
                                  accepts=(MINIMAX_H3,), mode=self.mode)
        return [
            ParamDef("positive_prompt", "Positive Prompt", ParamType.STR,
                     defaults["positive_prompt"], multiline=True),
            ParamDef("input_image", self.picture_label, ParamType.IMAGE, defaults["input_image"]),
            ParamDef("seed", "Seed", ParamType.SEED, defaults["seed"]),
            ParamDef("frame_count", "Duration", ParamType.INT, defaults["frame_count"],
                     min_val=H3_SHORTEST_FRAMES, max_val=H3_LONGEST_FRAMES, step=H3_FRAME_STEP,
                     options=H3_DURATION_OPTIONS, unit="s", rate=H3_FPS,
                     good=(124, H3_LONGEST_FRAMES)),
            ParamDef("steps", "Steps", ParamType.INT, defaults["steps"], min_val=1, max_val=100,
                     good=self.good_steps),
            ParamDef("turbo", "Turbo", ParamType.BOOL, defaults["turbo"]),
            ParamDef("unet", "Model", ParamType.COMBO, defaults["unet"], options=models),
            *lora_choice(defaults, "lora", "lora_strength", accepts=(MINIMAX_H3,), mode=self.mode),
        ]

    def conditioning_nodes(self, params: dict, sized: SizedInput) -> dict:
        raise NotImplementedError

    def build_api_payload(self, params: dict) -> dict:
        sized = self.image_size_nodes(["1", 0], params)
        turbo, model_ref = self.lora_model_input(
            "5", ["4", 0], params["turbo_lora"] if params["turbo"] else NO_LORA, 1.0)
        for node in turbo.values():
            node["_meta"] = {"title": TURBO_TITLE}
        lora, model_ref = self.lora_model_input(
            "6", model_ref, params["lora"], params["lora_strength"])
        return {
            **sized.nodes,
            **turbo,
            **lora,
            **self.conditioning_nodes(params, sized),
            "1": {"class_type": "LoadImage", "inputs": {"image": params["input_image"]}},
            "2": {
                "class_type": "CLIPLoader",
                "inputs": {"clip_name": params["clip_name"], "type": "minimax", "device": "default"},
            },
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": params["vae_name"]}},
            "4": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": params["unet"], "weight_dtype": "default"},
            },
            "7": {"class_type": "VAELoader", "inputs": {"vae_name": params["audio_vae_name"]}},
            "9": {"class_type": "RandomNoise", "inputs": {"noise_seed": params["seed"]}},
            "10": {
                "class_type": "BasicGuider",
                "inputs": {"model": model_ref, "conditioning": [_CONDITIONING_ID, 0]},
            },
            "11": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": _SAMPLER}},
            "12": {
                "class_type": "BasicScheduler",
                "inputs": {"model": model_ref, "scheduler": _SCHEDULER, "steps": params["steps"],
                           "denoise": 1.0},
            },
            "13": {
                "class_type": "SamplerCustomAdvanced",
                "inputs": {
                    "noise": ["9", 0],
                    "guider": ["10", 0],
                    "sampler": ["11", 0],
                    "sigmas": ["12", 0],
                    "latent_image": [_CONDITIONING_ID, 1],
                },
            },
            "14": {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["3", 0]}},
            "15": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["13", 0], "vae": ["7", 0]}},
            self.output_node_id: video_writer(["14", 0], ["15", 0], params, rate=self.native_fps),
        }

    @staticmethod
    def conditioning(class_type: str, inputs: dict) -> dict:
        return {_CONDITIONING_ID: {"class_type": class_type, "inputs": inputs}}
