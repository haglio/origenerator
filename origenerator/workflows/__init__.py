from __future__ import annotations

from functools import cache

from origenerator.media import ItemType, MediaType
from origenerator.workflows.base import WorkflowTemplate
from origenerator.workflows.flux_t2i_upscaled import FluxT2iUpscaledWorkflow
from origenerator.workflows.image_enhance import ImageEnhanceWorkflow
from origenerator.workflows.krea2_t2i import Krea2T2iWorkflow
from origenerator.workflows.minimax_h3_i2v import MiniMaxH3I2vWorkflow
from origenerator.workflows.non_ai import NonAiWorkflow, non_ai_folder
from origenerator.workflows.outside import OutsideWorkflow, VideoKind, outside_parts
from origenerator.workflows.sdxl_pose_transfer import SdxlPoseTransferWorkflow
from origenerator.workflows.sdxl_t2i import SdxlT2iWorkflow
from origenerator.workflows.wan22_animate import Wan22AnimateWorkflow
from origenerator.workflows.wan22_flf2v_loop import Wan22Flf2vLoopWorkflow
from origenerator.workflows.wan22_i2v import Wan22I2vWorkflow
from origenerator.workflows.wan22_t2i import Wan22T2iWorkflow
from origenerator.workflows.wan22_t2v import Wan22T2vWorkflow

UNRECORDED_VERSIONS = frozenset({"imported", "unknown"})

WORKFLOW_REGISTRY: dict[str, WorkflowTemplate] = {
    "sdxl_t2i": SdxlT2iWorkflow(),
    "sdxl_pose_transfer": SdxlPoseTransferWorkflow(),
    "flux_t2i_upscaled": FluxT2iUpscaledWorkflow(),
    "krea2_t2i": Krea2T2iWorkflow(),
    "wan22_t2i": Wan22T2iWorkflow(),
    "image_enhance": ImageEnhanceWorkflow(),
    "wan22_flf2v_loop": Wan22Flf2vLoopWorkflow(),
    "wan22_t2v": Wan22T2vWorkflow(),
    "wan22_i2v": Wan22I2vWorkflow(),
    "wan22_animate": Wan22AnimateWorkflow(),
    "minimax_h3_i2v": MiniMaxH3I2vWorkflow(),
}


def offered_workflows(*, makes: MediaType | None) -> list[WorkflowTemplate]:
    return [wf for wf in WORKFLOW_REGISTRY.values()
            if wf.selectable and makes in (None, wf.output_type)]


def grouped_by_item_type(workflows: list[WorkflowTemplate]
                         ) -> list[tuple[ItemType, list[WorkflowTemplate]]]:
    groups = [(item_type, [wf for wf in workflows if wf.item_type is item_type])
              for item_type in ItemType]
    return [(item_type, group) for item_type, group in groups if group]


RETIRED_WORKFLOW_NAMES: dict[str, str] = {
    "wan21_ati_i2v": "I2V WAN 2.1 (Motion-Tracked)",
}


def workflow_named(name: str | None) -> WorkflowTemplate | None:
    if name in WORKFLOW_REGISTRY:
        return WORKFLOW_REGISTRY[name]
    parts = outside_parts(name)
    if parts is not None:
        return _outside(*parts)
    folder = non_ai_folder(name)
    return _non_ai(folder) if folder is not None else None


@cache
def _non_ai(folder: str) -> NonAiWorkflow:
    return NonAiWorkflow(folder)


@cache
def _outside(source: str, made: MediaType, kind: VideoKind | None) -> OutsideWorkflow:
    return OutsideWorkflow(source, made, kind)
