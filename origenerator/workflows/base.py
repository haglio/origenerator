from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from origenerator.workflows.derived_size import measure_derived_size, override_size
from origenerator.workflows.model_files import is_no_lora

# ComfyUI's KSampler vocabulary, for workflows that expose sampler/scheduler
# pickers (the SDXL pair) — one copy, so the option lists can't drift apart.
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

# The native factor of the installed ESRGAN-family upscale models (both are 4x).
# The enhance tail rescales the model's output DOWN from this to the requested
# ``enhance_scale``, so the saved image lands at enhance_scale x the base render.
UPSCALE_MODEL_FACTOR = 4.0

# The detail pass's fixed shape (see :meth:`WorkflowTemplate.detail_fix_nodes`).
# All of these are the detector/detailer nodes' own defaults, kept here as named
# constants rather than as knobs: the pass already costs the user a checkbox and
# a denoise, and every one of these is a value their answer would be a guess at.
_DETECTOR_THRESHOLD = 0.5     # how sure the detector must be to call it a face
_DETECTOR_DILATION = 10       # pixels grown around each box, so edges are inside
_DETECTOR_CROP_FACTOR = 3.0   # how much context around the box the sampler sees
_DETECTOR_DROP_SIZE = 10      # boxes smaller than this are noise, not anatomy
_DETAIL_GUIDE_SIZE = 512      # each crop is enlarged to this before sampling
_DETAIL_MAX_SIZE = 1024       # …but never past this, which is where VRAM goes
_DETAIL_FEATHER = 5           # pixels the repaint fades over on the way back in


@dataclass
class ParamDef:
    key: str
    label: str
    type: str  # "str", "int", "float", "seed", "combo", "image", "bool"
    default: Any
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


