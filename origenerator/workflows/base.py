from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property
from pathlib import Path
from typing import Any

from origenerator import points_of_interest
from origenerator.box_breaks import BOX_BREAK, prompt_boxes, unboxed
from origenerator.gallery_contract import SILENT_COPY_ROLE
from origenerator.media import MediaType
from origenerator.workflows.derived_size import measure_derived_size, override_size
from origenerator.workflows.detail_parts import detail_fix_passes, fix_prompts
from origenerator.workflows.fix_finding import finding_nodes, parts_found_by
from origenerator.workflows.frame_rate import NATIVE_FPS, rate_multiplier

SAMPLER_OPTIONS = [
    "euler", "euler_ancestral", "heun", "heunpp2", "dpm_2",
    "dpm_2_ancestral", "lms", "dpm_fast", "dpm_adaptive",
    "dpmpp_2s_ancestral", "dpmpp_sde", "dpmpp_sde_gpu",
    "dpmpp_2m", "dpmpp_2m_sde", "dpmpp_2m_sde_gpu",
    "dpmpp_3m_sde", "dpmpp_3m_sde_gpu", "ddpm", "lcm", "ddim",
    "uni_pc", "uni_pc_bh2",
]
SCHEDULER_OPTIONS = [
    "normal", "karras", "exponential", "sgm_uniform", "simple",
    "ddim_uniform", "beta",
]

DURATION_OPTIONS = [1, 5, 10, 15, 30, 60]
LONGEST_VIDEO_FRAMES = 961
# One window's activations grow with its length: 165 frames at the video pixel budget is 10.5 GB and
# 481 is 31 GB on the 16 GB graphics card, which Windows pages through system RAM at a crawl.
SINGLE_WINDOW_FRAMES = 161
SCENE_BREAK = "---"
FRAME_RATE_OPTIONS = [16, 32, 48, 64, 80, 96, 112]

RIFE_CHECKPOINT = "rife47.pth"
# The node's own default: it clears the CUDA cache after this many frames.
_RIFE_CACHE_FRAMES = 10

UPSCALE_MODEL_FACTOR = 4.0

_DETAIL_GUIDE_SIZE = 512
_DETAIL_MAX_SIZE = 1024
_DETAIL_FEATHER = 5

_SIZE_SCALE, _SIZE_GET = "size_scale", "size_get"
_ENH_LOADER, _ENH_UPSCALE, _ENH_RESCALE = "enh_loader", "enh_upscale", "enh_rescale"
_ENH_ENCODE, _ENH_SAMPLER, _ENH_DECODE = "enh_encode", "enh_sampler", "enh_decode"


def _text_encode(clip_ref, text: str) -> dict:
    return {"class_type": "CLIPTextEncode", "inputs": {"clip": clip_ref, "text": text}}


def ahead_of(own: str, prompt: str) -> str:
    return ", ".join(text for text in (own, prompt) if text)


