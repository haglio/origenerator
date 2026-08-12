from origenerator.workflows.base import (
    SAMPLER_OPTIONS, SCHEDULER_OPTIONS, ParamDef, WorkflowTemplate,
)
from origenerator.workflows.derived_size import measure_derived_size
from origenerator.workflows.model_files import list_model_files

# The pixel budget the output is scaled to. SDXL is trained at ~1 megapixel, so
# the pose image's aspect ratio is kept at that budget — unlike the video
# workflows' 0.4 MP, which would starve SDXL of resolution.
_TARGET_MEGAPIXELS = 1.0


class SdxlPoseTransferWorkflow(WorkflowTemplate):
    """SDXL text-to-image steered by the pose of an input image.

    A variation of :class:`~origenerator.workflows.sdxl_t2i.SdxlT2iWorkflow`
    that re-skins an image: a DWPose skeleton is extracted from the input and
    applied through an SDXL ControlNet, so the render keeps the input's pose,
    angle and proportions while the prompt and checkpoint replace everything
    else about how it looks. Only the skeleton crosses over — the sampler still
    denoises from scratch (denoise 1.0), which is what lets the presentation
    change completely while the structure holds.

    The output size is derived from the input image (its aspect ratio at the
    SDXL pixel budget), the same locked-Dimensions treatment the i2v workflows
    get, because the pose skeleton is stretched to the output canvas — a
    hand-set size with a different aspect would distort the pose it exists to
    preserve.

    Like sdxl_t2i, the render is finished by the shared upscale/enhance tail
    (:meth:`WorkflowTemplate.enhance_image_nodes`). Its second sampling pass
    reuses the ControlNet-applied conditioning, so the pose stays pinned while
    the checkpoint sharpens and re-textures the enlarged image.
    """

    name = "sdxl_pose_transfer"
    version = "v002"
    display_name = "SDXL Pose Transfer"
    output_type = "image"
    derives_size_from_input = True
    model_keys = ("checkpoint",)
    output_node_id = "14"

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
            "vae": "sdxl_vae.safetensors",
            "controlnet": "xinsir_openpose_sdxl_1.0.safetensors",
            "controlnet_strength": 0.8,
            "controlnet_end": 1.0,
            "pose_bbox_detector": "yolox_l.onnx",
            "pose_estimator": "dw-ll_ucoco_384_bs5.torchscript.pt",
            "upscale_model": "4xUltrasharp_4xUltrasharpV10.pt",
            "enhance_scale": 2.0,
            "enhance_steps": 20,
            "enhance_denoise": 0.3,
            "filename_prefix": "image/sdxl_pose_transfer",
        }

    def param_definitions(self) -> list[ParamDef]:
        defaults = self.default_params()
        checkpoints = list_model_files("checkpoints", [defaults["checkpoint"]])
        controlnets = list_model_files("controlnet", [defaults["controlnet"]])
        upscalers = list_model_files("upscale_models", [defaults["upscale_model"]])
        return [
            ParamDef("positive_prompt", "Positive Prompt", "str", "", multiline=True),
            ParamDef("negative_prompt", "Negative Prompt", "str", "", multiline=True),
            ParamDef("input_image", "Pose Image", "image", ""),
            ParamDef("checkpoint", "Model", "combo", defaults["checkpoint"],
                     options=checkpoints),
            ParamDef("controlnet", "ControlNet (Pose)", "combo", defaults["controlnet"],
                     options=controlnets),
            ParamDef("controlnet_strength", "Pose Strength", "float", 0.8,
                     min_val=0.0, max_val=2.0, step=0.05),
            ParamDef("controlnet_end", "Pose Hold (End %)", "float", 1.0,
                     min_val=0.0, max_val=1.0, step=0.05),
            ParamDef("seed", "Seed", "seed", 0),
            ParamDef("batch_size", "Batch Size", "int", 1, min_val=1, max_val=16),
            ParamDef("steps", "Steps", "int", 50, min_val=1, max_val=200),
            ParamDef("cfg", "CFG Scale", "float", 7.5, min_val=0.0, max_val=30.0, step=0.5),
            ParamDef("sampler_name", "Sampler", "combo", "euler",
                     options=SAMPLER_OPTIONS),
            ParamDef("scheduler", "Scheduler", "combo", "normal",
                     options=SCHEDULER_OPTIONS),
            ParamDef("denoise", "Denoise", "float", 1.0, min_val=0.0, max_val=1.0, step=0.01),
            ParamDef("upscale_model", "Upscale Model", "combo", defaults["upscale_model"],
                     options=upscalers),
            ParamDef("enhance_scale", "Upscale Factor", "float", 2.0,
                     min_val=1.0, max_val=4.0, step=0.25),
            ParamDef("enhance_steps", "Enhance Steps", "int", 20, min_val=1, max_val=100),
            ParamDef("enhance_denoise", "Enhance Denoise", "float", 0.3,
                     min_val=0.0, max_val=1.0, step=0.05),
            ParamDef("filename_prefix", "Output Prefix", "str", "image/sdxl_pose_transfer"),
        ]

    def derived_display_size(self, params: dict) -> tuple[int, int] | None:
        """The pose image's size at the SDXL budget — the base measurement, on
        this workflow's megapixels rather than the video default, so the locked
        Dimensions field shows exactly what the in-graph scaling will render."""
        return measure_derived_size(
            params.get("input_image", ""), megapixels=_TARGET_MEGAPIXELS
        )

    def build_api_payload(self, params: dict) -> dict:
        # Size the still off the pose image: derived in-graph at the SDXL budget
        # by default, or scaled to the user's explicit WxH when the derived size
        # was unlocked. The DWPose skeleton is drawn from the scaled image, so
        # the pose map shares the latent's aspect exactly.
        size_nodes, scaled_ref, width_ref, height_ref = self.image_size_nodes(
            "2", "3", ["1", 0], params, megapixels=_TARGET_MEGAPIXELS
        )
        enhance_nodes, enhanced_ref = self.enhance_image_nodes(
            "15", "16", "17", "18", "19", "20",
            image_ref=["13", 0], model_ref=["4", 0],
            positive_ref=["9", 0], negative_ref=["9", 1], vae_ref=["12", 0],
            params=params,
        )
        return {
            **size_nodes,
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": params["input_image"]},
            },
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": params["checkpoint"]},
            },
            "5": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["4", 1], "text": params["positive_prompt"]},
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["4", 1], "text": params["negative_prompt"]},
            },
            "7": {
                "class_type": "ControlNetLoader",
                "inputs": {"control_net_name": params["controlnet"]},
            },
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
                    # xinsir's SDXL ControlNets are trained on thicker skeleton
                    # sticks; the toggle follows the picked file so a swapped-in
                    # non-xinsir ControlNet gets standard sticks automatically.
                    "scale_stick_for_xinsr_cn": (
                        "enable" if "xinsir" in params["controlnet"].lower()
                        else "disable"
                    ),
                },
            },
            "9": {
                "class_type": "ControlNetApplyAdvanced",
                "inputs": {
                    "positive": ["5", 0],
                    "negative": ["6", 0],
                    "control_net": ["7", 0],
                    "image": ["8", 0],
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
                    "model": ["4", 0],
                    "positive": ["9", 0],
                    "negative": ["9", 1],
                    "latent_image": ["10", 0],
                    "seed": params["seed"],
                    "steps": params["steps"],
                    "cfg": params["cfg"],
                    "sampler_name": params["sampler_name"],
                    "scheduler": params["scheduler"],
                    "denoise": params["denoise"],
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
        }
