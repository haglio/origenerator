from __future__ import annotations

from origenerator.workflows.base import (
    SAMPLER_OPTIONS,
    SCHEDULER_OPTIONS,
    ParamDef,
    WorkflowTemplate,
)
from origenerator.workflows.model_arch import SD15, SDXL
from origenerator.workflows.model_files import ANY, list_model_files


class SdxlT2iWorkflow(WorkflowTemplate):
    """SDXL text-to-image, optionally finished by an upscale/enhance pass.

    The base render is the plain SDXL recipe. With the ``enhance`` toggle on,
    its decode then runs the shared enhance tail
    (:meth:`WorkflowTemplate.enhance_image_nodes`): a model upscale for
    sharpness, and a low-denoise second sampling pass in which the checkpoint
    re-imagines the enlarged pixels — real generated texture rather than
    interpolation, which is what keeps the result naturalistic. Toggled off
    (its default), the graph ends at the plain decode.

    The toggle defaults off because enhancement is now a *layer* the gallery
    applies afterward — its Enhance subpanel, per folder, with the original
    kept and every level listed. Baking the tail in here would produce an
    enhanced image with no original to compare against and no level to name.
    The param stays (an old run reproduces exactly what it recorded), but
    nothing sets it by hand any more.
    """

    name = "sdxl_t2i"
    version = "v004"
    display_name = "SDXL Text-to-Image"
    output_type = "image"
    model_keys = ("checkpoint",)
    extra_enhance_keys = ("upscale_model",)  # only the tail loads it
    output_node_id = "7"
    base_output_node_id = "15"  # the pre-enhance render, saved when the tail runs

    def default_params(self) -> dict:
        return {
            "positive_prompt": "",
            "negative_prompt": "",
            "seed": 0,
            "steps": 50,
            "cfg": 7.5,
            "width": 1280,
            "height": 720,
            "batch_size": 1,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1.0,
            "checkpoint": "reapony_v80.safetensors",
            "vae": "sdxl_vae.safetensors",
            "enhance": False,
            "upscale_model": "4xUltrasharp_4xUltrasharpV10.pt",
            "enhance_scale": 2.0,
            "enhance_steps": 20,
            # Kept low deliberately: at 0.3 the enhance pass re-imagined creases
            # and skin folds into wounds/disfigurements (user-reported). 0.15
            # refines texture without redrawing anatomy.
            "enhance_denoise": 0.15,
            "filename_prefix": "image/sdxl_t2i",
        }

    def param_definitions(self) -> list[ParamDef]:
        # SD1.5 alongside SDXL: it carries its own CLIP and runs here, just
        # against the SDXL VAE this graph pairs it with. The video models filed
        # under checkpoints carry no text encoder for node 2/3 to read at all.
        defaults = self.default_params()
        checkpoints = list_model_files(
            "checkpoints", [defaults["checkpoint"]], accepts=(SDXL, SD15),
        )
        upscalers = list_model_files(
            "upscale_models", [defaults["upscale_model"]], accepts=ANY,
        )
        return [
            ParamDef("positive_prompt", "Positive Prompt", "str", defaults["positive_prompt"], multiline=True),
            ParamDef("negative_prompt", "Negative Prompt", "str", defaults["negative_prompt"], multiline=True),
            ParamDef("checkpoint", "Model", "combo", defaults["checkpoint"],
                     options=checkpoints),
            ParamDef("seed", "Seed", "seed", defaults["seed"]),
            ParamDef("width", "Width", "int", defaults["width"], min_val=64, max_val=4096, step=64),
            ParamDef("height", "Height", "int", defaults["height"], min_val=64, max_val=4096, step=64),
            ParamDef("steps", "Steps", "int", defaults["steps"], min_val=1, max_val=200),
            ParamDef("cfg", "Prompt Strength", "float", defaults["cfg"], min_val=0.0, max_val=30.0, step=0.5),
            ParamDef("sampler_name", "Sampler", "combo", defaults["sampler_name"],
                     options=SAMPLER_OPTIONS),
            ParamDef("scheduler", "Scheduler", "combo", defaults["scheduler"],
                     options=SCHEDULER_OPTIONS),
            ParamDef("denoise", "Redraw Amount", "float", defaults["denoise"], min_val=0.0, max_val=1.0, step=0.01),
            ParamDef("enhance", "Enhance (upscale + re-sample)", "bool", defaults["enhance"]),
            ParamDef("upscale_model", "Upscale Model", "combo", defaults["upscale_model"],
                     options=upscalers),
            ParamDef("enhance_scale", "Upscale Factor", "float", defaults["enhance_scale"],
                     min_val=1.0, max_val=4.0, step=0.25),
            ParamDef("enhance_steps", "Enhance Steps", "int", defaults["enhance_steps"], min_val=1, max_val=100),
            ParamDef("enhance_denoise", "Enhance Redraw Amount", "float", defaults["enhance_denoise"],
                     min_val=0.0, max_val=1.0, step=0.05),
        ]

    def build_api_payload(self, params: dict) -> dict:
        enhance_nodes: dict = {}
        enhanced_ref = ["6", 0]  # enhance off: save the plain decode
        if params.get("enhance"):
            tail = self.enhance_image_nodes(
                image_ref=["6", 0], model_ref=["1", 0],
                positive_ref=["2", 0], negative_ref=["3", 0], vae_ref=["8", 0],
                params=params,
            )
            enhance_nodes, enhanced_ref = tail.nodes, tail.image
        return {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": params["checkpoint"]},
            },
            "2": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["1", 1], "text": params["positive_prompt"]},
            },
            "3": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["1", 1], "text": params["negative_prompt"]},
            },
            "4": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "width": params["width"],
                    "height": params["height"],
                    "batch_size": params["batch_size"],
                },
            },
            "5": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["1", 0],
                    "positive": ["2", 0],
                    "negative": ["3", 0],
                    "latent_image": ["4", 0],
                    "seed": params["seed"],
                    "steps": params["steps"],
                    "cfg": params["cfg"],
                    "sampler_name": params["sampler_name"],
                    "scheduler": params["scheduler"],
                    "denoise": params["denoise"],
                },
            },
            "6": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["5", 0], "vae": ["8", 0]},
            },
            "7": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": enhanced_ref,
                    "filename_prefix": params["filename_prefix"],
                },
            },
            "8": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": params["vae"]},
            },
            **enhance_nodes,
            # With the tail on, keep the base render too — it is made on the way
            # and would otherwise be discarded, leaving no original.
            **self.base_save_node(self.base_output_node_id, ["6", 0], params),
        }
