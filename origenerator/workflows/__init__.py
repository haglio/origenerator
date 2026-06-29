from origenerator.workflows.base import WorkflowTemplate
from origenerator.workflows.sdxl_t2i import SdxlT2iWorkflow
from origenerator.workflows.wan22_flf2v_loop import Wan22Flf2vLoopWorkflow
from origenerator.workflows.wan22_i2v import Wan22I2vWorkflow

WORKFLOW_REGISTRY: dict[str, WorkflowTemplate] = {
    "sdxl_t2i": SdxlT2iWorkflow(),
    "wan22_flf2v_loop": Wan22Flf2vLoopWorkflow(),
    "wan22_i2v": Wan22I2vWorkflow(),
}
