from origenerator.config import CUSTOM_POSES_DIR
from origenerator.workflows.base import (
    SAMPLER_OPTIONS, SCHEDULER_OPTIONS, ParamDef, WorkflowTemplate,
)
from origenerator.workflows.derived_size import measure_derived_size
from origenerator.workflows.model_arch import SD15, SDXL
from origenerator.workflows.model_files import ANY, list_model_files

# The pixel budget the output is scaled to. SDXL is trained at ~1 megapixel, so
# the pose image's aspect ratio is kept at that budget — unlike the video
# workflows' 0.4 MP, which would starve SDXL of resolution.
_TARGET_MEGAPIXELS = 1.0


class SdxlPoseTransferWorkflow(WorkflowTemplate):
    """SDXL text-to-image steered by the structure of an input image.

    A variation of :class:`~origenerator.workflows.sdxl_t2i.SdxlT2iWorkflow`
    that re-skins an image: a structure map extracted from the input is applied
    through an SDXL ControlNet, so the render keeps the input's pose, angle and
    proportions while the prompt and checkpoint replace everything else about
    how it looks. Only the map crosses over — the sampler still denoises from
    scratch (denoise 1.0), which is what lets the presentation change
    completely while the structure holds.

    Two structure modes. "depth" (the default) conditions on a DepthAnythingV2
    map: it captures every body, their contact and the camera angle no matter
    how entangled or tightly framed the scene, and carries no color or texture
    to leak through. "pose" conditions on a DWPose skeleton instead — a looser
    rein that only pins the figure, but DWPose's person detector collapses on
    close-ups and horizontal, overlapping bodies (observed fusing two people
    into one figure), so it fits single mostly-upright subjects only. The union
    ControlNet serves both modes through one file; SetUnionControlNetType picks
    the head, and is added only for union files because a plain single-purpose
    ControlNet crashes on the extra argument.

    The output size is derived from the input image (its aspect ratio at the
    SDXL pixel budget), the same locked-Dimensions treatment the i2v workflows
    get, because the structure map is stretched to the output canvas — a
    hand-set size with a different aspect would distort the very structure it
    exists to preserve.

    Like sdxl_t2i, the render is optionally finished by the shared
    upscale/enhance tail (:meth:`WorkflowTemplate.enhance_image_nodes`) via the
    ``enhance`` toggle — off by default, since enhancement is a layer the
    gallery's Enhance subpanel applies per folder afterward. Its second
    sampling pass reuses the ControlNet-applied conditioning, so the structure
    stays pinned while the checkpoint sharpens and re-textures the enlarged
    image.
    """

    name = "sdxl_pose_transfer"
    version = "v004"
    display_name = "SDXL Pose Transfer"
    output_type = "image"
    derives_size_from_input = True
    model_keys = ("checkpoint",)
    extra_enhance_keys = ("upscale_model",)  # only the tail loads it
    output_node_id = "14"
    # The pre-enhance render, saved when the tail runs. 21 is the union
    # ControlNet and 22/23 the depth pair, so this sits clear of both.
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
            # Kept low deliberately: at 0.3 the enhance pass re-imagined creases
            # and skin folds into wounds/disfigurements (user-reported). 0.15
            # refines texture without redrawing anatomy.
            "enhance_denoise": 0.15,
            "filename_prefix": "image/sdxl_pose_transfer",
        }

    def param_definitions(self) -> list[ParamDef]:
        defaults = self.default_params()
        checkpoints = list_model_files(
            "checkpoints", [defaults["checkpoint"]], accepts=(SDXL, SD15),
        )
        # SDXL only, unlike the checkpoint above: a ControlNet is built against
        # one UNet's block shapes, and the SD1.5 ones installed here fail on an
        # SDXL model rather than merely drifting the way a mismatched VAE does.
        controlnets = list_model_files(
            "controlnet", [defaults["controlnet"]], accepts=(SDXL,),
        )
        upscalers = list_model_files(
            "upscale_models", [defaults["upscale_model"]], accepts=ANY,
        )
        return [
            ParamDef("positive_prompt", "Positive Prompt", "str", "", multiline=True),
            ParamDef("negative_prompt", "Negative Prompt", "str", "", multiline=True),
            ParamDef("input_image", "Structure Image", "image", "",
                     browse_dir=CUSTOM_POSES_DIR),
            ParamDef("checkpoint", "Model", "combo", defaults["checkpoint"],
                     options=checkpoints),
            ParamDef("control_mode", "Structure From", "combo", "depth",
                     options=["depth", "pose"]),
            ParamDef("controlnet", "ControlNet", "combo", defaults["controlnet"],
                     options=controlnets),
            ParamDef("controlnet_strength", "Structure Strength", "float", 0.8,
                     min_val=0.0, max_val=2.0, step=0.05),
            ParamDef("controlnet_end", "Structure Hold (End %)", "float", 1.0,
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
            ParamDef("enhance", "Enhance (upscale + re-sample)", "bool", False),
            ParamDef("upscale_model", "Upscale Model", "combo", defaults["upscale_model"],
                     options=upscalers),
            ParamDef("enhance_scale", "Upscale Factor", "float", 2.0,
                     min_val=1.0, max_val=4.0, step=0.25),
            ParamDef("enhance_steps", "Enhance Steps", "int", 20, min_val=1, max_val=100),
            ParamDef("enhance_denoise", "Enhance Denoise", "float", 0.15,
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

    @staticmethod
    def _structure_nodes(params: dict, scaled_ref) -> tuple[dict, list]:
        """The mode's extractor subgraph and the hint-image ref it produces.

        Both modes read the already-scaled image, so the map they draw shares
        the latent's aspect exactly.
        """
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
                        # xinsir's SDXL ControlNets are trained on thicker
                        # skeleton sticks; the toggle follows the picked file so
                        # a swapped-in non-xinsir ControlNet gets standard
                        # sticks automatically.
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

    @staticmethod
    def _controlnet_nodes(params: dict) -> tuple[dict, list]:
        """The ControlNet loading subgraph and the CONTROL_NET ref to apply.

        A union file gets a SetUnionControlNetType picking the mode's head; a
        plain single-purpose ControlNet is passed straight through, because it
        crashes on the union node's extra argument.
        """
        nodes = {
            "7": {
                "class_type": "ControlNetLoader",
                "inputs": {"control_net_name": params["controlnet"]},
            },
        }
        if "union" not in params["controlnet"].lower():
            return nodes, ["7", 0]
        nodes["21"] = {
            "class_type": "SetUnionControlNetType",
            "inputs": {
                "control_net": ["7", 0],
                "type": "openpose" if params["control_mode"] == "pose" else "depth",
            },
        }
        return nodes, ["21", 0]

    def build_api_payload(self, params: dict) -> dict:
        # Size the still off the input image: derived in-graph at the SDXL
        # budget by default, or scaled to the user's explicit WxH when the
        # derived size was unlocked.
        size_nodes, scaled_ref, width_ref, height_ref = self.image_size_nodes(
            "2", "3", ["1", 0], params, megapixels=_TARGET_MEGAPIXELS
        )
        structure, hint_ref = self._structure_nodes(params, scaled_ref)
        controlnet, controlnet_ref = self._controlnet_nodes(params)
        enhance_nodes: dict = {}
        enhanced_ref = ["13", 0]  # enhance off: save the plain decode
        if params.get("enhance"):
            # The enhance pass re-samples on the ControlNet-applied conditioning
            # (node 9), so the upscale can't drift off the structure map.
            enhance_nodes, enhanced_ref = self.enhance_image_nodes(
                "15", "16", "17", "18", "19", "20",
                image_ref=["13", 0], model_ref=["4", 0],
                positive_ref=["9", 0], negative_ref=["9", 1], vae_ref=["12", 0],
                params=params,
            )
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
            "5": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["4", 1], "text": params["positive_prompt"]},
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["4", 1], "text": params["negative_prompt"]},
            },
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
            # With the tail on, keep the base render too — it is made on the way
            # and would otherwise be discarded, leaving no original.
            **self.base_save_node(self.base_output_node_id, ["13", 0], params),
        }
