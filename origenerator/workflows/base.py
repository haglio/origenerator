from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property
from pathlib import Path
from typing import Any

from origenerator import points_of_interest
from origenerator.gallery_contract import SILENT_COPY_ROLE
from origenerator.media import MediaType
from origenerator.workflows.derived_size import measure_derived_size, override_size
from origenerator.workflows.detail_parts import detail_fix_passes, fix_prompts
from origenerator.workflows.fix_finding import finding_nodes, parts_found_by
from origenerator.workflows.frame_rate import NATIVE_FPS, rate_multiplier

# ComfyUI's KSampler vocabulary, which the SDXL pair's pickers offer.
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

# What a video form's Duration and Frame Rate dropdowns offer; both take a
# typed value too. Every rate is a whole multiple of the models' native one,
# because those are the rates the frame interpolator can produce the frames for
# — see :mod:`origenerator.workflows.frame_rate`.
DURATION_OPTIONS = [1, 5, 10, 15, 30, 60]
# The longest of those, in frames at the native rate on the models' 4k+1 grid.
LONGEST_CLIP_FRAMES = 961
# Sampled as one window, a clip's activations grow with its length: measured
# on the 16 GB card, 165 frames at the video pixel budget is 10.5 GB and 481
# is 31 GB, which Windows pages through system RAM at a crawl rather than
# refusing. A longer clip is rendered as a chain of clips this long, each
# started from the last frame of the one before -- :meth:`WorkflowTemplate.
# chain_segments`.
SINGLE_WINDOW_FRAMES = 161
# A line holding only this, in a long clip's positive prompt, ends one scene's
# text and starts the next: each segment reads its own scene, and the last
# scene carries on through the segments after it (scene_prompts).
SCENE_BREAK = "---"
FRAME_RATE_OPTIONS = [16, 32, 48, 64, 80, 96, 112]

# The interpolation model that fills in the frames between the generated ones
# (see :meth:`WorkflowTemplate.interpolation_nodes`). RIFE 4.7 is the pack's own
# recommendation and its default; a setting here would be one more question whose
# answer is a guess, so it is a constant like the detector settings below.
RIFE_CHECKPOINT = "rife47.pth"
# How many source frames the interpolator processes before clearing the CUDA
# cache — the node's own default, and the one thing standing between a long clip
# at a high multiplier and an out-of-memory.
_RIFE_CACHE_FRAMES = 10

# The native factor of the installed ESRGAN-family upscale models (both are 4x).
# The enhance tail rescales the model's output DOWN from this to the requested
# ``enhance_scale``, so the saved image lands at enhance_scale x the base render.
UPSCALE_MODEL_FACTOR = 4.0

# The detail pass's fixed shape (see :meth:`WorkflowTemplate.detail_fix_nodes`).
# All of these are the detailer node's own defaults, kept here as named
# constants rather than as settings: the pass already costs the user a tick and
# a denoise, and every one of these is a value their answer would be a guess at.
_DETAIL_GUIDE_SIZE = 512      # each crop is enlarged to this before sampling
_DETAIL_MAX_SIZE = 1024       # …but never past this, which is where VRAM goes
_DETAIL_FEATHER = 5           # pixels the repaint fades over on the way back in

# The node ids the shared fragments below build under. Named rather than
# numbered, and allocated by the fragment rather than by its caller: a payload
# is assembled by merging fragments into one dict, so an id a caller invented
# for a fragment could silently overwrite one of the caller's own nodes and
# leave the link that pointed at it naming something else. Numbers were tracked
# by hand in comments ("21 is the union ControlNet and 22/23 the depth pair, so
# this sits clear of both"); a name a workflow's own graph never uses cannot
# collide at all.
_SIZE_SCALE, _SIZE_GET = "size_scale", "size_get"
_ENH_LOADER, _ENH_UPSCALE, _ENH_RESCALE = "enh_loader", "enh_upscale", "enh_rescale"
_ENH_ENCODE, _ENH_SAMPLER, _ENH_DECODE = "enh_encode", "enh_sampler", "enh_decode"


def _text_encode(clip_ref, text: str) -> dict:
    return {"class_type": "CLIPTextEncode", "inputs": {"clip": clip_ref, "text": text}}


