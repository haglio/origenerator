from __future__ import annotations

from origenerator.config import CUSTOM_POSES_DIR
from origenerator.media import MediaType
from origenerator.workflows.base import (
    GENTLE_ENHANCE_DENOISE,
    ParamDef,
    ParamType,
    WorkflowTemplate,
    prompt_conditioning,
    sampler_params,
)
from origenerator.workflows.derived_size import measure_derived_size
from origenerator.workflows.lora_rows import LORA_KEYS, lora_defaults, lora_rows, picked_loras
from origenerator.workflows.model_arch import SDXL
from origenerator.workflows.model_dropdowns import model_dropdown
from origenerator.workflows.model_files import WORKS_ON_PIXELS
from origenerator.workflows.parts import NodeRefs
from origenerator.workflows.prompt_readers import CLIP

# SDXL is trained at about one megapixel.
_SDXL_MEGAPIXELS = 1.0


class SdxlPoseTransferWorkflow(WorkflowTemplate):
    """SDXL T2I steered by the structure of an input image.

    ComfyUI's SetUnionControlNetType is added only for union ControlNets: a plain single-purpose one crashes on the extra argument.
    ComfyUI's DWPose preprocessor loses the person on close-ups and overlapping bodies.
    """
    name = "sdxl_pose_transfer"
    version = "v004"
    display_name = "SDXL Pose Transfer"
    output_type = MediaType.IMAGE
    derives_size_from_input = True
    model_keys = ("checkpoint",)
    lora_keys = loras_keyed_only_when_named = LORA_KEYS
    text_reader = CLIP
    extra_enhance_keys = ("upscale_model",)
    output_node_id = "14"
    base_output_node_id = "24"

    def default_params(self) -> dict:
        return {
            "positive_prompt": "",
            "negative_prompt": "",
            "input_image": "",
            "seed": 0,
            "steps": 50,
            "cfg": 7.5,
            "batch_size": 1,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1.0,
            "checkpoint": "reapony_v80.safetensors",
            **lora_defaults(LORA_KEYS),
            "vae": "sdxl_vae.safetensors",
            "control_mode": "depth",
            "controlnet": "xinsir_controlnet_union_sdxl_promax.safetensors",
            "controlnet_strength": 0.8,
            "controlnet_end": 1.0,
            "depth_model": "depth_anything_v2_vitl_fp32.safetensors",
            "pose_bbox_detector": "yolox_l.onnx",
            "pose_estimator": "dw-ll_ucoco_384_bs5.torchscript.pt",
            "enhance": False,
            "upscale_model": "4xUltrasharp_4xUltrasharpV10.pt",
            "enhance_scale": 2.0,
            "enhance_steps": 20,
            "enhance_denoise": GENTLE_ENHANCE_DENOISE,
            "filename_prefix": "image/sdxl_pose_transfer",
        }

    def param_definitions(self) -> list[ParamDef]:
        defaults = self.default_params()
        return [
            ParamDef("positive_prompt", "Positive Prompt", ParamType.STR, defaults["positive_prompt"], multiline=True),
            ParamDef("negative_prompt", "Negative Prompt", ParamType.STR, defaults["negative_prompt"], multiline=True),
            ParamDef("input_image", "Structure Image", ParamType.IMAGE, defaults["input_image"],
                     browse_dir=CUSTOM_POSES_DIR),
            model_dropdown("checkpoint", "Model", defaults["checkpoint"], "checkpoints",
                         accepts=(SDXL,)),
            *lora_rows(defaults, LORA_KEYS, accepts=(SDXL,)),
            ParamDef("control_mode", "Structure From", ParamType.DROPDOWN, defaults["control_mode"],
                     options=["depth", "pose"]),
            model_dropdown("controlnet", "Structure Model", defaults["controlnet"], "controlnet",
                         accepts=(SDXL,)),
            ParamDef("controlnet_strength", "Structure Strength", ParamType.FLOAT, defaults["controlnet_strength"],
                     min_val=0.0, max_val=2.0, step=0.05, good=(0.5, 0.9)),
            ParamDef("controlnet_end", "Structure Hold", ParamType.FLOAT, defaults["controlnet_end"],
                     min_val=0.0, max_val=1.0, step=0.05, good=(0.6, 1.0)),
            ParamDef("seed", "Seed", ParamType.SEED, defaults["seed"]),
            ParamDef("steps", "Steps", ParamType.INT, defaults["steps"], min_val=1, max_val=200, good=(25, 50)),
            ParamDef("cfg", "Prompt Strength", ParamType.FLOAT, defaults["cfg"], min_val=0.0, max_val=30.0, step=0.5, good=(3, 8)),
            *sampler_params(defaults),
            ParamDef("enhance", "Enhance (upscale + re-sample)", ParamType.BOOL, defaults["enhance"]),
            model_dropdown("upscale_model", "Upscaler", defaults["upscale_model"],
                         "upscale_models", accepts=WORKS_ON_PIXELS),
            ParamDef("enhance_scale", "Upscale Factor", ParamType.FLOAT, defaults["enhance_scale"],
                     min_val=1.0, max_val=4.0, step=0.25, good=(1.5, 2.0)),
            ParamDef("enhance_steps", "Enhance Steps", ParamType.INT, defaults["enhance_steps"], min_val=1, max_val=100, good=(15, 25)),
            ParamDef("enhance_denoise", "Enhance Redraw Amount", ParamType.FLOAT, defaults["enhance_denoise"],
                     min_val=0.0, max_val=1.0, step=0.05, good=(0.1, 0.2)),
        ]

    def derived_display_size(self, params: dict) -> tuple[int, int] | None:
        return measure_derived_size(
            params.get("input_image", ""), megapixels=_SDXL_MEGAPIXELS
        )

    @staticmethod
    def _structure_nodes(params: dict, scaled_ref) -> tuple[dict, list]:
        if params["control_mode"] == "pose":
            nodes = {
                "8": {
                    "class_type": "DWPreprocessor",
                    "inputs": {
                        "image": scaled_ref,
                        "detect_hand": "enable",
                        "detect_body": "enable",
                        "detect_face": "enable",
                        "resolution": 1024,
                        "bbox_detector": params["pose_bbox_detector"],
                        "pose_estimator": params["pose_estimator"],
                        # xinsir's SDXL ControlNets (ComfyUI loads them) are trained on thicker skeleton sticks.
                        "scale_stick_for_xinsr_cn": (
                            "enable" if "xinsir" in params["controlnet"].lower()
                            else "disable"
                        ),
                    },
                },
            }
            return nodes, ["8", 0]
        nodes = {
            "22": {
                "class_type": "DownloadAndLoadDepthAnythingV2Model",
                "inputs": {"model": params["depth_model"]},
            },
            "23": {
                "class_type": "DepthAnything_V2",
                "inputs": {"da_model": ["22", 0], "images": scaled_ref},
            },
        }
        return nodes, ["23", 0]

    def build_api_payload(self, params: dict) -> dict:
        sized = self.image_size_nodes(["1", 0], params, megapixels=_SDXL_MEGAPIXELS)
        size_nodes, scaled_ref = sized.nodes, sized.image
        width_ref, height_ref = sized.width, sized.height
        structure, hint_ref = self._structure_nodes(params, scaled_ref)
        controlnet, controlnet_ref = self.controlnet_nodes(
            "7", "21", controlnet=params["controlnet"],
            head="openpose" if params["control_mode"] == "pose" else "depth",
        )
        loras = self.lora_chain("25", ["4", 0], picked_loras(params, LORA_KEYS), clip_ref=["4", 1])
        enhance_nodes: dict = {}
        enhanced_ref = ["13", 0]
        if params.get("enhance"):
            tail = self.enhance_image_nodes(
                NodeRefs(image=["13", 0], model=loras.model, positive=["9", 0],
                         negative=["9", 1], vae=["12", 0]),
                params,
            )
            enhance_nodes, enhanced_ref = tail.nodes, tail.image
        return {
            **size_nodes,
            **structure,
            **controlnet,
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": params["input_image"]},
            },
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": params["checkpoint"]},
            },
            **loras.nodes,
            **prompt_conditioning("5", loras.clip_ref, params["positive_prompt"]),
            **prompt_conditioning("6", loras.clip_ref, params["negative_prompt"]),
            "9": {
                "class_type": "ControlNetApplyAdvanced",
                "inputs": {
                    "positive": ["5", 0],
                    "negative": ["6", 0],
                    "control_net": controlnet_ref,
                    "image": hint_ref,
                    "strength": params["controlnet_strength"],
                    "start_percent": 0.0,
                    "end_percent": params["controlnet_end"],
                },
            },
            "10": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "width": width_ref,
                    "height": height_ref,
                    "batch_size": params["batch_size"],
                },
            },
            "11": {
                "class_type": "KSampler",
                "inputs": {
                    "model": loras.model,
                    "positive": ["9", 0],
                    "negative": ["9", 1],
                    "latent_image": ["10", 0],
                    "seed": params["seed"],
                    "steps": params["steps"],
                    "cfg": params["cfg"],
                    "sampler_name": params["sampler_name"],
                    "scheduler": params["scheduler"],
                    "denoise": 1.0,
                },
            },
            "12": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": params["vae"]},
            },
            "13": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["11", 0], "vae": ["12", 0]},
            },
            "14": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": enhanced_ref,
                    "filename_prefix": params["filename_prefix"],
                },
            },
            **enhance_nodes,
            **self.base_save_node(self.base_output_node_id, ["13", 0], params),
        }
