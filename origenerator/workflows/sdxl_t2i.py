from origenerator.workflows.base import (
    SAMPLER_OPTIONS, SCHEDULER_OPTIONS, ParamDef, WorkflowTemplate,
)
from origenerator.workflows.model_files import list_model_files

_DEFAULT_UPSCALE_MODEL = "4xUltrasharp_4xUltrasharpV10.pt"


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
            "upscale_model": _DEFAULT_UPSCALE_MODEL,
            "enhance_scale": 2.0,
            "enhance_steps": 20,
            # Kept low deliberately: at 0.3 the enhance pass re-imagined creases
            # and skin folds into wounds/disfigurements (user-reported). 0.15
            # refines texture without redrawing anatomy.
            "enhance_denoise": 0.15,
            "filename_prefix": "image/sdxl_t2i",
        }

    def param_definitions(self) -> list[ParamDef]:
        checkpoints = list_model_files("checkpoints", ["reapony_v80.safetensors"])
        upscalers = list_model_files("upscale_models", [_DEFAULT_UPSCALE_MODEL])
        return [
            ParamDef("positive_prompt", "Positive Prompt", "str", "", multiline=True),
            ParamDef("negative_prompt", "Negative Prompt", "str", "", multiline=True),
            ParamDef("checkpoint", "Model", "combo", "reapony_v80.safetensors",
                     options=checkpoints),
            ParamDef("seed", "Seed", "seed", 0),
            ParamDef("width", "Width", "int", 1280, min_val=64, max_val=4096, step=64),
            ParamDef("height", "Height", "int", 720, min_val=64, max_val=4096, step=64),
            ParamDef("batch_size", "Batch Size", "int", 1, min_val=1, max_val=16),
            ParamDef("steps", "Steps", "int", 50, min_val=1, max_val=200),
            ParamDef("cfg", "CFG Scale", "float", 7.5, min_val=0.0, max_val=30.0, step=0.5),
            ParamDef("sampler_name", "Sampler", "combo", "euler",
                     options=SAMPLER_OPTIONS),
            ParamDef("scheduler", "Scheduler", "combo", "normal",
                     options=SCHEDULER_OPTIONS),
            ParamDef("denoise", "Denoise", "float", 1.0, min_val=0.0, max_val=1.0, step=0.01),
            ParamDef("enhance", "Enhance (upscale + re-sample)", "bool", False),
            ParamDef("upscale_model", "Upscale Model", "combo", _DEFAULT_UPSCALE_MODEL,
                     options=upscalers),
            ParamDef("enhance_scale", "Upscale Factor", "float", 2.0,
                     min_val=1.0, max_val=4.0, step=0.25),
            ParamDef("enhance_steps", "Enhance Steps", "int", 20, min_val=1, max_val=100),
            ParamDef("enhance_denoise", "Enhance Denoise", "float", 0.15,
                     min_val=0.0, max_val=1.0, step=0.05),
            ParamDef("filename_prefix", "Output Prefix", "str", "image/sdxl_t2i"),
        ]

    def build_api_payload(self, params: dict) -> dict:
        enhance_nodes: dict = {}
        enhanced_ref = ["6", 0]  # enhance off: save the plain decode
        if params.get("enhance"):
            enhance_nodes, enhanced_ref = self.enhance_image_nodes(
                "9", "10", "11", "12", "13", "14",
                image_ref=["6", 0], model_ref=["1", 0],
                positive_ref=["2", 0], negative_ref=["3", 0], vae_ref=["8", 0],
                params=params,
            )
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
