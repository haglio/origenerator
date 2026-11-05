from __future__ import annotations

from dataclasses import replace

from origenerator.media import MediaType
from origenerator.workflows.base import ParamDef, ParamType, WorkflowTemplate, prompt_conditioning
from origenerator.workflows.derived_size import measure_image_size, override_size
from origenerator.workflows.detail_parts import FIX_MAX
from origenerator.workflows.flux_t2i_upscaled import FluxT2iUpscaledWorkflow
from origenerator.workflows.krea2_t2i import Krea2T2iWorkflow
from origenerator.workflows.model_arch import SDXL
from origenerator.workflows.model_dropdowns import model_dropdown
from origenerator.workflows.model_files import ANY
from origenerator.workflows.parts import NodeRefs
from origenerator.workflows.prompt_readers import CLIP
from origenerator.workflows.wan22_t2i import Wan22T2iWorkflow

ENHANCE_MODEL_FAMILIES = (SDXL,)
FORMS_THAT_REDRAW = {form.name: form for form in (
    Krea2T2iWorkflow(), FluxT2iUpscaledWorkflow(), Wan22T2iWorkflow())}


class ImageEnhanceWorkflow(WorkflowTemplate):
    name = "image_enhance"
    version = "v005"
    display_name = "Image Enhance"
    output_type = MediaType.IMAGE
    derives_size_from_input = True
    selectable = False
    model_keys = ("checkpoint",)
    text_reader = CLIP
    output_node_id = "12"

    def default_params(self) -> dict:
        return {
            "input_image": "",
            "positive_prompt": "",
            "negative_prompt": "",
            "seed": 0,
            "cfg": 7.5,
            "sampler_name": "euler",
            "scheduler": "normal",
            "checkpoint": "reapony_v80.safetensors",
            "vae": "sdxl_vae.safetensors",
            "upscale_model": "4xUltrasharp_4xUltrasharpV10.pt",
            "enhance_scale": 2.0,
            "enhance_steps": 20,
            "enhance_denoise": 0.15,
            "enhance_detail_fixes": {},
            "enhance_fix_prompts": {},
            "filename_prefix": "image/image_enhance",
        }

    def param_definitions(self) -> list[ParamDef]:
        defaults = self.default_params()
        return [
            ParamDef("input_image", "Image", ParamType.IMAGE, defaults["input_image"]),
            ParamDef("positive_prompt", "Positive Prompt", ParamType.STR, defaults["positive_prompt"], multiline=True),
            ParamDef("negative_prompt", "Negative Prompt", ParamType.STR, defaults["negative_prompt"], multiline=True),
            model_dropdown("checkpoint", "Model", defaults["checkpoint"], "checkpoints",
                         accepts=ENHANCE_MODEL_FAMILIES),
            ParamDef("seed", "Seed", ParamType.SEED, defaults["seed"]),
            model_dropdown("upscale_model", "Upscaler", defaults["upscale_model"],
                         "upscale_models", accepts=ANY),
            ParamDef("enhance_scale", "Upscale Factor", ParamType.FLOAT, defaults["enhance_scale"],
                     min_val=1.0, max_val=4.0, step=0.25, good=(1.5, 2.0)),
            ParamDef("enhance_steps", "Enhance Steps", ParamType.INT, defaults["enhance_steps"], min_val=1, max_val=100, good=(15, 25)),
            ParamDef("enhance_denoise", "Enhance Redraw Amount", ParamType.FLOAT, defaults["enhance_denoise"],
                     min_val=0.0, max_val=1.0, step=0.05, good=(0.1, 0.2)),
            # ComfyUI's detailer node rejects a zero denoise, so a named part's floor sits above zero.
            ParamDef("enhance_detail_fixes", "Fixes", ParamType.FIXES, defaults["enhance_detail_fixes"],
                     min_val=0.05, max_val=FIX_MAX, step=0.05),
        ]

    def derived_display_size(self, params: dict) -> tuple[int, int] | None:
        size = measure_image_size(params.get("input_image", ""))
        if size is None:
            return None
        scale = params.get("enhance_scale", 1.0)
        return round(size[0] * scale), round(size[1] * scale)

    def build_api_payload(self, params: dict) -> dict:
        model_nodes, refs = self._redrawing_model(params)
        enhanced = self.enhance_image_nodes(refs, params, rescale_to=override_size(params))
        detail, saved_ref = self.detail_fix_nodes(replace(refs, image=enhanced.image), params)
        return {
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": params["input_image"]},
            },
            **(model_nodes if params["enhance_denoise"] or detail else {}),
            **enhanced.nodes,
            **detail,
            "12": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": saved_ref,
                    "filename_prefix": params["filename_prefix"],
                },
            },
        }

    def source_model_of(self, params: dict) -> dict | None:
        return params.get("source_model")

    @staticmethod
    def _redrawing_model(params: dict) -> tuple[dict, NodeRefs]:
        source = params.get("source_model")
        if source:
            return FORMS_THAT_REDRAW[source["workflow"]].redraw_refs(
                source["params"], ["1", 0], params["positive_prompt"], params["negative_prompt"])
        return {
            "2": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": params["checkpoint"]},
            },
            **prompt_conditioning("3", ["2", 1], params["positive_prompt"]),
            **prompt_conditioning("4", ["2", 1], params["negative_prompt"]),
            "5": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": params["vae"]},
            },
        }, NodeRefs(image=["1", 0], model=["2", 0], positive=["3", 0],
                    negative=["4", 0], vae=["5", 0], clip_ref=["2", 1])