def _without_box_breaks(value):
    if isinstance(value, str):
        return unboxed(value)
    if isinstance(value, dict):
        return {key: _without_box_breaks(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_without_box_breaks(item) for item in value]
    return value


def prompt_conditioning(node_id: str, clip_ref, text: str, *, ahead: str = "") -> dict:
    if BOX_BREAK not in ahead + text:
        return {node_id: _text_encode(clip_ref, ahead_of(ahead, text))}
    pieces = [piece for piece in (*prompt_boxes(ahead), *prompt_boxes(text))
              if piece.strip()] or [""]
    if len(pieces) == 1:
        return {node_id: _text_encode(clip_ref, pieces[0])}
    nodes = {f"{node_id}_box{index}": _text_encode(clip_ref, piece)
             for index, piece in enumerate(pieces, start=1)}
    joined = [f"{node_id}_box1", 0]
    for index in range(2, len(pieces) + 1):
        join_id = node_id if index == len(pieces) else f"{node_id}_join{index}"
        nodes[join_id] = {"class_type": "ConditioningConcat", "inputs": {
            "conditioning_to": joined, "conditioning_from": [f"{node_id}_box{index}", 0]}}
        joined = [join_id, 0]
    return nodes


@dataclass(frozen=True)
class SizedInput:
    nodes: dict
    image: list
    width: object
    height: object


@dataclass(frozen=True)
class EnhanceTail:
    nodes: dict
    image: list
    upscaled: list


@dataclass(frozen=True)
class LoraChain:
    nodes: dict
    model: list
    clip_ref: list | None


def story_of(scenes: list[str]) -> str:
    return f"\n{SCENE_BREAK}\n".join(scenes)


def chained_frames(lengths: list[int]) -> int:
    return lengths[0] + sum(length - 1 for length in lengths[1:])


def chained_to(total: int, lengths: list[int], shortest: int) -> list[int]:
    fitted = list(lengths)
    fitted[-1] += max(0, total - chained_frames(fitted))
    for index in reversed(range(len(fitted))):
        fitted[index] -= max(0, min(chained_frames(fitted) - total, fitted[index] - shortest))
    return fitted


def scene_prompts(text: str) -> list[str]:
    lines = text.split("\n")
    if not any(line.strip() == SCENE_BREAK for line in lines):
        return [text]
    scenes: list[str] = []
    current: list[str] = []
    for line in lines:
        if line.strip() == SCENE_BREAK:
            scenes.append("\n".join(current).strip())
            current = []
        else:
            current.append(line)
    scenes.append("\n".join(current).strip())
    return scenes


def scene_text(texts: list[str], scene: int) -> str:
    return texts[min(scene, len(texts) - 1)]


class ParamType(StrEnum):
    STR = "str"
    INT = "int"
    FLOAT = "float"
    SEED = "seed"
    DROPDOWN = "dropdown"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    BOOL = "bool"
    SCENES = "scenes"
    LINES = "lines"
    FIXES = "fixes"


@dataclass
class ParamDef:
    key: str
    label: str
    type: ParamType
    default: Any
    options: list | None = None
    min_val: float | None = None
    max_val: float | None = None
    step: float | None = None
    multiline: bool = False
    browse_dir: Path | None = None
    unit: str = ""
    rate: float | None = None
    also_sets: tuple[str, ...] = ()
    good: tuple[float, float] | None = None
    beside_model: str = ""
    folder: str = ""

    def __post_init__(self):
        self.type = ParamType(self.type)


def sampler_params(defaults: dict) -> list[ParamDef]:
    return [
        ParamDef("sampler_name", "Sampler", ParamType.DROPDOWN, defaults["sampler_name"],
                 options=SAMPLER_OPTIONS),
        ParamDef("scheduler", "Step Spacing", ParamType.DROPDOWN, defaults["scheduler"],
                 options=SCHEDULER_OPTIONS),
    ]


class WorkflowTemplate(ABC):
    name: str
    version: str
    display_name: str
    output_type: MediaType
    looping: bool = False
    derives_size_from_input: bool = False
    derived_size_source: str = "input_image"
    selectable: bool = True
    generates_here: bool = True
    model_keys: tuple[str, ...] = ()
    lora_keys: tuple[str, ...] = ()
    text_reader: str | None = None
    loras_keyed_only_when_named: tuple[str, ...] = ()
    extra_enhance_keys: tuple[str, ...] = ()
    output_node_id: str
    base_output_node_id: str | None = None

    @abstractmethod
    def default_params(self) -> dict:
        pass

    @abstractmethod
    def param_definitions(self) -> list[ParamDef]:
        pass

    def derived_display_size(self, params: dict) -> tuple[int, int] | None:
        if not self.derives_size_from_input:
            return None
        return measure_derived_size(params.get("input_image", ""))

    def seed_keys(self) -> tuple[str, ...]:
        return self._seed_keys

    @cached_property
    def _seed_keys(self) -> tuple[str, ...]:
        return tuple(pd.key for pd in self.param_definitions() if pd.type == ParamType.SEED)

    def missing_inputs(self, params: dict) -> list[str]:
        return [label for key, label in self.input_params
                if not str(params.get(key) or "").strip()]

    @cached_property
    def input_params(self) -> tuple[tuple[str, str], ...]:
        return tuple((pd.key, pd.label) for pd in self.param_definitions()
                     if pd.type in (ParamType.IMAGE, ParamType.VIDEO))

    def starts_from_an_image(self) -> bool:
        return "input_image" in self.default_params()

    def pins_reused_seed(self) -> bool:
        return self.output_type != MediaType.VIDEO

    def enhance_keys(self) -> tuple[str, ...]:
        named = tuple(pd.key for pd in self.param_definitions()
                      if pd.key == "enhance" or pd.key.startswith("enhance_"))
        return named + self.extra_enhance_keys

    @abstractmethod
    def build_api_payload(self, params: dict) -> dict:
        pass

    def tells_a_story(self) -> bool:
        return any(pd.type == ParamType.SCENES for pd in self.param_definitions())

    def payload_for_comfyui(self, params: dict) -> dict:
        return _without_box_breaks(self.build_api_payload(params))

    def authored_actions(self, params: dict) -> list[dict] | None:
        return None

    @staticmethod
    def lora_chain(node_id: str, model_ref, loras, clip_ref=None) -> LoraChain:
        nodes: dict = {}
        for index, (lora_name, strength) in enumerate(loras):
            loader_id = node_id if index == 0 else f"{node_id}_{index + 1}"
            if clip_ref is None:
                nodes[loader_id] = {"class_type": "LoraLoaderModelOnly", "inputs": {
                    "model": model_ref, "lora_name": lora_name, "strength_model": strength}}
            else:
                nodes[loader_id] = {"class_type": "LoraLoader", "inputs": {
                    "model": model_ref, "clip": clip_ref, "lora_name": lora_name,
                    "strength_model": strength, "strength_clip": strength}}
                clip_ref = [loader_id, 1]
            model_ref = [loader_id, 0]
        return LoraChain(nodes, model_ref, clip_ref)

    @staticmethod
    def scene_prompt_nodes(index: int, scene: int, scenes: list[str], clip_ref, first_ref,
                           role: str = "prompt"):
        text = scene_text(scenes, scene)
        if index == 0 or text == scenes[0]:
            return {}, first_ref
        node_id = f"s{index}_{role}"
        return {node_id: _text_encode(clip_ref, text)}, [node_id, 0]

    @classmethod
    def scene_plan(cls, params: dict) -> list[tuple[int, int]]:
        return [(length, scene)
                for scene, count in enumerate(cls.scene_lengths(params))
                for length in cls.segment_lengths(count)]

    @staticmethod
    def scene_lengths(params: dict) -> list[int]:
        frames = [int(count) for count in (params.get("scene_frames") or [])]
        if len(frames) <= 1:
            frames = [int(params["frame_count"])]
        return frames

    @staticmethod
    def video_frames(plan: list[tuple[int, int]]) -> int:
        return chained_frames([length for length, _ in plan])

    @staticmethod
    def segment_lengths(frame_count: int) -> list[int]:
        lengths = [min(frame_count, SINGLE_WINDOW_FRAMES)]
        remaining = frame_count - lengths[0]
        while remaining > 0:
            length = min(SINGLE_WINDOW_FRAMES, remaining + 1)
            lengths.append(length)
            remaining -= length - 1
        return lengths

    @classmethod
    def chain_segments(cls, params: dict, start_ref, render):
        plan = cls.scene_plan(params)
        first_length, first_scene = plan[0]
        nodes, frames = render(0, first_scene, start_ref, first_length, len(plan) == 1,
                               previous=None)
        joined, previous, previous_length = frames, frames, first_length
        for index, (length, scene) in enumerate(plan[1:], start=1):
            prefix = f"s{index}_"
            nodes[prefix + "last"] = {
                "class_type": "ImageFromBatch",
                "inputs": {"image": previous, "batch_index": previous_length - 1, "length": 1},
            }
            segment, frames = render(index, scene, [prefix + "last", 0], length,
                                     index == len(plan) - 1, previous=previous)
            nodes.update(segment)
            nodes[prefix + "new"] = {
                "class_type": "ImageFromBatch",
                "inputs": {"image": frames, "batch_index": 1, "length": length - 1},
            }
            nodes[prefix + "join"] = {
                "class_type": "ImageBatch",
                "inputs": {"image1": joined, "image2": [prefix + "new", 0]},
            }
            joined, previous, previous_length = [prefix + "join", 0], frames, length
        return nodes, joined, cls.video_frames(plan)

    @staticmethod
    def image_size_nodes(image_ref, params: dict, megapixels: float = 0.4) -> SizedInput:
        override = override_size(params)
        if override is not None:
            width, height = override
            nodes = {
                _SIZE_SCALE: {
                    "class_type": "ImageScale",
                    "inputs": {
                        "image": image_ref,
                        "upscale_method": "lanczos",
                        "width": width,
                        "height": height,
                        "crop": "disabled",
                    },
                },
            }
            return SizedInput(nodes, [_SIZE_SCALE, 0], width, height)
        nodes = {
            _SIZE_SCALE: {
                "class_type": "ImageScaleToTotalPixels",
                "inputs": {
                    "image": image_ref,
                    "upscale_method": "lanczos",
                    "megapixels": megapixels,
                    "resolution_steps": 16,
                },
            },
            _SIZE_GET: {
                "class_type": "GetImageSize",
                "inputs": {"image": [_SIZE_SCALE, 0]},
            },
        }
        return SizedInput(nodes, [_SIZE_SCALE, 0], [_SIZE_GET, 0], [_SIZE_GET, 1])

    @staticmethod
    def controlnet_nodes(loader_id: str, union_id: str, *, controlnet: str,
                         head: str) -> tuple[dict, list]:
        nodes = {
            loader_id: {
                "class_type": "ControlNetLoader",
                "inputs": {"control_net_name": controlnet},
            },
        }
        if "union" not in controlnet.lower():
            return nodes, [loader_id, 0]
        nodes[union_id] = {
            "class_type": "SetUnionControlNetType",
            "inputs": {"control_net": [loader_id, 0], "type": head},
        }
        return nodes, [union_id, 0]

    @staticmethod
    def enhance_image_nodes(*, image_ref, model_ref, positive_ref, negative_ref,
                            vae_ref, params: dict,
                            rescale_to: tuple[int, int] | None = None) -> EnhanceTail:
        if rescale_to is None:
            rescale = {
                "class_type": "ImageScaleBy",
                "inputs": {
                    "image": [_ENH_UPSCALE, 0],
                    "upscale_method": "lanczos",
                    "scale_by": params["enhance_scale"] / UPSCALE_MODEL_FACTOR,
                },
            }
        else:
            width, height = rescale_to
            rescale = {
                "class_type": "ImageScale",
                "inputs": {
                    "image": [_ENH_UPSCALE, 0],
                    "upscale_method": "lanczos",
                    "width": width,
                    "height": height,
                    "crop": "disabled",
                },
            }
        nodes = {
            _ENH_LOADER: {
                "class_type": "UpscaleModelLoader",
                "inputs": {"model_name": params["upscale_model"]},
            },
            _ENH_UPSCALE: {
                "class_type": "ImageUpscaleWithModel",
                "inputs": {"upscale_model": [_ENH_LOADER, 0], "image": image_ref},
            },
            _ENH_RESCALE: rescale,
            _ENH_ENCODE: {
                "class_type": "VAEEncode",
                "inputs": {"pixels": [_ENH_RESCALE, 0], "vae": vae_ref},
            },
            _ENH_SAMPLER: {
                "class_type": "KSampler",
                "inputs": {
                    "model": model_ref,
                    "positive": positive_ref,
                    "negative": negative_ref,
                    "latent_image": [_ENH_ENCODE, 0],
                    "seed": params["seed"],
                    "steps": params["enhance_steps"],
                    "cfg": params["cfg"],
                    "sampler_name": params["sampler_name"],
                    "scheduler": params["scheduler"],
                    "denoise": params["enhance_denoise"],
                },
            },
            _ENH_DECODE: {
                "class_type": "VAEDecode",
                "inputs": {"samples": [_ENH_SAMPLER, 0], "vae": vae_ref},
            },
        }
        return EnhanceTail(nodes, [_ENH_DECODE, 0], [_ENH_UPSCALE, 0])

    @staticmethod
    def detail_fix_nodes(*, image_ref, model_ref, clip_ref, vae_ref,
                         positive_ref, negative_ref, params: dict):
        nodes: dict = {}
        prompts = fix_prompts(params)
        original = image_ref
        for index, fix in enumerate(detail_fix_passes(params)):
            found, segs_ref = finding_nodes(index, fix, image_ref, original)
            nodes.update(found)
            detailer_id = f"fix{index}_detailer"
            own = prompts[fix.part.name]
            fixed = WorkflowTemplate.lora_chain(
                f"fix{index}_lora", model_ref,
                [(own["lora"], own["strength"])] if own["lora"] else [], clip_ref=clip_ref)
            nodes.update(fixed.nodes)
            model, fixed_clip_ref = fixed.model, fixed.clip_ref
            positive, negative = positive_ref, negative_ref
            if own["prompt"] or own["avoid"] or own["lora"]:
                positive_id, negative_id = f"fix{index}_positive", f"fix{index}_negative"
                nodes.update(prompt_conditioning(positive_id, fixed_clip_ref, params["positive_prompt"],
                                                 ahead=own["prompt"]))
                nodes.update(prompt_conditioning(negative_id, fixed_clip_ref, params["negative_prompt"],
                                                 ahead=own["avoid"]))
                positive, negative = [positive_id, 0], [negative_id, 0]
            nodes[detailer_id] = {
                "class_type": "DetailerForEach",
                "_meta": {"title": f"{fix.part.name.capitalize()} fix"},
                "inputs": {
                    "image": image_ref,
                    "segs": segs_ref,
                    "model": model,
                    "clip": fixed_clip_ref,
                    "vae": vae_ref,
                    "guide_size": _DETAIL_GUIDE_SIZE,
                    "guide_size_for": True,
                    "max_size": _DETAIL_MAX_SIZE,
                    "seed": params["seed"],
                    "steps": params["enhance_steps"],
                    "cfg": params["cfg"],
                    "sampler_name": params["sampler_name"],
                    "scheduler": params["scheduler"],
                    "positive": positive,
                    "negative": negative,
                    "denoise": fix.denoise,
                    "feather": _DETAIL_FEATHER,
                    "noise_mask": True,
                    "force_inpaint": True,
                    "wildcard": "",
                    "cycle": 1,
                },
            }
            image_ref = [detailer_id, 0]
        return nodes, image_ref

    @staticmethod
    def foley_audio_nodes(model_id: str, deps_id: str, sampler_id: str, frames_ref, params: dict):
        duration = max(1.0, params["frame_count"] / NATIVE_FPS)
        nodes = {
            model_id: {
                "class_type": "HunyuanModelLoader",
                "inputs": {
                    "model_name": params["foley_model"],
                    "precision": "bf16",
                    "quantization": "auto",
                },
            },
            deps_id: {
                "class_type": "HunyuanDependenciesLoader",
                "inputs": {
                    "vae_name": params["foley_vae"],
                    "synchformer_name": params["foley_synchformer"],
                },
            },
            sampler_id: {
                "class_type": "HunyuanFoleySampler",
                "inputs": {
                    "hunyuan_model": [model_id, 0],
                    "hunyuan_deps": [deps_id, 0],
                    "image": frames_ref,
                    "frame_rate": NATIVE_FPS,
                    "duration": duration,
                    "prompt": params["audio_prompt"],
                    "negative_prompt": params["audio_negative_prompt"],
                    "cfg_scale": 4.5,
                    "steps": 50,
                    "sampler": "euler",
                    "batch_size": 1,
                    "seed": params["audio_seed"],
                    "force_offload": True,
                },
            },
        }
        return nodes, [sampler_id, 0]

    @staticmethod
    def speech_window_nodes(prefix: str, line_ref, encoder_ref, offset: int, length: int):
        nodes = {
            prefix + "cut": {
                "class_type": "TrimAudioDuration",
                "inputs": {
                    "audio": line_ref,
                    "start_index": offset / NATIVE_FPS,
                    "duration": length / NATIVE_FPS,
                },
            },
            prefix + "hear": {
                "class_type": "AudioEncoderEncode",
                "inputs": {"audio_encoder": encoder_ref, "audio": [prefix + "cut", 0]},
            },
        }
        return nodes, [prefix + "hear", 0]

    @staticmethod
    def speech_track_nodes(prefix: str, scenes: list[tuple[int, list | None]], foley_ref):
        nodes: dict = {}
        track = None
        last = len(scenes) - 1
        offset = 0
        for index, (frames, line_ref) in enumerate(scenes):
            seconds = (frames if index == last else frames - 1) / NATIVE_FPS
            if line_ref is None:
                node_id = f"{prefix}ambience{index}"
                nodes[node_id] = {
                    "class_type": "TrimAudioDuration",
                    "inputs": {"audio": foley_ref, "start_index": offset / NATIVE_FPS, "duration": seconds},
                }
                piece = [node_id, 0]
            elif index == last:
                piece = line_ref
            else:
                node_id = f"{prefix}cut{index}"
                nodes[node_id] = {
                    "class_type": "TrimAudioDuration",
                    "inputs": {"audio": line_ref, "start_index": 0.0, "duration": seconds},
                }
                piece = [node_id, 0]
            offset += frames - 1
            if track is None:
                track = piece
                continue
            node_id = f"{prefix}join{index}"
            nodes[node_id] = {
                "class_type": "AudioConcat",
                "inputs": {"audio1": track, "audio2": piece, "direction": "after"},
            }
            track = [node_id, 0]
        return nodes, track

    @staticmethod
    def interpolation_nodes(node_id: str, frames_ref, params: dict):
        multiplier = rate_multiplier(params["frame_rate"])
        if multiplier == 1:
            return {}, frames_ref
        nodes = {
            node_id: {
                "class_type": "RIFE VFI",
                "inputs": {
                    "frames": frames_ref,
                    "ckpt_name": RIFE_CHECKPOINT,
                    "multiplier": multiplier,
                    "clear_cache_after_n_frames": _RIFE_CACHE_FRAMES,
                    "fast_mode": True,
                    "ensemble": True,
                    "scale_factor": 1.0,
                },
            },
        }
        return nodes, [node_id, 0]

    def extract_output_info(self, history_data: dict) -> list[dict]:
        outputs = history_data.get("outputs", {})
        files = _listed_files(outputs.get(self.output_node_id, {}))
        places = points_of_interest.reported(outputs, parts_found_by(history_data))
        if files and places is not None:
            files[0] = {**files[0], **points_of_interest.kept(places)}
        files += soundless_copies_of(files)
        if self.base_output_node_id is None:
            return files
        base = _listed_files(outputs.get(self.base_output_node_id, {}))
        return files + [{**f, "role": "original"} for f in base]

    def base_save_node(self, node_id: str, image_ref, params: dict) -> dict:
        if not params.get("enhance"):
            return {}
        return {
            node_id: {
                "class_type": "SaveImage",
                "inputs": {
                    "images": image_ref,
                    "filename_prefix": f"{params['filename_prefix']}_base",
                },
            },
        }


def _listed_files(saved_by_node: dict) -> list[dict]:
    return [*saved_by_node.get("images", []), *saved_by_node.get("gifs", [])]


def soundless_copies_of(saved: list[dict]) -> list[dict]:
    copies = []
    for saved_file in saved:
        stem, dot, ext = (saved_file.get("filename") or "").rpartition(".")
        if dot and stem.endswith("-audio"):
            copies.append({"filename": f"{stem.removesuffix('-audio')}.{ext}",
                           "subfolder": saved_file.get("subfolder", ""),
                           "type": saved_file.get("type", "output"),
                           "role": SILENT_COPY_ROLE})
    return copies
