import json

from origenerator.workflows.base import ParamDef
from origenerator.workflows.model_files import NO_LORA, list_lora_files, list_model_files
from origenerator.workflows.stroke_authored import (
    REFERENCE_HEIGHT,
    REFERENCE_WIDTH,
    TRACK_POINTS,
    StrokeAuthoredWorkflow,
)

# The three cluster points ride the stroke slightly staggered (as derisked in
# the PoC): enough spread to read as a hand, not so much it smears the patch.
_CLUSTER_OFFSETS = ((-5.0, -30.0), (3.0, 0.0), (-3.0, 30.0))


class Wan21AtiI2vWorkflow(StrokeAuthoredWorkflow):
    """WAN 2.1 ATI image-to-video: the video follows an authored stroke track.

    Motion authorship is flipped relative to the other video workflows: a
    stroke is authored first (``stroke_*`` params), ``WanTrackToVideo``
    conditions the ATI-finetuned WAN 2.1 checkpoint on it, and the video obeys.
    The same track then becomes the funscript (:meth:`authored_actions`) — one
    source, exact by construction, no pixel measurement. The decoded frames
    still get the HunyuanVideo-Foley scoring pass, muxed by ``CreateVideo``.

    The output size is derived from the input image like the WAN 2.2 workflows,
    but app-side rather than in-graph (see :meth:`build_api_payload`): its
    ``WanTrackToVideo`` needs the integer size *and* a track whose coordinates
    share that space, and an in-graph ``GetImageSize`` couldn't feed the track,
    which is built here. The stroke is authored in a fixed 480×864 reference
    frame and rescaled into the derived size, so one authored track fits any
    aspect ratio. Frame count stops at 113 because ComfyUI's track resampler
    faults at exactly 121 frames (its length-1=120 off-by-one).

    LoRAs come as a high/low-noise pair like the WAN 2.2 workflows take,
    emulated on this single 2.1 base by splitting the denoise into two
    ``KSamplerAdvanced`` stages at ``steps // 2`` — the high-noise LoRA
    patches the early-step model, the low-noise one the late-step model, both
    branching off the one UNET. Either slot may be "None".
    """

    name = "wan21_ati_i2v"
    version = "v006"
    display_name = "WAN 2.1 ATI (Stroke-Tracked I2V)"
    output_type = "video"
    derives_size_from_input = True
    model_keys = ("unet",)
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
            "cfg": 5.0,
            "sampler_name": "euler",
            "scheduler": "simple",
            "shift": 8.0,
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
            "filename_prefix": "video/wan21_ati_i2v",
            "clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
            "vae_name": "wan_2.1_vae.safetensors",
            "clip_vision_name": "clip_vision_h.safetensors",
            "unet": "Wan2_1-I2V-ATI-14B_fp8_e4m3fn.safetensors",
            "lora_high": NO_LORA,
            "lora_strength_high": 1.0,
            "lora_low": NO_LORA,
            "lora_strength_low": 1.0,
        }

    def param_definitions(self) -> list[ParamDef]:
        defaults = self.default_params()
        models = list_model_files("diffusion_models", [defaults["unet"]])
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
            ParamDef("frame_count", "Frames", "int", 81, min_val=5, max_val=113, step=4),
            ParamDef("steps", "Steps", "int", 20, min_val=1, max_val=50),
            ParamDef("cfg", "CFG Scale", "float", 5.0, min_val=0.0, max_val=30.0, step=0.1),
            ParamDef("shift", "Shift", "float", 8.0, min_val=0.0, max_val=20.0, step=0.5),
            ParamDef("unet", "Model", "combo", defaults["unet"], options=models),
            ParamDef("lora_high", "LoRA (High)", "combo", defaults["lora_high"], options=list_lora_files([])),
            ParamDef("lora_strength_high", "LoRA Strength (High)", "float", 1.0, min_val=0.0, max_val=2.0, step=0.05),
            ParamDef("lora_low", "LoRA (Low)", "combo", defaults["lora_low"], options=list_lora_files([])),
            ParamDef("lora_strength_low", "LoRA Strength (Low)", "float", 1.0, min_val=0.0, max_val=2.0, step=0.05),
            ParamDef("frame_rate", "Frame Rate", "float", 16.0, min_val=1.0, max_val=60.0, step=1.0),
            ParamDef("filename_prefix", "Output Prefix", "str", "video/wan21_ati_i2v"),
        ]

    def _stroke_tracks(self, params: dict) -> str:
        """The tracks JSON: three staggered points riding the authored stroke
        series, plus one static point pinning the anchor. 121 points at 24fps,
        ATI's fixed convention."""
        amplitude = (params["stroke_bottom"] - params["stroke_top"]) / 2
        series = self._stroke_series(params)
        tracks = []
        for x_off, y_off in _CLUSTER_OFFSETS:
            spread = min(abs(y_off), amplitude * 0.4) * (1 if y_off >= 0 else -1)
            tracks.append([
                {"x": float(params["stroke_x"] + x_off), "y": float(y + spread)}
                for y in series
            ])
        tracks.append(
            [{"x": float(params["anchor_x"]), "y": float(params["anchor_y"])}] * TRACK_POINTS
        )
        return json.dumps(tracks)

    def build_api_payload(self, params: dict) -> dict:
        # ATI can't derive its size in-graph (its WanTrackToVideo needs the
        # integer size AND a track whose coordinates share that space), so both
        # are built here: the size is the input image's derived size (or the
        # unlocked override) and the authored stroke — auto-aimed at the
        # detected anchor unless the user placed it — is rescaled into it.
        params = self._auto_aim_params(params)
        width, height = self._output_size(params)
        stroke_params = self._scaled_stroke_params(params, width, height)
        foley, audio_ref = self.foley_audio_nodes("20", "21", "22", ["13", 0], params)
        # High/low-noise LoRA pair, emulated on the single 2.1 base: the
        # denoise splits into two stages at steps//2, and each stage's model
        # chain branches off the one UNET with its own optional LoRA ("None"
        # omits that loader; the stage runs the base unmodified).
        lora_high, model_high = self.lora_model_input(
            "10", ["4", 0], params["lora_high"], params["lora_strength_high"]
        )
        lora_low, model_low = self.lora_model_input(
            "16", ["4", 0], params["lora_low"], params["lora_strength_low"]
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
                "class_type": "CLIPVisionLoader",
                "inputs": {"clip_name": params["clip_vision_name"]},
            },
            "4": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": params["unet"], "weight_dtype": "default"},
            },
            "5": {
                "class_type": "ModelSamplingSD3",
                "inputs": {"model": model_high, "shift": params["shift"]},
            },
            "17": {
                "class_type": "ModelSamplingSD3",
                "inputs": {"model": model_low, "shift": params["shift"]},
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["1", 0], "text": params["positive_prompt"]},
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["1", 0], "text": params["negative_prompt"]},
            },
            "8": {
                "class_type": "LoadImage",
                "inputs": {"image": params["input_image"]},
            },
            "9": {
                "class_type": "CLIPVisionEncode",
                "inputs": {
                    "clip_vision": ["3", 0],
                    "image": ["8", 0],
                    "crop": "center",
                },
            },
            "11": {
                "class_type": "WanTrackToVideo",
                "inputs": {
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "vae": ["2", 0],
                    "tracks": self._stroke_tracks(stroke_params),
                    "width": width,
                    "height": height,
                    "length": params["frame_count"],
                    "batch_size": params["batch_size"],
                    "temperature": 220.0,
                    "topk": 2,
                    "start_image": ["8", 0],
                    "clip_vision_output": ["9", 0],
                },
            },
            "18": {
                "class_type": "KSamplerAdvanced",
                "inputs": {
                    "model": ["5", 0],
                    "positive": ["11", 0],
                    "negative": ["11", 1],
                    "latent_image": ["11", 2],
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
            "12": {
                "class_type": "KSamplerAdvanced",
                "inputs": {
                    "model": ["17", 0],
                    "positive": ["11", 0],
                    "negative": ["11", 1],
                    "latent_image": ["18", 0],
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
                "inputs": {"samples": ["12", 0], "vae": ["2", 0]},
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
