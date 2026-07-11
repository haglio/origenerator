import json
import math
import random

from origenerator.workflows.base import ParamDef, WorkflowTemplate
from origenerator.workflows.derived_size import measure_derived_size
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

# The reference frame the stored stroke coordinates are authored in. They're
# rescaled from here into the derived output space (see ``_scaled_stroke_params``),
# and this doubles as the fallback size when the input image can't be measured.
REFERENCE_WIDTH = 480
REFERENCE_HEIGHT = 864


class Wan21AtiI2vWorkflow(WorkflowTemplate):
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
    """

    name = "wan21_ati_i2v"
    version = "v004"
    display_name = "WAN 2.1 ATI (Stroke-Tracked I2V)"
    output_type = "video"
    derives_size_from_input = True
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
            ParamDef("lora", "LoRA", "combo", defaults["lora"], options=list_lora_files([])),
            ParamDef("lora_strength", "LoRA Strength", "float", 1.0, min_val=0.0, max_val=2.0, step=0.05),
            ParamDef("frame_rate", "Frame Rate", "float", 16.0, min_val=1.0, max_val=60.0, step=1.0),
            ParamDef("filename_prefix", "Output Prefix", "str", "video/wan21_ati_i2v"),
        ]

    @staticmethod
    def _stroke_series(params: dict) -> list[float]:
        """The authored stroke as its 121 track-time samples (y per sample).

        Alternating half-strokes with cosine easing into every reversal — the
        hand decelerates into each turnaround instead of bouncing off it — and
        a seeded wobble in each half-stroke's pace (±12%) and landing depth
        (up to 10% short), so the rhythm reads human rather than metronomic.
        Seeded by the generation seed: deterministic per run, re-rolled by a
        variation. This one series drives both the pixel track and the
        funscript, which is what keeps them locked."""
        rng = random.Random(params["seed"])
        top = float(params["stroke_top"])
        bottom = float(params["stroke_bottom"])
        depth = bottom - top
        half = 0.5 / params["stroke_hz"]
        reversals = [(0.0, top)]
        t, going_down = 0.0, True
        while t <= TRACK_SECONDS:
            t += half * rng.uniform(0.88, 1.12)
            short = depth * rng.uniform(0.0, 0.10)
            reversals.append((t, bottom - short if going_down else top + short))
            going_down = not going_down
        ys, seg = [], 0
        for f in range(TRACK_POINTS):
            tt = f / 24.0
            while reversals[seg + 1][0] < tt:
                seg += 1
            (t0, y0), (t1, y1) = reversals[seg], reversals[seg + 1]
            eased = (1 - math.cos(math.pi * (tt - t0) / (t1 - t0))) / 2
            ys.append(y0 + (y1 - y0) * eased)
        return ys

    def _derived_size(self, params: dict) -> tuple[int, int]:
        """The output size for this run: the input image measured and scaled to
        the shared pixel budget (:func:`~origenerator.workflows.derived_size.
        measure_derived_size`), or the reference size when the image is missing or
        unreadable — so payload build never crashes on a stale or hand-typed
        filename, it just uses the default. Unlike the WAN 2.2 pair ATI can't defer
        this to the graph: its track's pixel coordinates must be built here."""
        return measure_derived_size(params.get("input_image", "")) or (
            REFERENCE_WIDTH,
            REFERENCE_HEIGHT,
        )

    @staticmethod
    def _scaled_stroke_params(params: dict, width: int, height: int) -> dict:
        """``params`` with the stroke coordinates rescaled from the 480×864
        reference frame into the derived ``width``×``height`` space, so a track
        authored once lands in the same relative place whatever the input image's
        aspect ratio. X coordinates scale by the width ratio, Y by the height
        ratio; everything else (the rate, the seeds, …) passes through."""
        sx = width / REFERENCE_WIDTH
        sy = height / REFERENCE_HEIGHT
        return {
            **params,
            "stroke_x": params["stroke_x"] * sx,
            "anchor_x": params["anchor_x"] * sx,
            "stroke_top": params["stroke_top"] * sy,
            "stroke_bottom": params["stroke_bottom"] * sy,
            "anchor_y": params["anchor_y"] * sy,
        }

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

    def authored_actions(self, params: dict) -> list[dict]:
        """The funscript for the authored stroke: the same 121-sample series
        the track rides, each sample mapped from track time onto the clip's
        real duration (the mapping WanTrackToVideo applies) and normalized to
        stroke depth — 100 at the top of the stroke, 0 at the bottom. Dense
        samples rather than bare extremes, so the device eases into reversals
        exactly as the pixels do."""
        top = float(params["stroke_top"])
        bottom = float(params["stroke_bottom"])
        depth = (bottom - top) or 1.0
        video_s = params["frame_count"] / params["frame_rate"]
        scale = video_s / TRACK_SECONDS
        actions = []
        for f, y in enumerate(self._stroke_series(params)):
            ms = round(f / 24.0 * scale * 1000)
            pos = max(0, min(100, round(100 * (bottom - y) / depth)))
            if actions and actions[-1]["at"] == ms:
                continue
            actions.append({"at": int(ms), "pos": pos})
        return actions

    def build_api_payload(self, params: dict) -> dict:
        # ATI can't derive its size in-graph (its WanTrackToVideo needs the
        # integer size AND a track whose coordinates share that space), so both
        # are built here: the size is measured from the input image and the
        # authored stroke is rescaled into it.
        width, height = self._derived_size(params)
        stroke_params = self._scaled_stroke_params(params, width, height)
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
