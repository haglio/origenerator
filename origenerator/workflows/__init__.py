from origenerator.workflows.base import WorkflowTemplate
from origenerator.workflows.flux_t2i_upscaled import FluxT2iUpscaledWorkflow
from origenerator.workflows.image_enhance import ImageEnhanceWorkflow
from origenerator.workflows.sdxl_pose_transfer import SdxlPoseTransferWorkflow
from origenerator.workflows.sdxl_t2i import SdxlT2iWorkflow
from origenerator.workflows.wan21_ati_i2v import Wan21AtiI2vWorkflow
from origenerator.workflows.wan22_flf2v_loop import Wan22Flf2vLoopWorkflow
from origenerator.workflows.wan22_fun_stroke_i2v import Wan22FunStrokeI2vWorkflow
from origenerator.workflows.wan22_i2v import Wan22I2vWorkflow
from origenerator.workflows.wan22_t2i import Wan22T2iWorkflow

WORKFLOW_REGISTRY: dict[str, WorkflowTemplate] = {
    "sdxl_t2i": SdxlT2iWorkflow(),
    "sdxl_pose_transfer": SdxlPoseTransferWorkflow(),
    "flux_t2i_upscaled": FluxT2iUpscaledWorkflow(),
    "wan22_t2i": Wan22T2iWorkflow(),
    "image_enhance": ImageEnhanceWorkflow(),
    "wan22_flf2v_loop": Wan22Flf2vLoopWorkflow(),
    "wan22_i2v": Wan22I2vWorkflow(),
    "wan21_ati_i2v": Wan21AtiI2vWorkflow(),
    "wan22_fun_stroke_i2v": Wan22FunStrokeI2vWorkflow(),
}
