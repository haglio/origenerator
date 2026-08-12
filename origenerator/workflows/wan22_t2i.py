from origenerator.workflows.base import ParamDef, WorkflowTemplate


class Wan22T2iWorkflow(WorkflowTemplate):
    """WAN 2.2 14B text-to-image, dual-noise (high/low) sampling.

    The WAN 2.2 T2V model has no still-image mode, so this coaxes one out of it:
    a tiny ``EmptyHunyuanLatentVideo`` is denoised by two ``KSamplerAdvanced``
    passes (high-noise model for the first half of the steps, low-noise for the
    second), and ``ImageFromBatch`` keeps the first frame, which ``SaveImage``
    writes as a PNG. No input image and no CLIP-Vision — conditioning is text
    only, which is what separates it from :class:`Wan22I2vWorkflow`.

    The ``enhance`` toggle (off by default) appends the shared enhance tail
    (:meth:`WorkflowTemplate.enhance_image_nodes`) to the kept frame: a model
    upscale, then a low-denoise re-sample on the LOW-noise model's chain — the
    stage WAN 2.2 itself uses for late-step refinement — with the same text
    conditioning and VAE, so the enlargement carries generated texture rather
    than interpolated pixels.
    """

    name = "wan22_t2i"
    version = "v002"
    display_name = "WAN 2.2 Text-to-Image"
    output_type = "image"
    model_keys = ("unet_high", "unet_low")
    output_node_id = "14"

    def default_params(self) -> dict:
        return {
            "positive_prompt": "",
            "negative_prompt": "",
            "noise_seed": 0,
            "seed": 0,
            "width": 1088,
            "height": 1920,
            "length": 5,
            "batch_size": 1,
            "steps": 20,
            "cfg": 3.5,
            "sampler_name": "euler",
            "scheduler": "simple",
            "shift_high": 8.0,
            "shift_low": 8.0,
            "enhance": False,
            "upscale_model": "4xUltrasharp_4xUltrasharpV10.pt",
            "enhance_scale": 2.0,
            "enhance_steps": 20,
            "enhance_denoise": 0.15,
            "filename_prefix": "image/wan22_t2i",
            "clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
            "vae_name": "wan_2.1_vae.safetensors",
            "unet_high": "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors",
            "unet_low": "wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors",
        }

    def param_definitions(self) -> list[ParamDef]:
        return [
            ParamDef("positive_prompt", "Positive Prompt", "str", "", multiline=True),
            ParamDef("negative_prompt", "Negative Prompt", "str", "", multiline=True),
            ParamDef("noise_seed", "Noise Seed (Stage 1)", "seed", 0),
            ParamDef("seed", "Seed (Stage 2)", "seed", 0),
            ParamDef("width", "Width", "int", 1088, min_val=64, max_val=2048, step=16),
            ParamDef("height", "Height", "int", 1920, min_val=64, max_val=2048, step=16),
            ParamDef("steps", "Steps", "int", 20, min_val=1, max_val=50),
            ParamDef("cfg", "CFG Scale", "float", 3.5, min_val=0.0, max_val=30.0, step=0.1),
            ParamDef("shift_high", "Shift (High)", "float", 8.0, min_val=0.0, max_val=20.0, step=0.5),
            ParamDef("shift_low", "Shift (Low)", "float", 8.0, min_val=0.0, max_val=20.0, step=0.5),
            ParamDef("enhance", "Enhance (upscale + re-sample)", "bool", False),
            ParamDef("enhance_scale", "Upscale Factor", "float", 2.0,
                     min_val=1.0, max_val=4.0, step=0.25),
            ParamDef("enhance_steps", "Enhance Steps", "int", 20, min_val=1, max_val=100),
            ParamDef("enhance_denoise", "Enhance Denoise", "float", 0.15,
                     min_val=0.0, max_val=1.0, step=0.05),
            ParamDef("filename_prefix", "Output Prefix", "str", "image/wan22_t2i"),
        ]

    def build_api_payload(self, params: dict) -> dict:
        half_steps = params["steps"] // 2
        enhance_nodes: dict = {}
        enhanced_ref = ["13", 0]  # enhance off: save the kept frame as-is
        if params.get("enhance"):
            # Re-sample on the low-noise chain ("6") — WAN 2.2's own refinement
            # stage — with the same conditioning and VAE as the base pass. The
            # WAN VAE encodes the kept frame as a one-frame video latent, which
            # is exactly the shape the t2i pass itself denoises.
            enhance_nodes, enhanced_ref = self.enhance_image_nodes(
                "15", "16", "17", "18", "19", "20",
                image_ref=["13", 0], model_ref=["6", 0],
                positive_ref=["7", 0], negative_ref=["8", 0], vae_ref=["2", 0],
                params=params,
            )
        return {
            "1": {
                "class_type": "CLIPLoader",
                "inputs": {
                    "clip_name": params["clip_name"],
                    "type": "wan",
                    "device": "default",
                },
            },
            "2": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": params["vae_name"]},
            },
            "3": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": params["unet_high"], "weight_dtype": "default"},
            },
            "4": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": params["unet_low"], "weight_dtype": "default"},
            },
            "5": {
                "class_type": "ModelSamplingSD3",
                "inputs": {"model": ["3", 0], "shift": params["shift_high"]},
            },
            "6": {
                "class_type": "ModelSamplingSD3",
                "inputs": {"model": ["4", 0], "shift": params["shift_low"]},
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["1", 0], "text": params["positive_prompt"]},
            },
            "8": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["1", 0], "text": params["negative_prompt"]},
            },
            "9": {
                "class_type": "EmptyHunyuanLatentVideo",
                "inputs": {
                    "width": params["width"],
                    "height": params["height"],
                    "length": params["length"],
                    "batch_size": params["batch_size"],
                },
            },
            "10": {
                "class_type": "KSamplerAdvanced",
                "inputs": {
                    "model": ["5", 0],
                    "positive": ["7", 0],
                    "negative": ["8", 0],
                    "latent_image": ["9", 0],
                    "add_noise": "enable",
                    "noise_seed": params["noise_seed"],
                    "steps": params["steps"],
                    "cfg": params["cfg"],
                    "sampler_name": params["sampler_name"],
                    "scheduler": params["scheduler"],
                    "start_at_step": 0,
                    "end_at_step": half_steps,
                    "return_with_leftover_noise": "enable",
                },
            },
            "11": {
                "class_type": "KSamplerAdvanced",
                "inputs": {
                    "model": ["6", 0],
                    "positive": ["7", 0],
                    "negative": ["8", 0],
                    "latent_image": ["10", 0],
                    "add_noise": "disable",
                    "noise_seed": params["seed"],
                    "steps": params["steps"],
                    "cfg": params["cfg"],
                    "sampler_name": params["sampler_name"],
                    "scheduler": params["scheduler"],
                    "start_at_step": half_steps,
                    "end_at_step": 10000,
                    "return_with_leftover_noise": "disable",
                },
            },
            "12": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["11", 0], "vae": ["2", 0]},
            },
            "13": {
                "class_type": "ImageFromBatch",
                "inputs": {"image": ["12", 0], "batch_index": 0, "length": 1},
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
