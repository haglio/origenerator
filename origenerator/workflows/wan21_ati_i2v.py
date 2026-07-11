import json
import math

from origenerator.workflows.base import ParamDef, WorkflowTemplate
from origenerator.workflows.model_files import NO_LORA, list_lora_files, list_model_files

# ATI's track convention is fixed regardless of the clip: 121 points sampled at
# 24fps (5.0s of "track time"), which ComfyUI's WanTrackToVideo resamples onto
# the actual frame count — so a clip's effective cadence is the authored one
# scaled by (5.0 / clip seconds). Both the tracks and the funscript below use
# the same mapping, which is what keeps them locked to each other.
TRACK_POINTS = 121
TRACK_SECONDS = 5.0
# The three cluster points ride the stroke slightly staggered (as derisked in
# the PoC): enough spread to read as a hand, not so much it smears the patch.
_CLUSTER_OFFSETS = ((-5.0, -30.0), (3.0, 0.0), (-3.0, 30.0))


class Wan21AtiI2vWorkflow(WorkflowTemplate):
    """WAN 2.1 ATI image-to-video: the video follows an authored stroke track.

    Motion authorship is flipped relative to the other video workflows: a
    stroke is authored first (``stroke_*`` params), ``WanTrackToVideo``
    conditions the ATI-finetuned WAN 2.1 checkpoint on it, and the video obeys.
    The same track then becomes the funscript (:meth:`authored_actions`) — one
    source, exact by construction, no pixel measurement. The decoded frames
    still get the HunyuanVideo-Foley scoring pass, muxed by ``CreateVideo``.

    Unlike the WAN 2.2 workflows the output size is explicit (``width`` /
    ``height``): the track's pixel coordinates and the conditioning must agree
    on one space, so deriving the size in-graph would leave the track blind.
    Frame count stops at 113 because ComfyUI's track resampler faults at
    exactly 121 frames (its length-1=120 off-by-one).
    """

    name = "wan21_ati_i2v"
    version = "v002"
    display_name = "WAN 2.1 ATI (Stroke-Tracked I2V)"
    output_type = "video"
    model_keys = ("unet",)
    lora_keys = ("lora",)
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
            "width": 480,
            "height": 864,
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
            "lora": NO_LORA,
            "lora_strength": 1.0,
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
            ParamDef("stroke_x", "Stroke X", "int", 255, min_val=0, max_val=4096),
            ParamDef("stroke_top", "Stroke Top Y", "int", 490, min_val=0, max_val=4096),
            ParamDef("stroke_bottom", "Stroke Bottom Y", "int", 650, min_val=0, max_val=4096),
            ParamDef("anchor_x", "Anchor X", "int", 233, min_val=0, max_val=4096),
            ParamDef("anchor_y", "Anchor Y", "int", 760, min_val=0, max_val=4096),
            ParamDef("frame_count", "Frames", "int", 81, min_val=5, max_val=113, step=4),
            ParamDef("steps", "Steps", "int", 20, min_val=1, max_val=50),
            ParamDef("cfg", "CFG Scale", "float", 5.0, min_val=0.0, max_val=30.0, step=0.1),
            ParamDef("shift", "Shift", "float", 8.0, min_val=0.0, max_val=20.0, step=0.5),
            ParamDef("unet", "Model", "combo", defaults["unet"], options=models),
            ParamDef("lora", "LoRA", "combo", defaults["lora"], options=list_lora_files([])),
            ParamDef("lora_strength", "LoRA Strength", "float", 1.0, min_val=0.0, max_val=2.0, step=0.05),
            ParamDef("width", "Width", "int", 480, min_val=64, max_val=2048, step=16),
            ParamDef("height", "Height", "int", 864, min_val=64, max_val=2048, step=16),
            ParamDef("frame_rate", "Frame Rate", "float", 16.0, min_val=1.0, max_val=60.0, step=1.0),
            ParamDef("filename_prefix", "Output Prefix", "str", "video/wan21_ati_i2v"),
        ]

    @staticmethod
    def _stroke_phase(params: dict, t_track: float) -> float:
        """The authored sine at track-time ``t_track``, in [-1, 1]; -1 is the
        stroke top (where the cluster starts), +1 the bottom."""
        return math.sin(2 * math.pi * params["stroke_hz"] * t_track - math.pi / 2)

    def _stroke_tracks(self, params: dict) -> str:
        """The tracks JSON: three staggered points riding the authored stroke
        between ``stroke_top`` and ``stroke_bottom``, plus one static point
        pinning the anchor. 121 points at 24fps, ATI's fixed convention."""
        center = (params["stroke_top"] + params["stroke_bottom"]) / 2
        amplitude = (params["stroke_bottom"] - params["stroke_top"]) / 2
        tracks = []
        for x_off, y_off in _CLUSTER_OFFSETS:
            spread = min(abs(y_off), amplitude * 0.4) * (1 if y_off >= 0 else -1)
            pts = []
            for f in range(TRACK_POINTS):
                y = center + spread + amplitude * self._stroke_phase(params, f / 24.0)
                pts.append({"x": float(params["stroke_x"] + x_off), "y": float(y)})
            tracks.append(pts)
        tracks.append(
            [{"x": float(params["anchor_x"]), "y": float(params["anchor_y"])}] * TRACK_POINTS
        )
        return json.dumps(tracks)

    def authored_actions(self, params: dict) -> list[dict]:
        """The funscript for the authored stroke: alternating top/bottom
        extremes at the authored cadence, mapped from track time onto the
        clip's real duration — the same mapping WanTrackToVideo applies to the
        track, so script and pixels stay locked."""
        video_s = params["frame_count"] / params["frame_rate"]
        scale = video_s / TRACK_SECONDS
        half_period_ms = 500.0 / params["stroke_hz"] * scale
        actions = []
        i = 0
        while (ms := round(i * half_period_ms)) <= video_s * 1000:
            actions.append({"at": int(ms), "pos": 100 if i % 2 == 0 else 0})
            i += 1
        return actions

    def build_api_payload(self, params: dict) -> dict:
        foley, audio_ref = self.foley_audio_nodes("20", "21", "22", ["13", 0], params)
        # Optional 2.1-compatible LoRA: "None" omits the loader and the base
        # ATI model runs unmodified (WorkflowTemplate.lora_model_input).
        lora, model_ref = self.lora_model_input(
            "10", ["4", 0], params["lora"], params["lora_strength"]
        )
        return {
            **foley,
            **lora,
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
                "inputs": {"model": model_ref, "shift": params["shift"]},
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
                    "tracks": self._stroke_tracks(params),
                    "width": params["width"],
                    "height": params["height"],
                    "length": params["frame_count"],
                    "batch_size": params["batch_size"],
                    "temperature": 220.0,
                    "topk": 2,
                    "start_image": ["8", 0],
                    "clip_vision_output": ["9", 0],
                },
            },
            "12": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["5", 0],
                    "positive": ["11", 0],
                    "negative": ["11", 1],
                    "latent_image": ["11", 2],
                    "seed": params["seed"],
                    "steps": params["steps"],
                    "cfg": params["cfg"],
                    "sampler_name": params["sampler_name"],
                    "scheduler": params["scheduler"],
                    "denoise": 1.0,
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