def ahead_of(own: str, prompt: str) -> str:
    return ", ".join(text for text in (own, prompt) if text)


@dataclass(frozen=True)
class SizedInput:
    """The nodes that size a run off its input image, and what reads them:
    ``image`` the scaled image's ref, ``width``/``height`` either a ref into
    the size node or the literal the user pinned."""

    nodes: dict
    image: list
    width: object
    height: object


@dataclass(frozen=True)
class EnhanceTail:
    """The upscale/enhance tail's nodes and the two images it makes: ``image``
    the re-sampled result a save node stores, and ``upscaled`` the plain model
    upscale before it — which is the whole output of the workflow named for it
    (Flux), kept alongside rather than discarded."""

    nodes: dict
    image: list
    upscaled: list


@dataclass(frozen=True)
class LoraChain:
    nodes: dict
    model: list
    clip: list | None


def story_of(scenes: list[str]) -> str:
    """The one positive prompt that stores ``scenes``: their texts with a
    :data:`SCENE_BREAK` line between each -- what :func:`scene_prompts` splits."""
    return f"\n{SCENE_BREAK}\n".join(scenes)


def chained_frames(lengths: list[int]) -> int:
    """How many frames pieces chained from each other's last frame add up to:
    each after the first starts on the frame before it, so counts once."""
    return lengths[0] + sum(length - 1 for length in lengths[1:])


def chained_to(total: int, lengths: list[int], shortest: int) -> list[int]:
    fitted = list(lengths)
    fitted[-1] += max(0, total - chained_frames(fitted))
    for index in reversed(range(len(fitted))):
        fitted[index] -= max(0, min(chained_frames(fitted) - total, fitted[index] - shortest))
    return fitted


def scene_prompts(text: str) -> list[str]:
    """The scenes a positive prompt tells, split at :data:`SCENE_BREAK` lines --
    or the one prompt exactly as typed when it has none."""
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
    COMBO = "combo"
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
    # A "combo" picks one of these; an "int"/"float" with them is an editable
    # dropdown of common values that still takes any typed one.
    options: list | None = None
    min_val: float | None = None
    max_val: float | None = None
    step: float | None = None
    multiline: bool = False
    # Where an "image" field's Browse dialog opens when the field is empty (a
    # field already holding an image still opens at that image). ``None`` leaves
    # it at ComfyUI's input folder — the right home for workflows fed by
    # generated frames; a workflow whose sources live in a folder of the library
    # names that folder instead.
    browse_dir: Path | None = None
    # Shown after a preset dropdown's numbers ("48 fps"); typing the bare
    # number is accepted.
    unit: str = ""
    # For an "int" frame count: the frames per second it counts, so the form can
    # show and edit it as seconds. ``options`` are then seconds; min/max/step
    # stay frames. This is the rate the MODEL paces motion at, not the rate the
    # file is played at — the frames are generated at the one and interpolated up
    # to the other, so a clip's seconds don't move when its rate does.
    rate: float | None = None
    also_sets: tuple[str, ...] = ()
    good: tuple[float, float] | None = None

    def __post_init__(self):
        self.type = ParamType(self.type)


def sampler_params(defaults: dict) -> list[ParamDef]:
    return [
        ParamDef("sampler_name", "Sampler", ParamType.COMBO, defaults["sampler_name"],
                 options=SAMPLER_OPTIONS),
        ParamDef("scheduler", "Step Spacing", ParamType.COMBO, defaults["scheduler"],
                 options=SCHEDULER_OPTIONS),
    ]


