from origenerator.workflows.base import ParamDef, WorkflowTemplate
from origenerator.workflows.derived_size import measure_image_size, override_size
from origenerator.workflows.model_files import list_detector_files, list_model_files

_DEFAULT_CHECKPOINT = "reapony_v80.safetensors"
_DEFAULT_UPSCALE_MODEL = "4xUltrasharp_4xUltrasharpV10.pt"
# The detail pass's detectors. Named rather than derived so a run records which
# model found its regions; an install with neither dims the pass instead (see
# :func:`~origenerator.workflows.model_files.list_detector_files`).
_DEFAULT_FACE_DETECTOR = "face_yolov8m.pt"
_DEFAULT_HAND_DETECTOR = "hand_yolov8s.pt"


class ImageEnhanceWorkflow(WorkflowTemplate):
    """Upscale and enhance an existing image — the standalone form of the
    enhance tail the generation workflows append.

    Takes any image (a past generation, an import, a file on disk) and runs it
    through the shared tail (:meth:`WorkflowTemplate.enhance_image_nodes`): an
    ESRGAN-family model upscale for sharpness, then a low-denoise SDXL sampling
    pass that re-imagines the enlarged pixels into real texture. The SDXL
    checkpoint does the refining regardless of what made the source image —
    at ``enhance_denoise`` this low it adds texture without repainting, which
    is what lets one enhancer serve every workflow's output (and imports,
    whose maker is unknown). The prompts steer that texture; a batch enhance
    seeds them from the source generation's own prompts.

    That tail's gentleness is also its ceiling: it cannot mend a mouth fused
    into its teeth or a hand with a finger too many, because the denoise that
    would redraw them redraws everything else too. ``enhance_detail_fix`` adds a second
    stage past it (:meth:`WorkflowTemplate.detail_fix_nodes`) that finds the
    faces and hands and re-samples each one alone, at its own much higher
    denoise, leaving every pixel outside those regions exactly as the tail left
    it. Off by default: it needs detectors installed, and it costs a sampling
    run per region found.

    Machinery, not a peer workflow (``selectable`` False): its results are
    upgrades of existing images, not generations with a shared nature, so it
    never appears in the Generate dropdown and its finished rows never live in
    the gallery — each is folded into the image it enhanced
    (:func:`origenerator.gallery.enhance.fold_enhancement`), which keeps its
    folder and star and simply becomes the enhanced version. The output size
    is the source's own dimensions at ``enhance_scale`` — no pixel budget.
    """

    name = "image_enhance"
    version = "v002"
    display_name = "Image Enhance"
    output_type = "image"
    derives_size_from_input = True
    selectable = False
    model_keys = ("checkpoint",)
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
            "checkpoint": _DEFAULT_CHECKPOINT,
            "vae": "sdxl_vae.safetensors",
            "upscale_model": _DEFAULT_UPSCALE_MODEL,
            "enhance_scale": 2.0,
            "enhance_steps": 20,
            "enhance_denoise": 0.15,
            "enhance_detail_fix": False,
            "enhance_detail_denoise": 0.45,
            "enhance_face_detector": _DEFAULT_FACE_DETECTOR,
            "enhance_hand_detector": _DEFAULT_HAND_DETECTOR,
            "filename_prefix": "image/image_enhance",
        }

    def param_definitions(self) -> list[ParamDef]:
        checkpoints = list_model_files("checkpoints", [_DEFAULT_CHECKPOINT])
        upscalers = list_model_files("upscale_models", [_DEFAULT_UPSCALE_MODEL])
        detectors = list_detector_files()
        return [
            ParamDef("input_image", "Image", "image", ""),
            ParamDef("positive_prompt", "Positive Prompt", "str", "", multiline=True),
            ParamDef("negative_prompt", "Negative Prompt", "str", "", multiline=True),
            ParamDef("checkpoint", "Model", "combo", _DEFAULT_CHECKPOINT,
                     options=checkpoints),
            ParamDef("seed", "Seed", "seed", 0),
            ParamDef("upscale_model", "Upscale Model", "combo", _DEFAULT_UPSCALE_MODEL,
                     options=upscalers),
            ParamDef("enhance_scale", "Upscale Factor", "float", 2.0,
                     min_val=1.0, max_val=4.0, step=0.25),
            ParamDef("enhance_steps", "Enhance Steps", "int", 20, min_val=1, max_val=100),
            ParamDef("enhance_denoise", "Enhance Denoise", "float", 0.15,
                     min_val=0.0, max_val=1.0, step=0.05),
            ParamDef("enhance_detail_fix", "Fix Faces & Hands", "bool", False),
            # Floored above zero: the detailer node rejects 0, and a pass that
            # repaints nothing is a slower way of not running one.
            ParamDef("enhance_detail_denoise", "Detail Denoise", "float", 0.45,
                     min_val=0.05, max_val=1.0, step=0.05),
            ParamDef("enhance_face_detector", "Face Detector", "combo",
                     _DEFAULT_FACE_DETECTOR, options=detectors),
            ParamDef("enhance_hand_detector", "Hand Detector", "combo",
                     _DEFAULT_HAND_DETECTOR, options=detectors),
        ]

    def derived_display_size(self, params: dict) -> tuple[int, int] | None:
        """The source image's own size at ``enhance_scale`` — what the tail's
        rescale lands on — rather than a pixel-budget derivation. ``None`` when
        no image is picked or it can't be measured, so the form shows nothing
        until one resolves."""
        size = measure_image_size(params.get("input_image", ""))
        if size is None:
            return None
        scale = params.get("enhance_scale", 1.0)
        return round(size[0] * scale), round(size[1] * scale)

    @staticmethod
    def _with_installed_detectors(params: dict) -> dict:
        """``params`` with any detail-pass detector ComfyUI hasn't got blanked.

        Faces and hands are found by two different models, and having only one
        of them installed is an ordinary state — but ComfyUI validates the name
        and rejects the whole prompt over the missing one, which would take the
        half that could have run down with it. Blanked, that half simply builds
        no nodes (see :meth:`WorkflowTemplate.detail_fix_nodes`). With neither
        installed the pass builds nothing at all, which is the state the Enhance
        panel dims its checkbox for.
        """
        if not params.get("enhance_detail_fix"):
            return params
        installed = set(list_detector_files())
        return dict(params, **{
            key: (params.get(key) if params.get(key) in installed else "")
            for key in ("enhance_face_detector", "enhance_hand_detector")
        })

    def build_api_payload(self, params: dict) -> dict:
        tail, enhanced_ref = self.enhance_image_nodes(
            "6", "7", "8", "9", "10", "11",
            image_ref=["1", 0], model_ref=["2", 0],
            positive_ref=["3", 0], negative_ref=["4", 0], vae_ref=["5", 0],
            params=params,
        )
        # An unlocked explicit WxH replaces the relative rescale with an exact
        # one, so the Dimensions override actually governs the saved size.
        override = override_size(params)
        if override is not None:
            width, height = override
            tail["8"] = {
                "class_type": "ImageScale",
                "inputs": {
                    "image": ["7", 0],
                    "upscale_method": "lanczos",
                    "width": width,
                    "height": height,
                    "crop": "disabled",
                },
            }
        detail, saved_ref = self.detail_fix_nodes(
            ("13", "14", "15"), ("16", "17", "18"),
            image_ref=enhanced_ref, model_ref=["2", 0], clip_ref=["2", 1],
            vae_ref=["5", 0], positive_ref=["3", 0], negative_ref=["4", 0],
            params=self._with_installed_detectors(params),
        )
        return {
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": params["input_image"]},
            },
            "2": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": params["checkpoint"]},
            },
            "3": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["2", 1], "text": params["positive_prompt"]},
            },
            "4": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["2", 1], "text": params["negative_prompt"]},
            },
            "5": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": params["vae"]},
            },
            **tail,
            **detail,
            "12": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": saved_ref,
                    "filename_prefix": params["filename_prefix"],
                },
            },
        }
