from origenerator.workflows.base import ParamDef
from origenerator.workflows.model_files import list_lora_files, list_model_files
from origenerator.workflows.stroke_authored import (
    REFERENCE_HEIGHT,
    REFERENCE_WIDTH,
    StrokeAuthoredWorkflow,
)
from origenerator.workflows.stroke_control_video import (
    control_marker_positions,
    render_control_video,
)


class Wan22FunStrokeI2vWorkflow(StrokeAuthoredWorkflow):
    """WAN 2.2 Fun-Control image-to-video following an authored stroke plan.

    The other stroke-authored workflow (WAN 2.1 ATI) obeys its plan strictly
    but runs a base that never learned this content's acts; this one trades a
    little obedience for the full WAN 2.2 ecosystem — the same high/low UNET
    pair layout and LoRA pairs as the standard i2v workflow — by expressing
    the plan as a rendered control video (see stroke_control_video) that the
    Fun-Control models condition on: a primary marker riding the stroke and a
    secondary marker swaying at the base, one per hand. The plan also becomes
    the funscript (:meth:`~StrokeAuthoredWorkflow.authored_actions`), and the
    decoded frames get the HunyuanVideo-Foley scoring pass like every video
    workflow.

    Size derives from the input image app-side (the control video and the
    conditioning must share one pixel space), with the stroke coordinates
    authored in the fixed reference frame and rescaled in — all inherited
    from :class:`StrokeAuthoredWorkflow`, auto-aim included.
    """

    name = "wan22_fun_stroke_i2v"
    version = "v001"
    display_name = "WAN 2.2 Fun Stroke (I2V)"
    output_type = "video"
    derives_size_from_input = True
    model_keys = ("unet_high", "unet_low")
    lora_keys = ("lora_high", "lora_low")
    output_node_id = "15"

    def default_params(self) -> dict:
        return {
            "positive_prompt": "",
            "negative_prompt": "",
            "input_image": "",
            "seed": 0,
            "frame_count": 81,
            "batch_size": 1,
            "steps": 20,
            "cfg": 3.5,
            "sampler_name": "euler",
            "scheduler": "simple",
            "shift_high": 8.0,
            "shift_low": 8.0,
            "frame_rate": 16.0,
            "stroke_hz": 1.2,
            "stroke_x": 255,
            "stroke_top": 490,
            "stroke_bottom": 650,
            "anchor_x": 233,
            "anchor_y": 760,
            "audio_prompt": "",
            "audio_negative_prompt": "noisy, harsh",
            "audio_seed": 0,
            "foley_model": "hunyuanvideo_foley_fp8_e4m3fn.safetensors",
            "foley_vae": "vae_128d_48k_fp16.safetensors",
            "foley_synchformer": "synchformer_state_dict_fp16.safetensors",
            "filename_prefix": "video/wan22_fun_stroke",
            "clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
            "vae_name": "wan_2.1_vae.safetensors",
            "unet_high": "wan2.2_fun_control_high_noise_14B_fp8_scaled.safetensors",
            "unet_low": "wan2.2_fun_control_low_noise_14B_fp8_scaled.safetensors",
            "lora_high": "wan22-f4c3spl4sh-100epoc-high-k3nk.safetensors",
            "lora_low": "wan22-f4c3spl4sh-154epoc-low-k3nk.safetensors",
            "lora_strength_high": 1.0,
            "lora_strength_low": 1.0,
        }

    def param_definitions(self) -> list[ParamDef]:
        defaults = self.default_params()
        models = list_model_files("diffusion_models", [defaults["unet_high"], defaults["unet_low"]])
        loras = list_lora_files([defaults["lora_high"], defaults["lora_low"]])
        return [
            ParamDef("positive_prompt", "Positive Prompt", "str", "", multiline=True),
            ParamDef("negative_prompt", "Negative Prompt", "str", "", multiline=True),
            ParamDef("input_image", "Input Image", "image", ""),
            ParamDef("audio_prompt", "Audio Prompt", "str", "", multiline=True),
            ParamDef("audio_negative_prompt", "Audio Negative Prompt", "str", "noisy, harsh", multiline=True),
            ParamDef("seed", "Seed", "seed", 0),
            ParamDef("audio_seed", "Audio Seed", "seed", 0),
            ParamDef("stroke_hz", "Stroke Rate (Hz)", "float", 1.2, min_val=0.2, max_val=4.0, step=0.1),
            # Stroke coordinates are authored in the 480×864 reference frame and
            # rescaled into the derived output size at payload build, so their
            # ranges are the reference frame's bounds (width for X, height for Y).
            ParamDef("stroke_x", "Stroke X", "int", 255, min_val=0, max_val=REFERENCE_WIDTH),
            ParamDef("stroke_top", "Stroke Top Y", "int", 490, min_val=0, max_val=REFERENCE_HEIGHT),
            ParamDef("stroke_bottom", "Stroke Bottom Y", "int", 650, min_val=0, max_val=REFERENCE_HEIGHT),
            ParamDef("anchor_x", "Anchor X", "int", 233, min_val=0, max_val=REFERENCE_WIDTH),
            ParamDef("anchor_y", "Anchor Y", "int", 760, min_val=0, max_val=REFERENCE_HEIGHT),
            ParamDef("frame_count", "Frames", "int", 81, min_val=5, max_val=121, step=4),
            ParamDef("steps", "Steps", "int", 20, min_val=1, max_val=50),
            ParamDef("cfg", "CFG Scale", "float", 3.5, min_val=0.0, max_val=30.0, step=0.1),
            ParamDef("shift_high", "Shift (High)", "float", 8.0, min_val=0.0, max_val=20.0, step=0.5),
            ParamDef("shift_low", "Shift (Low)", "float", 8.0, min_val=0.0, max_val=20.0, step=0.5),
            ParamDef("unet_high", "Model (High)", "combo", defaults["unet_high"], options=models),
            ParamDef("unet_low", "Model (Low)", "combo", defaults["unet_low"], options=models),
            ParamDef("lora_high", "LoRA (High)", "combo", defaults["lora_high"], options=loras),
            ParamDef("lora_strength_high", "LoRA Strength (High)", "float", 1.0, min_val=0.0, max_val=2.0, step=0.05),
            ParamDef("lora_low", "LoRA (Low)", "combo", defaults["lora_low"], options=loras),
            ParamDef("lora_strength_low", "LoRA Strength (Low)", "float", 1.0, min_val=0.0, max_val=2.0, step=0.05),
            ParamDef("frame_rate", "Frame Rate", "float", 16.0, min_val=1.0, max_val=60.0, step=1.0),
            ParamDef("filename_prefix", "Output Prefix", "str", "video/wan22_fun_stroke"),
        ]

    def _control_video_path(self, stroke_params: dict, width: int, height: int) -> str:
        """Render (or reuse) this plan's control video and return its path."""
        positions = control_marker_positions(
            self._stroke_series(stroke_params),
            stroke_params["stroke_x"],
            stroke_params["stroke_top"],
            stroke_params["anchor_x"],
            stroke_params["anchor_y"],
            stroke_params["frame_count"],
        )
        return str(render_control_video(positions, width, height, stroke_params["frame_rate"]))

    def build_api_payload(self, params: dict) -> dict:
        # The control video and the conditioning must share one pixel space, so
        # the size is derived app-side (or taken from the unlocked override) and
        # the authored stroke — auto-aimed at the detected anchor unless the
        # user placed it — is rescaled into it before rendering.
        params = self._auto_aim_params(params)
        width, height = self._output_size(params)
        stroke_params = self._scaled_stroke_params(params, width, height)
        control_video = self._control_video_path(stroke_params, width, height)
        foley, audio_ref = self.foley_audio_nodes("20", "21", "22", ["13", 0], params)
        lora_high, model_high = self.lora_model_input(
            "5", ["3", 0], params["lora_high"], params["lora_strength_high"]
        )
        lora_low, model_low = self.lora_model_input(
            "6", ["4", 0], params["lora_low"], params["lora_strength_low"]
        )
        half_steps = params["steps"] // 2
        return {
            **foley,
            **lora_high,
            **lora_low,
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
            "7": {
                "class_type": "ModelSamplingSD3",
                "inputs": {"model": model_high, "shift": params["shift_high"]},
            },
            "8": {
                "class_type": "ModelSamplingSD3",
                "inputs": {"model": model_low, "shift": params["shift_low"]},
            },
            "9": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["1", 0], "text": params["positive_prompt"]},
            },
            "10": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["1", 0], "text": params["negative_prompt"]},
            },
            "11": {
                "class_type": "LoadImage",
                "inputs": {"image": params["input_image"]},
            },
            "12": {
                "class_type": "VHS_LoadVideoPath",
                "inputs": {
                    "video": control_video,
                    "force_rate": 0,
                    "custom_width": 0,
                    "custom_height": 0,
                    "frame_load_cap": 0,
                    "skip_first_frames": 0,
                    "select_every_nth": 1,
                },
            },
            "16": {
                "class_type": "Wan22FunControlToVideo",
                "inputs": {
                    "positive": ["9", 0],
                    "negative": ["10", 0],
                    "vae": ["2", 0],
                    "width": width,
                    "height": height,
                    "length": params["frame_count"],
                    "batch_size": params["batch_size"],
                    "ref_image": ["11", 0],
                    "control_video": ["12", 0],
                },
            },
            "17": {
                "class_type": "KSamplerAdvanced",
                "inputs": {
                    "model": ["7", 0],
                    "positive": ["16", 0],
                    "negative": ["16", 1],
                    "latent_image": ["16", 2],
                    "add_noise": "enable",
                    "noise_seed": params["seed"],
                    "steps": params["steps"],
                    "cfg": params["cfg"],
                    "sampler_name": params["sampler_name"],
                    "scheduler": params["scheduler"],
                    "start_at_step": 0,
                    "end_at_step": half_steps,
                    "return_with_leftover_noise": "enable",
                },
            },
            "18": {
                "class_type": "KSamplerAdvanced",
                "inputs": {
                    "model": ["8", 0],
                    "positive": ["16", 0],
                    "negative": ["16", 1],
                    "latent_image": ["17", 0],
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
            "13": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["18", 0], "vae": ["2", 0]},
            },
            "14": {
                "class_type": "CreateVideo",
                "inputs": {
                    "images": ["13", 0],
                    "fps": params["frame_rate"],
                    "audio": audio_ref,
                },
            },
            "15": {
                "class_type": "SaveVideo",
                "inputs": {
                    "video": ["14", 0],
                    "filename_prefix": params["filename_prefix"],
                    "format": "auto",
                    "codec": "auto",
                },
            },
        }