class WorkflowTemplate(ABC):
    name: str
    version: str
    display_name: str
    output_type: MediaType
    looping: bool = False
    # True when the output size is derived from the input image (kept at its
    # aspect ratio on a fixed pixel budget) rather than set by hand. The i2v
    # workflows set this; the Generate form then shows the derived width/height in
    # a locked Dimensions field the user can unlock to override. Width/height stay
    # out of ``default_params`` (the size isn't a stored setting), so an
    # override never splits a gallery folder from an otherwise identical run.
    derives_size_from_input: bool = False
    # Which input a size-deriving workflow takes its shape from.
    derived_size_source: str = "input_image"
    # False for machinery workflows the user never picks by hand (the standalone
    # image enhancer, launched by the gallery's enhance buttons): they stay out
    # of the Generate tab's workflow dropdown but remain registered — payloads
    # still build, in-flight rows still reconnect and caption themselves.
    selectable: bool = True
    generates_here: bool = True
    # The param key(s) whose values identify which model produced an output.
    # The gallery groups a workflow's generations into model folders by these.
    model_keys: tuple[str, ...] = ()
    # The param key(s) whose values identify which LoRA(s) a run used. The gallery
    # nests a LoRA folder level beneath each model folder, so runs that differ only
    # in LoRA (same base model) split there. Empty for workflows with no LoRA; the
    # gallery then collapses that level to a single "(no LoRA)" folder.
    lora_keys: tuple[str, ...] = ()
    loras_keyed_only_when_named: tuple[str, ...] = ()
    # Param keys the enhance tail reads that the ``enhance``/``enhance_*`` naming
    # doesn't already cover, so they join :meth:`enhance_keys` and stay out of the
    # gallery's grouping. The SDXL and WAN t2i workflows list ``upscale_model``
    # here: it loads the tail's upscaler and does nothing with the toggle off.
    # Flux does not — there the same param also drives the plain 4x upscale that
    # is that workflow's namesake output, so it stays part of the settings.
    extra_enhance_keys: tuple[str, ...] = ()
    output_node_id: str
    # The node that saves the pre-enhance render, present in the payload only
    # when the inline enhance tail ran (see :meth:`base_save_node`). Its files
    # are appended after the primary ones and tagged as the original, so a row
    # made with the tail on carries both versions — the enhanced one leading,
    # the base one reachable — exactly like a standalone enhance folded in.
    base_output_node_id: str | None = None

    @abstractmethod
    def default_params(self) -> dict:
        """Return dict of param_name -> default_value."""

    @abstractmethod
    def param_definitions(self) -> list[ParamDef]:
        """Return ordered list of ParamDef for the UI form builder."""

    def derived_display_size(self, params: dict) -> tuple[int, int] | None:
        """The width×height this run's input image derives, for the form to show
        in its locked Dimensions field, or ``None`` when the size isn't derived
        (a manual-size workflow) or the image can't be measured yet (none picked,
        missing, unreadable) — the form then shows no size until one resolves.

        Measured app-side (:func:`~origenerator.workflows.derived_size.
        measure_derived_size`) to exactly match what the in-graph WAN 2.2 scaling
        produces, so the number shown is the number the run will use.
        """
        if not self.derives_size_from_input:
            return None
        return measure_derived_size(params.get("input_image", ""))

    def seed_keys(self) -> tuple[str, ...]:
        """Param keys whose type is ``seed`` — the seed(s) a variation re-rolls.

        A workflow with two seeds (e.g. dual-noise video) reports both, in form
        order. Derived from ``param_definitions`` so it stays in sync with the UI.
        """
        return self._seed_keys

    @cached_property
    def _seed_keys(self) -> tuple[str, ...]:
        return tuple(pd.key for pd in self.param_definitions() if pd.type == ParamType.SEED)

    def missing_inputs(self, params: dict) -> list[str]:
        """The labels of the images and videos ``params`` leave unpicked."""
        return [label for key, label in self._input_params
                if not str(params.get(key) or "").strip()]

    @cached_property
    def _input_params(self) -> tuple[tuple[str, str], ...]:
        return tuple((pd.key, pd.label) for pd in self.param_definitions()
                     if pd.type in (ParamType.IMAGE, ParamType.VIDEO))

    def starts_from_an_image(self) -> bool:
        return "input_image" in self.default_params()

    def pins_reused_seed(self) -> bool:
        """Whether loading a past generation's settings pins its seed(s): true
        for a still, whose seed is its composition, false for a video, whose
        seed is one sample of its motion (test_only_the_video_workflows_go_on_
        drawing_seeds_once_one_is_reused says why)."""
        return self.output_type != MediaType.VIDEO

    def enhance_keys(self) -> tuple[str, ...]:
        """Param keys that configure the enhancement rather than the base settings.

        An enhancement is a finish applied to an image, not a different image:
        the gallery deliberately doesn't group by these, so an enhanced render
        shares a folder with its unenhanced twin — the same way a standalone
        enhance folds into the row it upgrades without moving it.

        Derived from the ``enhance``/``enhance_*`` naming (plus
        :attr:`extra_enhance_keys` for the tail params that convention misses),
        so a workflow growing another enhance setting can't silently start
        splitting folders by it.
        """
        named = tuple(pd.key for pd in self.param_definitions()
                      if pd.key == "enhance" or pd.key.startswith("enhance_"))
        return named + self.extra_enhance_keys

    @abstractmethod
    def build_api_payload(self, params: dict) -> dict:
        """Build the ComfyUI API-format prompt dict from user params."""

    def authored_actions(self, params: dict) -> list[dict] | None:
        """The script this clip's movements follow, or ``None`` to take the metronome."""
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
        """The text conditioning segment ``index`` of scene ``scene`` reads --
        ``role`` "prompt" for what it shows, "negative" for what it keeps out:
        ``first_ref``, the graph's own encode of the first scene's text, while
        its scene's text is that one, or an encode of its own scene. A text
        without a break is one scene, so every segment shares the node the
        graph always had; a scene past the last text carries the last text on.
        """
        text = scene_text(scenes, scene)
        if index == 0 or text == scenes[0]:
            return {}, first_ref
        node_id = f"s{index}_{role}"
        return {node_id: _text_encode(clip_ref, text)}, [node_id, 0]

    @classmethod
    def scene_plan(cls, params: dict) -> list[tuple[int, int]]:
        """Every segment of the clip as ``(length, scene)``, in order.

        A story is ``scene_frames``, one length per scene; a lone scene is the
        whole clip and runs for ``frame_count`` -- the length every other reader
        of the settings goes by, and all that settings from the overlay carry -- so a
        single entry never overrules it. Each scene splits into segments of at
        most :data:`SINGLE_WINDOW_FRAMES` (:meth:`segment_lengths`), and every
        segment after the first, its scene's first included, starts on the
        frame before it.
        """
        return [(length, scene)
                for scene, count in enumerate(cls.scene_lengths(params))
                for length in cls.segment_lengths(count)]

    @staticmethod
    def scene_lengths(params: dict) -> list[int]:
        """Each scene's frames: ``scene_frames`` when the story has several, else
        the one clip length (see :meth:`scene_plan` for why a lone entry never
        overrules it)."""
        frames = [int(count) for count in (params.get("scene_frames") or [])]
        if len(frames) < 2:
            frames = [int(params["frame_count"])]
        return frames

    @staticmethod
    def clip_frames(plan: list[tuple[int, int]]) -> int:
        """How many frames a plan renders once each seam's shared frame is
        counted once."""
        return chained_frames([length for length, _ in plan])

    @staticmethod
    def segment_lengths(frame_count: int) -> list[int]:
        """How a clip's frames split into segments of at most
        :data:`SINGLE_WINDOW_FRAMES`: the first as long as it can be, each
        later one starting on the frame before it ended, so it renders one
        frame more than it adds. Every length stays on the models' 4k+1 grid
        because ``frame_count`` is on it.
        """
        lengths = [min(frame_count, SINGLE_WINDOW_FRAMES)]
        remaining = frame_count - lengths[0]
        while remaining > 0:
            length = min(SINGLE_WINDOW_FRAMES, remaining + 1)
            lengths.append(length)
            remaining -= length - 1
        return lengths

    @classmethod
    def chain_segments(cls, params: dict, start_ref, render):
        """The whole clip as segments chained from each other's last frame:
        the nodes, the IMAGE ref holding every frame in order, and how many
        frames that is.

        ``render(index, scene, start_ref, length, last, previous=)`` builds one
        segment -- its conditioning, samplers and decode -- from the image ref
        it starts on, and returns ``(nodes, frames_ref)``; ``scene`` is the
        scene of the story it belongs to, ``last`` says it is the final one,
        and ``previous`` is the frames of the segment before (``None`` for the
        first), for a renderer that carries motion across the seam rather than
        only the one frame. Segment 0 starts on ``start_ref`` and keeps the
        graph's own node ids, so a clip that fits one segment is the graph it
        always was. Each later segment starts on the frame the previous one
        ended on (cut out with ``ImageFromBatch``), and joins the frames after
        that shared one onto the clip (``ImageBatch``), so the seam is one
        frame long.
        """
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
        return nodes, joined, cls.clip_frames(plan)

    @staticmethod
    def image_size_nodes(image_ref, params: dict, megapixels: float = 0.4) -> SizedInput:
        """The subgraph that sizes a run off its input image, and the refs the
        downstream nodes read for the scaled image and its width/height.

        By default the image is scaled to ``megapixels`` in-graph
        (``ImageScaleToTotalPixels`` on a /16 stride — 0.4 MP is the video
        budget; the SDXL still workflow passes its own) and the size read back
        off it (``GetImageSize``), so a portrait or widescreen yields a
        proportional output without a hardcoded WxH. When the user has unlocked
        the derived size and set an explicit ``width``/``height`` (see
        :func:`~origenerator.workflows.derived_size.override_size`), the image is
        instead scaled to that exact size (``ImageScale``) and the literal
        width/height drive the consumer, with no second node to read them off.
        """
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
        """The ControlNet loading subgraph and the CONTROL_NET ref to apply.

        A union file gets a SetUnionControlNetType picking ``head``; a plain
        single-purpose ControlNet is passed straight through, because it
        crashes on the union node's extra argument.
        """
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
        """The upscale/enhance tail appended after a workflow's decode, and the
        IMAGE ref its save node should store.

        Two stages, matching the two things wrong with a raw SDXL render. The
        decoded image first runs through an ESRGAN-family upscale model — real
        edge reconstruction, so the enlargement is sharp rather than resampled —
        and is rescaled to ``enhance_scale`` x the base render (relative to the
        model's own 4x output; see :data:`UPSCALE_MODEL_FACTOR`). ``VAEEncode``
        then hands it to a second ``KSampler`` at ``enhance_denoise``: low
        enough to keep the composition, high enough that the checkpoint
        re-imagines fine texture — skin, hair, fabric — that no upscaler can
        invent, which is what reads as naturalistic. The pass reuses the base
        sampler's model, conditioning, cfg and seed, so an enhanced render is
        still exactly the settings its params record; at ``enhance_denoise`` 0 it
        degrades to a plain sharpening upscale.

        ``rescale_to`` replaces the relative rescale with an exact WxH, for the
        one workflow whose Dimensions field is a derived size the user can
        unlock (the standalone enhance): its override has to govern the saved
        size, and this is the node that decides it. The workflows whose width
        and height are ordinary form fields pass nothing — their size is settled
        long before the tail runs, and reading their params here would rescale
        every enhanced render to the base render's own dimensions.
        """
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
        """The per-part detail pass appended after the enhance tail, and the
        IMAGE ref the save node should store.

        The tail refines the whole frame at once, and that is exactly why it
        cannot fix anatomy: at ``enhance_denoise`` it only re-textures, and the
        denoise that could redraw a hand (0.3+) applies to the sky and the
        floorboards too — which is how creases became wounds. This pass spends
        that denoise where it is wanted instead. A YOLO detector finds the part,
        each rect is cropped out and enlarged to the sampler's own working size,
        re-sampled at that part's own denoise, and composited back through a
        feathered mask — so a mouth or a finger is redrawn at real resolution
        while every pixel outside the rects is left untouched. A part found as
        an outline (skin, hair) is redrawn inside that outline instead, toward
        its own prompts put ahead of the image's.

        One pass per part asked for (:func:`~origenerator.workflows.detail_parts.
        detail_fix_passes` reads ``enhance_detail_fixes`` and drops what isn't
        installed), each running over the last one's output rather than on a
        merged rect list: they are different models found by different detectors,
        and an image with a face and two hands must get all three. A part left
        at zero builds no nodes at all.

        Returns ``(nodes, image_ref)`` — the dict to merge into the payload, and
        the end of the chain. With no part asked for (or no detector installed
        for any of them) that is ``image_ref`` unchanged, so the caller saves
        the tail's output.
        """
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
            model, clip = fixed.model, fixed.clip
            positive, negative = positive_ref, negative_ref
            if own["prompt"] or own["avoid"] or own["lora"]:
                positive_id, negative_id = f"fix{index}_positive", f"fix{index}_negative"
                nodes[positive_id] = _text_encode(
                    clip, ahead_of(own["prompt"], params["positive_prompt"]))
                nodes[negative_id] = _text_encode(
                    clip, ahead_of(own["avoid"], params["negative_prompt"]))
                positive, negative = [positive_id, 0], [negative_id, 0]
            nodes[detailer_id] = {
                "class_type": "DetailerForEach",
                "_meta": {"title": f"{fix.part.name.capitalize()} fix"},
                "inputs": {
                    "image": image_ref,
                    "segs": segs_ref,
                    "model": model,
                    "clip": clip,
                    "vae": vae_ref,
                    # The crop is enlarged to this before sampling, which is what
                    # buys a thumbnail-sized hand enough pixels to be redrawn.
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
        """The HunyuanVideo-Foley subgraph that scores a video's frames, and the
        AUDIO ref the output node should mux.

        Returns ``({three foley nodes}, [sampler_id, 0])`` — a dict to merge into
        the payload, and the ref to feed the video writer's ``audio`` input.
        ``frames_ref`` is the decoded frames the sampler watches — the ones the
        model authored, before any are interpolated between them — so the audio
        follows the motion actually rendered and stays the clip's real length
        whatever rate the file is written at. Both the duration and the rate the
        sampler is told come from the native rate for that reason (the model's
        floor is 1s, so shorter clips get a trailing sliver of extra audio
        rather than a rejected prompt).
        """
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
        """The audio a speaking segment's lips follow: its scene's line from
        ``offset`` frames into the scene, ``length`` frames long, heard by the
        speech model's audio encoder. Returns ``(nodes, encoded_ref)``.

        A scene's line is one file as long as the scene, so a scene that spans
        two segments plays the second its own stretch of it.
        """
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
        """The clip's track for the writer: her line where a scene speaks, the
        foley's own stretch where it does not, laid end to end. ``scenes`` is
        ``(frames, line_ref)`` per scene in order, the ref ``None`` for a silent
        scene; ``foley_ref`` is the foley scored over the whole clip. Returns
        ``(nodes, audio_ref)``.

        The foley watches the frames it scores, and shown a woman talking it
        scores what it sees: a garbled voice under hers, which is what made the
        first spoken clip unlistenable. So a speaking scene carries her line
        alone, and only a silent scene keeps the foley -- cut from the whole
        clip's score at the scene's own place in it.

        Each scene after the first starts on the frame before it, so every
        scene but the last is cut to the frames it adds (its seam frame is the
        next scene's); the last keeps its whole length.
        """
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
        """The frame-interpolation stage that sits between a video's decode and
        its writer, and the IMAGE ref the writer should encode.

        The models pace motion by the frame at
        :data:`~origenerator.workflows.frame_rate.NATIVE_FPS`, so a clip is
        always generated there and a higher rate buys smoothness rather than
        speed. RIFE synthesizes what goes in between: ``multiplier`` frames per
        gap, which turns N frames into (N-1)*multiplier+1 spanning the same
        seconds. The generated frames all survive, endpoints included, so a loop
        still closes on itself.

        Returns ``(nodes, frames_ref)`` — the dict to merge into the payload and
        the ref to encode. At the native rate the multiplier is 1 and there is
        nothing to put between anything: no node, and ``frames_ref`` handed
        straight through.
        """
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
        """Find this workflow's saved files in a ComfyUI /history response.

        VHS_VideoCombine names only the ``-audio`` file it muxed and leaves the
        soundless one it wrote first beside it unlisted.

        When the run also saved its pre-enhance render (:meth:`base_save_node`),
        those files follow, each tagged ``role: "original"``. The order is the
        one the gallery reads as versions of one image — most enhanced first,
        the original last — so an inline-enhanced run lists its levels the same
        way a standalone enhance folded into a row does.
        """
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
        """The extra SaveImage that keeps the pre-enhance render, or ``{}``.

        The enhance tail re-samples an image the graph already made; without
        this that base render is computed and thrown away, leaving an enhanced
        result with nothing to compare it against. Saved under its own prefix,
        it becomes the row's original — the version a re-enhance runs from and
        the one the info pane offers beside the enhanced one. Empty when the
        tail isn't running, since then the primary save IS the base render.
        """
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