class WorkflowTemplate(ABC):
    name: str
    version: str
    display_name: str
    output_type: str  # "image" or "video"
    # True when the output video loops (returns to its start frame), so the
    # funscript synthesized alongside it is tiled to repeat seamlessly. Only the
    # first-last-frame loop workflow sets this; a one-shot video leaves it False.
    looping: bool = False
    # True when the output size is derived from the input image (kept at its
    # aspect ratio on a fixed pixel budget) rather than set by hand. The i2v
    # workflows set this; the Generate form then shows the derived width/height in
    # a locked Dimensions field the user can unlock to override. Width/height stay
    # out of ``default_params`` (the size isn't a stored recipe setting), so an
    # override never splits a gallery folder from an otherwise identical run.
    derives_size_from_input: bool = False
    # False for machinery workflows the user never picks by hand (the standalone
    # image enhancer, launched by the gallery's enhance buttons): they stay out
    # of the Generate tab's workflow dropdown but remain registered — payloads
    # still build, in-flight rows still reconnect and caption themselves.
    selectable: bool = True
    # The param key(s) whose values identify which model produced an output.
    # The gallery groups a workflow's generations into model folders by these.
    model_keys: tuple[str, ...] = ()
    # The param key(s) whose values identify which LoRA(s) a run used. The gallery
    # nests a LoRA folder level beneath each model folder, so runs that differ only
    # in LoRA (same base model) split there. Empty for workflows with no LoRA; the
    # gallery then collapses that level to a single "(no LoRA)" folder.
    lora_keys: tuple[str, ...] = ()
    # Param keys the enhance tail reads that the ``enhance``/``enhance_*`` naming
    # doesn't already cover, so they join :meth:`enhance_keys` and stay out of the
    # gallery's grouping. The SDXL and WAN t2i workflows list ``upscale_model``
    # here: it loads the tail's upscaler and does nothing with the toggle off.
    # Flux does not — there the same param also drives the plain 4x upscale that
    # is that workflow's namesake output, so it stays part of the recipe.
    extra_enhance_keys: tuple[str, ...] = ()
    # The output node whose /history entry lists the saved files, and the key it
    # lists them under: "images" for SaveImage / native SaveVideo, "gifs" for
    # VHS_VideoCombine.
    output_node_id: str
    output_key: str = "images"
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
        return tuple(pd.key for pd in self.param_definitions() if pd.type == "seed")

    def enhance_keys(self) -> tuple[str, ...]:
        """Param keys that configure the enhancement rather than the recipe.

        An enhancement is a finish applied to an image, not a different image:
        the gallery deliberately doesn't group by these, so an enhanced render
        shares a folder with its unenhanced twin — the same way a standalone
        enhance folds into the row it upgrades without moving it.

        Derived from the ``enhance``/``enhance_*`` naming (plus
        :attr:`extra_enhance_keys` for the tail params that convention misses),
        so a workflow growing another enhance knob can't silently start
        splitting folders by it.
        """
        named = tuple(pd.key for pd in self.param_definitions()
                      if pd.key == "enhance" or pd.key.startswith("enhance_"))
        return named + self.extra_enhance_keys

    @abstractmethod
    def build_api_payload(self, params: dict) -> dict:
        """Build the ComfyUI API-format prompt dict from user params."""

    def authored_actions(self, params: dict) -> list[dict] | None:
        """The funscript actions this generation's motion was AUTHORED to, or
        ``None`` when the workflow doesn't condition motion on a track.

        A track-conditioned workflow (ATI) knows its stroke exactly, so its
        funscript comes from here — completion prefers it over the synthesized
        metronome, which remains the fallback for pixels-only workflows."""
        return None

    @staticmethod
    def lora_model_input(node_id: str, model_ref, lora_name, strength):
        """The optional model-only LoRA node to add to a payload, and the model
        input the downstream node should read.

        With a real ``lora_name``, returns ``({node_id: <LoraLoaderModelOnly>},
        [node_id, 0])`` — a one-node dict to merge into the payload, and the ref
        pointing at it. When ``lora_name`` is the "None" sentinel (or empty),
        returns ``({}, model_ref)``: no node, and ``model_ref`` passed straight
        through, so the graph carries no LoRA for that slot and the base model
        runs unmodified. ComfyUI validates ``lora_name`` against the installed
        files, so a bypassed slot must be omitted, not passed a placeholder name.
        """
        if is_no_lora(lora_name):
            return {}, model_ref
        node = {
            node_id: {
                "class_type": "LoraLoaderModelOnly",
                "inputs": {
                    "model": model_ref,
                    "lora_name": lora_name,
                    "strength_model": strength,
                },
            }
        }
        return node, [node_id, 0]

    @staticmethod
    def image_size_nodes(scale_id: str, size_id: str, image_ref, params: dict,
                         megapixels: float = 0.4):
        """The subgraph that sizes a run off its input image, and the refs the
        downstream nodes read for the scaled image and its width/height.

        Returns ``(nodes, scaled_image_ref, width_ref, height_ref)`` to merge into
        the payload. By default the image is scaled to ``megapixels`` in-graph
        (``ImageScaleToTotalPixels`` on a /16 stride — 0.4 MP is the video
        budget; the SDXL still workflow passes its own) and the size read back
        off it (``GetImageSize``), so a portrait or widescreen yields a
        proportional output without a hardcoded WxH. When the user has unlocked
        the derived size and set an explicit ``width``/``height`` (see
        :func:`~origenerator.workflows.derived_size.override_size`), the image is
        instead scaled to that exact size (``ImageScale``) and the literal
        width/height drive the consumer — ``size_id`` is then unused.
        """
        override = override_size(params)
        if override is not None:
            width, height = override
            nodes = {
                scale_id: {
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
            return nodes, [scale_id, 0], width, height
        nodes = {
            scale_id: {
                "class_type": "ImageScaleToTotalPixels",
                "inputs": {
                    "image": image_ref,
                    "upscale_method": "lanczos",
                    "megapixels": megapixels,
                    "resolution_steps": 16,
                },
            },
            size_id: {
                "class_type": "GetImageSize",
                "inputs": {"image": [scale_id, 0]},
            },
        }
        return nodes, [scale_id, 0], [size_id, 0], [size_id, 1]

    @staticmethod
    def enhance_image_nodes(loader_id: str, upscale_id: str, scale_id: str,
                            encode_id: str, sampler_id: str, decode_id: str, *,
                            image_ref, model_ref, positive_ref, negative_ref,
                            vae_ref, params: dict):
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
        still exactly the recipe its params record; at ``enhance_denoise`` 0 it
        degrades to a plain sharpening upscale.

        Returns ``(nodes, [decode_id, 0])`` — the dict to merge into the
        payload, and the enhanced-image ref to feed the save node.
        """
        nodes = {
            loader_id: {
                "class_type": "UpscaleModelLoader",
                "inputs": {"model_name": params["upscale_model"]},
            },
            upscale_id: {
                "class_type": "ImageUpscaleWithModel",
                "inputs": {"upscale_model": [loader_id, 0], "image": image_ref},
            },
            scale_id: {
                "class_type": "ImageScaleBy",
                "inputs": {
                    "image": [upscale_id, 0],
                    "upscale_method": "lanczos",
                    "scale_by": params["enhance_scale"] / UPSCALE_MODEL_FACTOR,
                },
            },
            encode_id: {
                "class_type": "VAEEncode",
                "inputs": {"pixels": [scale_id, 0], "vae": vae_ref},
            },
            sampler_id: {
                "class_type": "KSampler",
                "inputs": {
                    "model": model_ref,
                    "positive": positive_ref,
                    "negative": negative_ref,
                    "latent_image": [encode_id, 0],
                    "seed": params["seed"],
                    "steps": params["enhance_steps"],
                    "cfg": params["cfg"],
                    "sampler_name": params["sampler_name"],
                    "scheduler": params["scheduler"],
                    "denoise": params["enhance_denoise"],
                },
            },
            decode_id: {
                "class_type": "VAEDecode",
                "inputs": {"samples": [sampler_id, 0], "vae": vae_ref},
            },
        }
        return nodes, [decode_id, 0]

    @staticmethod
    def detail_fix_nodes(face_ids: tuple[str, str, str],
                         hand_ids: tuple[str, str, str], *,
                         image_ref, model_ref, clip_ref, vae_ref,
                         positive_ref, negative_ref, params: dict):
        """The face/hand detail pass appended after the enhance tail, and the
        IMAGE ref the save node should store.

        The tail refines the whole frame at once, and that is exactly why it
        cannot fix anatomy: at ``enhance_denoise`` it only re-textures, and the
        denoise that could redraw a hand (0.3+) applies to the sky and the
        floorboards too — which is how creases became wounds. This pass spends
        that denoise where it is wanted instead. A YOLO detector finds the faces
        (then the hands), each box is cropped out and enlarged to the sampler's
        own working size, re-sampled at ``enhance_detail_denoise``, and composited back
        through a feathered mask — so a mouth or a finger is redrawn at real
        resolution while every pixel outside the boxes is left untouched.

        Two independent detectors, run one after the other on each other's
        output, rather than one merged box list: they are different models, and
        an image with a face and two hands must get all three. Each ``*_ids``
        triple names that half's provider, detector and detailer nodes; a half
        whose detector param is empty builds no nodes at all — the same bypass
        :meth:`lora_model_input` does, since ComfyUI validates the model name
        and rejects the whole submit for one it cannot find.

        Returns ``(nodes, image_ref)`` — the dict to merge into the payload, and
        the end of the chain. With ``enhance_detail_fix`` off (or no detector named)
        that is ``image_ref`` unchanged, so the caller saves the tail's output.
        """
        if not params.get("enhance_detail_fix"):
            return {}, image_ref
        nodes: dict = {}
        for ids, key in ((face_ids, "enhance_face_detector"),
                         (hand_ids, "enhance_hand_detector")):
            detector = params.get(key)
            if not detector:
                continue
            provider_id, segs_id, detailer_id = ids
            nodes[provider_id] = {
                "class_type": "UltralyticsDetectorProvider",
                # The provider's own picker prefixes its bounding-box models
                # this way, and the value is matched against that list.
                "inputs": {"model_name": f"bbox/{detector}"},
            }
            nodes[segs_id] = {
                "class_type": "BboxDetectorSEGS",
                "inputs": {
                    "bbox_detector": [provider_id, 0],
                    "image": image_ref,
                    "threshold": _DETECTOR_THRESHOLD,
                    "dilation": _DETECTOR_DILATION,
                    "crop_factor": _DETECTOR_CROP_FACTOR,
                    "drop_size": _DETECTOR_DROP_SIZE,
                    "labels": "all",
                },
            }
            nodes[detailer_id] = {
                "class_type": "DetailerForEach",
                "inputs": {
                    "image": image_ref,
                    "segs": [segs_id, 0],
                    "model": model_ref,
                    "clip": clip_ref,
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
                    "positive": positive_ref,
                    "negative": negative_ref,
                    "denoise": params["enhance_detail_denoise"],
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
        ``frames_ref`` is the decoded frames the sampler watches, so the audio
        follows the motion actually rendered. The sampler's duration is derived
        from the same frame_count/frame_rate the video nodes use (the model's
        floor is 1s, so shorter clips get a trailing sliver of extra audio
        rather than a rejected prompt).
        """
        duration = max(1.0, params["frame_count"] / params["frame_rate"])
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
                    "frame_rate": params["frame_rate"],
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

    def extract_output_info(self, history_data: dict) -> list[dict]:
        """Find this workflow's saved files in a ComfyUI /history response.

        The output node lists them under ``output_key`` — ``images`` for
        SaveImage and native SaveVideo, ``gifs`` for VHS_VideoCombine.

        When the run also saved its pre-enhance render (:meth:`base_save_node`),
        those files follow, each tagged ``role: "original"``. The order is the
        one the gallery reads as versions of one image — most enhanced first,
        the original last — so an inline-enhanced run lists its levels the same
        way a standalone enhance folded into a row does.
        """
        outputs = history_data.get("outputs", {})
        files = list(outputs.get(self.output_node_id, {}).get(self.output_key, []))
        if self.base_output_node_id is None:
            return files
        base = outputs.get(self.base_output_node_id, {}).get(self.output_key, [])
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
