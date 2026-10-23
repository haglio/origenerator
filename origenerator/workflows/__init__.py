from __future__ import annotations

from functools import cache

from origenerator.media import MediaType
from origenerator.workflows.base import WorkflowTemplate
from origenerator.workflows.flux_t2i_upscaled import FluxT2iUpscaledWorkflow
from origenerator.workflows.image_enhance import ImageEnhanceWorkflow
from origenerator.workflows.krea2_t2i import Krea2T2iWorkflow
from origenerator.workflows.outside import OutsideWorkflow, VideoKind, outside_parts
from origenerator.workflows.sdxl_pose_transfer import SdxlPoseTransferWorkflow
from origenerator.workflows.sdxl_t2i import SdxlT2iWorkflow
from origenerator.workflows.wan22_animate import Wan22AnimateWorkflow
from origenerator.workflows.wan22_flf2v_loop import Wan22Flf2vLoopWorkflow
from origenerator.workflows.wan22_i2v import Wan22I2vWorkflow
from origenerator.workflows.wan22_t2i import Wan22T2iWorkflow

# What an imported row stores as its workflow_version: the file never said.
# "unknown" is the spelling imports carried before "imported".
UNRECORDED_VERSIONS = frozenset({"imported", "unknown"})

WORKFLOW_REGISTRY: dict[str, WorkflowTemplate] = {
    "sdxl_t2i": SdxlT2iWorkflow(),
    "sdxl_pose_transfer": SdxlPoseTransferWorkflow(),
    "flux_t2i_upscaled": FluxT2iUpscaledWorkflow(),
    "krea2_t2i": Krea2T2iWorkflow(),
    "wan22_t2i": Wan22T2iWorkflow(),
    "image_enhance": ImageEnhanceWorkflow(),
    "wan22_flf2v_loop": Wan22Flf2vLoopWorkflow(),
    "wan22_i2v": Wan22I2vWorkflow(),
    "wan22_animate": Wan22AnimateWorkflow(),
}


def offered_workflows(*, makes: MediaType | None) -> list[WorkflowTemplate]:
    return [wf for wf in WORKFLOW_REGISTRY.values()
            if wf.selectable and makes in (None, wf.output_type)]


RETIRED_WORKFLOW_NAMES: dict[str, str] = {
    "wan21_ati_i2v": "WAN 2.1 I2V (Motion-Tracked)",
}


def workflow_named(name: str | None) -> WorkflowTemplate | None:
    if name in WORKFLOW_REGISTRY:
        return WORKFLOW_REGISTRY[name]
    parts = outside_parts(name)
    return _outside(*parts) if parts is not None else None


@cache
def _outside(source: str, made: MediaType, kind: VideoKind | None) -> OutsideWorkflow:
    return OutsideWorkflow(source, made, kind)
