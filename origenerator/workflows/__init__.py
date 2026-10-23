from __future__ import annotations

from origenerator.workflows.base import WorkflowTemplate
from origenerator.workflows.flux_t2i_upscaled import FluxT2iUpscaledWorkflow
from origenerator.workflows.image_enhance import ImageEnhanceWorkflow
from origenerator.workflows.krea2_t2i import Krea2T2iWorkflow
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

RETIRED_WORKFLOW_NAMES: dict[str, str] = {
    "wan21_ati_i2v": "WAN 2.1 Image-to-Video (Motion-Tracked)",
}
