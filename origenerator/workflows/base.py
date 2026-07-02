from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

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

    def seed_keys(self) -> tuple[str, ...]:
        """Param keys whose type is ``seed`` — the seed(s) a variation re-rolls.

        A workflow with two seeds (e.g. dual-noise video) reports both, in form
        order. Derived from ``param_definitions`` so it stays in sync with the UI.
        """
        return tuple(pd.key for pd in self.param_definitions() if pd.type == "seed")

    @abstractmethod
    def build_api_payload(self, params: dict) -> dict:
        """Build the ComfyUI API-format prompt dict from user params."""

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

    def extract_output_info(self, history_data: dict) -> list[dict]:
        """Find this workflow's saved files in a ComfyUI /history response.

        The output node lists them under ``output_key`` — ``images`` for
        SaveImage and native SaveVideo, ``gifs`` for VHS_VideoCombine.
        """
        node = history_data.get("outputs", {}).get(self.output_node_id, {})
        return node.get(self.output_key, [])
