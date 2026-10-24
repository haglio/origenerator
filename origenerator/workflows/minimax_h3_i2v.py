from __future__ import annotations

from origenerator.workflows.base import SizedInput
from origenerator.workflows.minimax_h3 import H3_FPS, MiniMaxH3Workflow
from origenerator.workflows.model_arch import FL2VA

__all__ = ["H3_FPS", "MiniMaxH3I2vWorkflow"]


class MiniMaxH3I2vWorkflow(MiniMaxH3Workflow):
    name = "minimax_h3_i2v"
    version = "v001"
    display_name = "MiniMax H3 Image-to-Video"
    mode = FL2VA
    checkpoint = "MiniMax_H3_FL2VA_pruned_nvfp4.safetensors"
    turbo_lora = "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"
    turbo = True
    steps = 8
    good_steps = (8, 20)
    picture_label = "Start Image"

    def conditioning_nodes(self, params: dict, sized: SizedInput) -> dict:
        return self.conditioning("MiniMaxH3ImageToVideo", {
            "clip": ["2", 0],
            "vae": ["3", 0],
            "prompt": params["positive_prompt"],
            "width": sized.width,
            "height": sized.height,
            "length": params["frame_count"],
            "first_frame": sized.image,
        })
