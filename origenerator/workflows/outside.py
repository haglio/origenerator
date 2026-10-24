from __future__ import annotations

from enum import StrEnum

from origenerator.media import MediaType
from origenerator.workflows.base import ParamDef, ParamType, WorkflowTemplate

OUTSIDE_MODEL_KEYS = ("model",)
OUTSIDE_LORA_KEYS = ("style",)

_SETTINGS = ("model", "style", "resolution", "aspect_ratio", "quality", "creativity")
PLACES = {
    MediaType.VIDEO: {"prompt": "positive_prompt", "seed": "seed",
                      **{name: name for name in _SETTINGS}},
    MediaType.IMAGE: {"positive_prompt": "positive_prompt", "negative_prompt": "negative_prompt",
                      "seed": "seed", **{name: name for name in _SETTINGS}},
}


class VideoKind(StrEnum):
    IMAGE_TO_VIDEO = "I2V"
    TEXT_TO_VIDEO = "T2V"


_PREFIXES = {
    (MediaType.VIDEO, None): "outside:",
    (MediaType.VIDEO, VideoKind.IMAGE_TO_VIDEO): "outside image-to-video:",
    (MediaType.VIDEO, VideoKind.TEXT_TO_VIDEO): "outside text-to-video:",
    (MediaType.IMAGE, None): "outside picture:",
}


def outside_workflow(source: str, made: MediaType = MediaType.VIDEO,
                     kind: VideoKind | None = None) -> str:
    return _PREFIXES[made, kind] + source


def outside_parts(workflow_name: str | None) -> tuple[str, MediaType, VideoKind | None] | None:
    for (made, kind), prefix in _PREFIXES.items():
        if workflow_name and workflow_name.startswith(prefix):
            return workflow_name.removeprefix(prefix), made, kind
    return None


def outside_source(workflow_name: str | None) -> str | None:
    parts = outside_parts(workflow_name)
    return parts[0] if parts is not None else None


class OutsideWorkflow(WorkflowTemplate):
    version = "outside"
    selectable = False
    generates_here = False
    model_keys = OUTSIDE_MODEL_KEYS
    lora_keys = OUTSIDE_LORA_KEYS
    output_node_id = ""

    def __init__(self, source: str, made: MediaType = MediaType.VIDEO,
                 kind: VideoKind | None = None):
        self.name = outside_workflow(source, made, kind)
        self.display_name = f"{source} {kind}" if kind else source
        self.output_type = made
        self.kind = kind

    def default_params(self) -> dict:
        return {pd.key: pd.default for pd in self.param_definitions()}

    def param_definitions(self) -> list[ParamDef]:
        recorded = set(PLACES[self.output_type].values())
        return [pd for pd in (
            ParamDef("positive_prompt", "Positive Prompt", ParamType.STR, "", multiline=True),
            ParamDef("negative_prompt", "Negative Prompt", ParamType.STR, "", multiline=True),
            ParamDef("seed", "Seed", ParamType.SEED, None),
            ParamDef("model", "Model", ParamType.STR, ""),
            ParamDef("style", "LoRA", ParamType.STR, ""),
            ParamDef("creativity", "Creativity", ParamType.STR, ""),
            ParamDef("resolution", "Resolution", ParamType.STR, ""),
            ParamDef("aspect_ratio", "Aspect Ratio", ParamType.STR, ""),
            ParamDef("quality", "Quality", ParamType.STR, ""),
        ) if pd.key in recorded]

    def pins_reused_seed(self) -> bool:
        return True

    def starts_from_a_picture(self) -> bool:
        return self.kind == VideoKind.IMAGE_TO_VIDEO

    def build_api_payload(self, params: dict) -> dict:
        raise NotImplementedError(f"{self.display_name} made this, and ComfyUI never runs it")
