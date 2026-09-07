from __future__ import annotations

from origenerator.workflows.base import (
    DURATION_OPTIONS,
    FRAME_RATE_OPTIONS,
    ParamDef,
    WorkflowTemplate,
)
from origenerator.workflows.derived_size import (
    measure_derived_size,
    override_size,
    resolve_input_image_path,
)
from origenerator.workflows.frame_rate import (
    MAX_PLAYBACK_FPS,
    NATIVE_FPS,
    playback_rate,
)
from origenerator.workflows.model_arch import WAN
from origenerator.workflows.model_files import NO_LORA, list_lora_files, list_model_files
from origenerator.workflows.motion_aim import detect_grip_aim
from origenerator.workflows.motion_track import (
    REFERENCE_HEIGHT,
    REFERENCE_WIDTH,
    authored_actions,
    motion_tracks,
    scaled_motion_params,
)


class Wan21AtiI2vWorkflow(WorkflowTemplate):
    """WAN 2.1 ATI image-to-video: the video follows an authored motion track.

    Motion authorship is flipped relative to the other video workflows: a
    motion is authored first (``motion_*`` params), ``WanTrackToVideo``
    conditions the ATI-finetuned WAN 2.1 checkpoint on it, and the video obeys.
    The same track then becomes the funscript (:meth:`authored_actions`) — one
    source, exact by construction, no pixel measurement. The decoded frames
    still get the HunyuanVideo-Foley scoring pass, muxed by ``CreateVideo``, and
    are interpolated up to the chosen playback rate on their way to it
    (:meth:`~WorkflowTemplate.interpolation_nodes`) — the track, the funscript
    and the audio all stay on the clip's real seconds, which the rate no longer
    moves.

    The output size is derived from the input image like the WAN 2.2 workflows,
    but app-side rather than in-graph (see :meth:`build_api_payload`): its
    ``WanTrackToVideo`` needs the integer size *and* a track whose coordinates
    share that space, and an in-graph ``GetImageSize`` couldn't feed the track,
    which is built here. The motion is authored in a fixed 480×864 reference
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
    version = "v007"
    display_name = "WAN 2.1 ATI (Motion-Tracked I2V)"
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
            "frame_rate": NATIVE_FPS,
            "motion_hz": 1.2,
            "motion_x": 255,
            "motion_ceiling": 490,
            "motion_floor": 650,
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
        models = list_model_files("diffusion_models", [defaults["unet"]], accepts=(WAN,))
        loras_high = list_lora_files([], accepts=(WAN,), expert="high")
        loras_low = list_lora_files([], accepts=(WAN,), expert="low")
        return [
            ParamDef("positive_prompt", "Positive Prompt", "str", defaults["positive_prompt"], multiline=True),
            ParamDef("negative_prompt", "Negative Prompt", "str", defaults["negative_prompt"], multiline=True),
            ParamDef("input_image", "Start Image", "image", defaults["input_image"]),
            ParamDef("audio_prompt", "Audio Prompt", "str", defaults["audio_prompt"], multiline=True),
            ParamDef("audio_negative_prompt", "Audio Negative Prompt", "str", defaults["audio_negative_prompt"], multiline=True),
            ParamDef("seed", "Seed", "seed", defaults["seed"]),
            ParamDef("audio_seed", "Audio Seed", "seed", defaults["audio_seed"]),
            ParamDef("motion_hz", "Motion Rate (Hz)", "float", defaults["motion_hz"], min_val=0.2, max_val=4.0, step=0.1),
            # Motion coordinates are authored in the 480×864 reference frame and
            # rescaled into the derived output size at payload build, so their
            # ranges are the reference frame's bounds (width for X, height for Y).
            ParamDef("motion_x", "Motion X", "int", defaults["motion_x"], min_val=0, max_val=REFERENCE_WIDTH),
            ParamDef("motion_ceiling", "Motion Ceiling Y", "int", defaults["motion_ceiling"], min_val=0, max_val=REFERENCE_HEIGHT),
            ParamDef("motion_floor", "Motion Floor Y", "int", defaults["motion_floor"], min_val=0, max_val=REFERENCE_HEIGHT),
            ParamDef("anchor_x", "Anchor X", "int", defaults["anchor_x"], min_val=0, max_val=REFERENCE_WIDTH),
            ParamDef("anchor_y", "Anchor Y", "int", defaults["anchor_y"], min_val=0, max_val=REFERENCE_HEIGHT),
            ParamDef("frame_count", "Duration", "int", defaults["frame_count"], min_val=5, max_val=113, step=4,
                     options=DURATION_OPTIONS, unit="s", rate=NATIVE_FPS),
            ParamDef("steps", "Steps", "int", defaults["steps"], min_val=1, max_val=100),
            ParamDef("cfg", "Prompt Strength", "float", defaults["cfg"], min_val=0.0, max_val=30.0, step=0.1),
            ParamDef("shift", "Shift", "float", defaults["shift"], min_val=0.0, max_val=20.0, step=0.5),
            ParamDef("unet", "Model", "combo", defaults["unet"], options=models),
            ParamDef("lora_high", "LoRA (High)", "combo", defaults["lora_high"], options=loras_high),
            ParamDef("lora_strength_high", "LoRA Strength (High)", "float", defaults["lora_strength_high"], min_val=0.0, max_val=2.0, step=0.05),
            ParamDef("lora_low", "LoRA (Low)", "combo", defaults["lora_low"], options=loras_low),
            ParamDef("lora_strength_low", "LoRA Strength (Low)", "float", defaults["lora_strength_low"], min_val=0.0, max_val=2.0, step=0.05),
            ParamDef("frame_rate", "Frame Rate", "float", defaults["frame_rate"],
                     min_val=NATIVE_FPS, max_val=MAX_PLAYBACK_FPS, step=NATIVE_FPS,
                     options=FRAME_RATE_OPTIONS, unit="fps"),
        ]

    # The aim params auto-detection may fill; leaving ALL of them untouched is
    # what opts a run into detection, and editing ANY is the manual override.
    _AIM_KEYS = ("motion_x", "motion_ceiling", "motion_floor", "anchor_x", "anchor_y")

    def _auto_aim_params(self, params: dict) -> dict:
        """``params`` with the motion aimed at the detected anchor, when the user
        left every aim coordinate at its default and the start frame yields a
        detection — choosing where in the frame a thing is shouldn't be the
        user's job. Any edited coordinate, or no detection, leaves the given
        numbers exactly as they are. Fractions from the detector land in the
        reference frame, where all aim coordinates live."""
        defaults = self.default_params()
        if any(params[k] != defaults[k] for k in self._AIM_KEYS):
            return params
        aim = detect_grip_aim(resolve_input_image_path(params.get("input_image")))
        if aim is None:
            return params
        return {
            **params,
            "motion_x": round(aim["motion_x"] * REFERENCE_WIDTH),
            "anchor_x": round(aim["anchor_x"] * REFERENCE_WIDTH),
            "motion_ceiling": round(aim["motion_ceiling"] * REFERENCE_HEIGHT),
            "motion_floor": round(aim["motion_floor"] * REFERENCE_HEIGHT),
            "anchor_y": round(aim["anchor_y"] * REFERENCE_HEIGHT),
        }

    def _output_size(self, params: dict) -> tuple[int, int]:
        """The size this run renders at: the user's explicit width/height when the
        derived size was unlocked and overridden, else the size derived from the
        input image (:meth:`_derived_size`). The motion track is then rescaled into
        whichever size wins, so it stays in the same relative place either way."""
        return override_size(params) or self._derived_size(params)

    def _derived_size(self, params: dict) -> tuple[int, int]:
        """The output size derived from the input image: measured and scaled to
        the shared pixel budget (:func:`~origenerator.workflows.derived_size.
        measure_derived_size`), or the reference size when the image is missing or
        unreadable — so payload build never crashes on a stale or hand-typed
        filename, it just uses the default. Unlike the WAN 2.2 pair ATI can't defer
        this to the graph: its track's pixel coordinates must be built here."""
        return measure_derived_size(params.get("input_image", "")) or (
            REFERENCE_WIDTH,
            REFERENCE_HEIGHT,
        )

    def authored_actions(self, params: dict) -> list[dict]:
        """This clip's funscript, written from the very reversals its pixel
        track eases between (:func:`~origenerator.workflows.motion_track.
        authored_actions`) -- which is what a workflow declaring an authored
        motion has to answer, where a pixels-only one answers ``None``."""
        return authored_actions(params)

    def build_api_payload(self, params: dict) -> dict:
        # ATI can't derive its size in-graph (its WanTrackToVideo needs the
        # integer size AND a track whose coordinates share that space), so both
        # are built here: the size is the input image's derived size (or the
        # unlocked override) and the authored motion — auto-aimed at the
        # detected anchor unless the user placed it — is rescaled into it.
        params = self._auto_aim_params(params)
        width, height = self._output_size(params)
        motion_params = scaled_motion_params(params, width, height)
        foley, audio_ref = self.foley_audio_nodes("20", "21", "22", ["13", 0], params)
        # Foley scores the decoded frames; CreateVideo encodes the interpolated
        # ones. At the native rate they are the same frames.
        interpolate, frames_ref = self.interpolation_nodes("23", ["13", 0], params)
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
            **interpolate,
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
                    "tracks": motion_tracks(motion_params),
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
                    "images": frames_ref,
                    "fps": playback_rate(params["frame_rate"]),
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
