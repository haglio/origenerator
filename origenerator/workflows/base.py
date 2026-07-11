from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from origenerator.workflows.derived_size import measure_derived_size, override_size
from origenerator.workflows.model_files import is_no_lora


@dataclass
class ParamDef:
    key: str
    label: str
    type: str  # "str", "int", "float", "seed", "combo", "image"
    default: Any
    options: list | None = None
    min_val: float | None = None
    max_val: float | None = None
    step: float | None = None
    multiline: bool = False


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
    # The param key(s) whose values identify which model produced an output.
    # The gallery groups a workflow's generations into model folders by these.
    model_keys: tuple[str, ...] = ()
    # The param key(s) whose values identify which LoRA(s) a run used. The gallery
    # nests a LoRA folder level beneath each model folder, so runs that differ only
    # in LoRA (same base model) split there. Empty for workflows with no LoRA; the
    # gallery then collapses that level to a single "(no LoRA)" folder.
    lora_keys: tuple[str, ...] = ()
    # The output node whose /history entry lists the saved files, and the key it
    # lists them under: "images" for SaveImage / native SaveVideo, "gifs" for
    # VHS_VideoCombine.
    output_node_id: str
    output_key: str = "images"

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
    def image_size_nodes(scale_id: str, size_id: str, image_ref, params: dict):
        """The subgraph that sizes an i2v run off its input image, and the refs a
        video node reads for its scaled start image and its width/height.

        Returns ``(nodes, scaled_image_ref, width_ref, height_ref)`` to merge into
        the payload. By default the image is scaled to the shared pixel budget
        in-graph (``ImageScaleToTotalPixels`` on a /16 stride) and the size read
        back off it (``GetImageSize``), so a portrait or widescreen yields a
        proportional video without a hardcoded WxH. When the user has unlocked the
        derived size and set an explicit ``width``/``height`` (see
        :func:`~origenerator.workflows.derived_size.override_size`), the image is
        instead scaled to that exact size (``ImageScale``) and the literal
        width/height drive the video node — ``size_id`` is then unused.
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
                    "megapixels": 0.4,
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
        """
        node = history_data.get("outputs", {}).get(self.output_node_id, {})
        return node.get(self.output_key, [])
