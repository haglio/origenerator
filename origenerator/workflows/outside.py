from __future__ import annotations

from enum import StrEnum

from app_support.gallery_records import PLACES

from origenerator.display_names import shown_name
from origenerator.media import MediaType
from origenerator.workflows.base import ParamDef, ParamType, WorkflowTemplate

OUTSIDE_MODEL_KEYS = ("model",)
OUTSIDE_LORA_KEYS = ("style",)

class VideoKind(StrEnum):
    IMAGE_TO_VIDEO = "I2V"
    TEXT_TO_VIDEO = "T2V"


_PREFIXES = {
    (MediaType.VIDEO, None): "outside:",
    (MediaType.VIDEO, VideoKind.IMAGE_TO_VIDEO): "outside image-to-video:",
    (MediaType.VIDEO, VideoKind.TEXT_TO_VIDEO): "outside text-to-video:",
    (MediaType.IMAGE, None): "outside picture:",
}


PUBLISHED_PREFIXES = (("video", (MediaType.VIDEO, None)),
                      ("image_to_video", (MediaType.VIDEO, VideoKind.IMAGE_TO_VIDEO)),
                      ("text_to_video", (MediaType.VIDEO, VideoKind.TEXT_TO_VIDEO)),
                      ("image", (MediaType.IMAGE, None)))


def published_prefixes() -> dict[str, str]:
    return {kind: _PREFIXES[made_and_kind] for kind, made_and_kind in PUBLISHED_PREFIXES}


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
        self.source = source
        self.output_type = made
        self.kind = kind

    @property
    def display_name(self) -> str:
        site = shown_name(self.source)
        return f"{self.kind} {site}" if self.kind else site

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

    def kept_apart_by(self, params: dict) -> dict:
        return {} if params.get("positive_prompt") else {"input_image": params.get("input_image")}

    def starts_from_an_image(self) -> bool:
        return self.kind == VideoKind.IMAGE_TO_VIDEO

    def build_api_payload(self, params: dict) -> dict:
        raise NotImplementedError(f"{self.display_name} made this, and ComfyUI never runs it")
