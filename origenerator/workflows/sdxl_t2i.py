from origenerator.config import COMFYUI_DIR
from origenerator.workflows.base import ParamDef, WorkflowTemplate


def _list_checkpoints() -> list[str]:
    ckpt_dir = COMFYUI_DIR / "models" / "checkpoints"
    if not ckpt_dir.exists():
        return ["reapony_v80.safetensors"]
    return sorted(
        f.name for f in ckpt_dir.iterdir()
        if f.suffix in (".safetensors", ".ckpt") and f.is_file()
    ) or ["reapony_v80.safetensors"]


class SdxlT2iWorkflow(WorkflowTemplate):
    name = "sdxl_t2i"
    version = "v002"
    display_name = "SDXL Text-to-Image"
    output_type = "image"
    model_keys = ("checkpoint",)
    output_node_id = "7"

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
            "filename_prefix": "image/sdxl_t2i",
        }

    def param_definitions(self) -> list[ParamDef]:
        checkpoints = _list_checkpoints()
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
            ParamDef("sampler_name", "Sampler", "combo", "euler", options=[
                "euler", "euler_ancestral", "heun", "heunpp2", "dpm_2",
                "dpm_2_ancestral", "lms", "dpm_fast", "dpm_adaptive",
                "dpmpp_2s_ancestral", "dpmpp_sde", "dpmpp_sde_gpu",
                "dpmpp_2m", "dpmpp_2m_sde", "dpmpp_2m_sde_gpu",
                "dpmpp_3m_sde", "dpmpp_3m_sde_gpu", "ddpm", "lcm", "ddim",
                "uni_pc", "uni_pc_bh2",
            ]),
            ParamDef("scheduler", "Scheduler", "combo", "normal", options=[
                "normal", "karras", "exponential", "sgm_uniform", "simple",
                "ddim_uniform", "beta",
            ]),
            ParamDef("denoise", "Denoise", "float", 1.0, min_val=0.0, max_val=1.0, step=0.01),
            ParamDef("filename_prefix", "Output Prefix", "str", "image/sdxl_t2i"),
        ]

    def build_api_payload(self, params: dict) -> dict:
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
                    "images": ["6", 0],
                    "filename_prefix": params["filename_prefix"],
                },
            },
            "8": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": params["vae"]},
            },
        }
