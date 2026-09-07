from __future__ import annotations

from pathlib import Path

from origenerator.speech import VOICE_OPTIONS, VOICE_PRESETS, scene_speech
from origenerator.workflows.base import (
    DURATION_OPTIONS,
    FRAME_RATE_OPTIONS,
    LONGEST_CLIP_FRAMES,
    ParamDef,
    WorkflowTemplate,
    scene_prompts,
)
from origenerator.workflows.frame_rate import (
    MAX_PLAYBACK_FPS,
    NATIVE_FPS,
    playback_rate,
)
from origenerator.workflows.model_arch import WAN_S2V
from origenerator.workflows.model_files import list_model_files
from origenerator.workflows.wan_experts import (
    wan_expert_lora_params,
    wan_expert_model_params,
)

# A scene with a line renders on WAN 2.2's speech-to-video model: one model in
# place of the two experts, reading the line as audio and moving her lips to
# it, under the lightning LoRA Comfy's own S2V template runs it with -- four
# steps at no guidance, which is what the probe he judged by eye ran
# (2026-09-06). His LoRAs stay off it: the one tried put artifacts all over
# the picture.
_SPEECH_LORA = "wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors"
_SPEECH_STEPS = 4
_SPEECH_CFG = 1.0
_SPEECH_SAMPLER = "uni_pc"
_SPEECH_SCHEDULER = "simple"
_SPEECH_SHIFT = 8.0


class Wan22I2vWorkflow(WorkflowTemplate):
    """WAN 2.2 14B image-to-video, dual-noise (high/low) sampling.

    Reproduces the ``wan22_14b_i2v_dual_noise_template`` ComfyUI graph: a single
    input image is encoded with CLIP-Vision and fed to ``WanImageToVideo``, then
    denoised by two ``KSamplerAdvanced`` passes (high-noise model first, low-noise
    model after), interpolated up to the chosen playback rate
    (:meth:`~WorkflowTemplate.interpolation_nodes`) and written with the native
    ``CreateVideo`` + ``SaveVideo`` nodes. The stages hand off at ``split_step``
    (0 = half the steps), and each runs at its own ``cfg_high``/``cfg_low`` —
    LoRA authors tune these per stage (motion lives in the high pass, texture in
    the low), so a recipe can follow their numbers exactly. The output resolution is
    derived in-graph from the input image (see :meth:`build_api_payload`): it
    keeps the image's aspect ratio at a fixed pixel budget rather than a
    hardcoded size. The decoded frames also drive a HunyuanVideo-Foley pass
    (:meth:`~WorkflowTemplate.foley_audio_nodes`), whose synced audio
    ``CreateVideo`` muxes into the file.

    A story's scene with a line (``scene_lines``) is spoken instead: that
    scene's segments render on WAN 2.2's speech-to-video model, hearing the
    line as audio (made beforehand, see :mod:`origenerator.speech`) and moving
    her lips to it, and in the file that scene carries her line in place of
    the foley.
    """

    name = "wan22_i2v"
    version = "v007"
    display_name = "WAN 2.2 I2V (Image-to-Video)"
    output_type = "video"
    derives_size_from_input = True
    model_keys = ("unet_high", "unet_low")
    lora_keys = ("lora_high", "lora_low")
    output_node_id = "19"

    def default_params(self) -> dict:
        return {
            "positive_prompt": "",
            "negative_prompt": "",
            "input_image": "",
            "noise_seed": 0,
            "seed": 0,
            "frame_count": 81,
            "scene_frames": [81],
            "scene_lines": [""],
            "batch_size": 1,
            "steps": 20,
            "split_step": 0,
            "cfg_high": 3.5,
            "cfg_low": 3.5,
            "sampler_name": "euler",
            "scheduler": "simple",
            "shift_high": 8.0,
            "shift_low": 8.0,
            "lora_strength_high": 1.0,
            "lora_strength_low": 1.0,
            "frame_rate": NATIVE_FPS,
            "filename_prefix": "video/wan22_i2v",
            "clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
            "vae_name": "wan_2.1_vae.safetensors",
            "clip_vision_name": "clip_vision_h.safetensors",
            "unet_high": "split_files\\diffusion_models\\wan2.2_i2v_high_noise_14B_fp16.safetensors",
            "unet_low": "split_files\\diffusion_models\\wan2.2_i2v_low_noise_14B_fp16.safetensors",
            "lora_high": "wan22-f4c3spl4sh-100epoc-high-k3nk.safetensors",
            "lora_low": "wan22-f4c3spl4sh-154epoc-low-k3nk.safetensors",
            "audio_prompt": "",
            "audio_negative_prompt": "noisy, harsh",
            "audio_seed": 0,
            "voice": VOICE_PRESETS[0],
            "voice_sample": "",
            "voice_sample_text": "",
            "foley_model": "hunyuanvideo_foley_fp8_e4m3fn.safetensors",
            "foley_vae": "vae_128d_48k_fp16.safetensors",
            "foley_synchformer": "synchformer_state_dict_fp16.safetensors",
            "unet_s2v": "wan2.2_s2v_14B_fp8_scaled.safetensors",
            "audio_encoder_name": "wav2vec2_large_english_fp16.safetensors",
        }

    def param_definitions(self) -> list[ParamDef]:
        defaults = self.default_params()
        # The speech slot takes only the speech model: an expert in it would
        # render deaf, and the expert slots never offer it.
        speech = list_model_files("diffusion_models", [defaults["unet_s2v"]], accepts=(WAN_S2V,))
        return [
            ParamDef("positive_prompt", "Positive Prompt", "str", defaults["positive_prompt"], multiline=True),
            ParamDef("scene_frames", "Scenes", "scenes", defaults["scene_frames"], min_val=5,
                     max_val=LONGEST_CLIP_FRAMES, step=4, options=DURATION_OPTIONS,
                     unit="s", rate=NATIVE_FPS),
            ParamDef("scene_lines", "Lines", "lines", defaults["scene_lines"]),
            ParamDef("negative_prompt", "Negative Prompt", "str", defaults["negative_prompt"], multiline=True),
            ParamDef("input_image", "Start Image", "image", defaults["input_image"]),
            ParamDef("audio_prompt", "Audio Prompt", "str", defaults["audio_prompt"], multiline=True),
            ParamDef("audio_negative_prompt", "Audio Negative Prompt", "str", defaults["audio_negative_prompt"], multiline=True),
            ParamDef("voice", "Voice", "combo", defaults["voice"], options=list(VOICE_OPTIONS)),
            ParamDef("voice_sample", "Voice Sample", "audio", defaults["voice_sample"], browse_dir=Path.home()),
            ParamDef("voice_sample_text", "Voice Sample Says", "str", defaults["voice_sample_text"], multiline=True),
            ParamDef("noise_seed", "Seed (High)", "seed", defaults["noise_seed"]),
            ParamDef("seed", "Seed (Low)", "seed", defaults["seed"]),
            ParamDef("audio_seed", "Audio Seed", "seed", defaults["audio_seed"]),
            ParamDef("frame_count", "Duration", "int", defaults["frame_count"], min_val=5, max_val=LONGEST_CLIP_FRAMES, step=4,
                     options=DURATION_OPTIONS, unit="s", rate=NATIVE_FPS),
            ParamDef("steps", "Steps", "int", defaults["steps"], min_val=1, max_val=100),
            ParamDef("split_step", "Handoff Step (0 = half)", "int", defaults["split_step"], min_val=0, max_val=100),
            ParamDef("cfg_high", "Prompt Strength (High)", "float", defaults["cfg_high"], min_val=0.0, max_val=30.0, step=0.1),
            ParamDef("cfg_low", "Prompt Strength (Low)", "float", defaults["cfg_low"], min_val=0.0, max_val=30.0, step=0.1),
            ParamDef("shift_high", "Shift (High)", "float", defaults["shift_high"], min_val=0.0, max_val=20.0, step=0.5),
            ParamDef("shift_low", "Shift (Low)", "float", defaults["shift_low"], min_val=0.0, max_val=20.0, step=0.5),
            *wan_expert_model_params(defaults),
            ParamDef("unet_s2v", "Model (Speech)", "combo", defaults["unet_s2v"], options=speech),
            *wan_expert_lora_params(defaults),
            ParamDef("frame_rate", "Frame Rate", "float", defaults["frame_rate"],
                     min_val=NATIVE_FPS, max_val=MAX_PLAYBACK_FPS, step=NATIVE_FPS,
                     options=FRAME_RATE_OPTIONS, unit="fps"),
        ]

    @staticmethod
    def _stage_strengths(params: dict) -> tuple[float, float]:
        """Each sampler's prompt strength. A recipe stored before the stages had
        their own carries one ``cfg`` and a zero for each stage; that zero meant
        "use the shared one", so it still does — reading it as no guidance at all
        would re-run every such generation as a different video."""
        shared = params.get("cfg")
        if shared is None:
            return params["cfg_high"], params["cfg_low"]
        return params["cfg_high"] or shared, params["cfg_low"] or shared

    @staticmethod
    def _speech_nodes(params: dict, spoken) -> dict:
        """What every speaking segment shares: the speech model under its
        lightning LoRA, the audio encoder that hears the lines, and each spoken
        scene's line loaded once (``scene<k>_line``)."""
        nodes = {
            "30": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": params["unet_s2v"], "weight_dtype": "default"},
            },
            "31": {
                "class_type": "LoraLoaderModelOnly",
                "inputs": {"model": ["30", 0], "lora_name": _SPEECH_LORA, "strength_model": 1.0},
            },
            "32": {
                "class_type": "ModelSamplingSD3",
                "inputs": {"model": ["31", 0], "shift": _SPEECH_SHIFT},
            },
            "33": {
                "class_type": "AudioEncoderLoader",
                "inputs": {"audio_encoder_name": params["audio_encoder_name"]},
            },
        }
        for index, line in enumerate(spoken):
            if line is not None:
                nodes[f"scene{index}_line"] = {"class_type": "LoadAudio", "inputs": {"audio": line.file}}
        return nodes

    def _speaking_segment(self, index, scene, start, previous, length, offset,
                          positive_ref, negative_ref, size, params):
        """One segment of a scene with a line, on the speech model: it hears
        its stretch of the scene's line, starts on ``start`` as its reference
        and, past the first segment, carries the motion of the frames before
        it (the model's ``ref_motion``, which reads the last of them)."""
        prefix = f"s{index}_"
        width_ref, height_ref = size
        heard, heard_ref = self.speech_window_nodes(
            prefix, [f"scene{scene}_line", 0], ["33", 0], offset, length)
        conditioning = {
            "positive": positive_ref,
            "negative": negative_ref,
            "vae": ["2", 0],
            "width": width_ref,
            "height": height_ref,
            "length": length,
            "batch_size": params["batch_size"],
            "audio_encoder_output": heard_ref,
            "ref_image": start,
        }
        if previous is not None:
            conditioning["ref_motion"] = previous
        nodes = {
            **heard,
            prefix + "s2v": {"class_type": "WanSoundImageToVideo", "inputs": conditioning},
            prefix + "speak": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["32", 0],
                    "positive": [prefix + "s2v", 0],
                    "negative": [prefix + "s2v", 1],
                    "latent_image": [prefix + "s2v", 2],
                    "seed": params["noise_seed"] + index,
                    "steps": _SPEECH_STEPS,
                    "cfg": _SPEECH_CFG,
                    "sampler_name": _SPEECH_SAMPLER,
                    "scheduler": _SPEECH_SCHEDULER,
                    "denoise": 1.0,
                },
            },
            prefix + "decode": {
                "class_type": "VAEDecode",
                "inputs": {"samples": [prefix + "speak", 0], "vae": ["2", 0]},
            },
        }
        return nodes, [prefix + "decode", 0]

    def build_api_payload(self, params: dict) -> dict:
        split_step = params["split_step"] or params["steps"] // 2
        cfg_high, cfg_low = self._stage_strengths(params)
        # Each LoRA is optional: "None" adds no LoraLoader for that stage, so its
        # sampler runs the base UNET unmodified (WorkflowTemplate.lora_model_input).
        lora_high, model_high = self.lora_model_input(
            "6", ["4", 0], params["lora_high"], params["lora_strength_high"]
        )
        lora_low, model_low = self.lora_model_input(
            "7", ["5", 0], params["lora_low"], params["lora_strength_low"]
        )
        # Size the video off the input image: derived in-graph by default, or
        # scaled to the user's explicit WxH when the derived size was unlocked.
        sized = self.image_size_nodes(["12", 0], params)
        size_nodes, start_ref = sized.nodes, sized.image
        width_ref, height_ref = sized.width, sized.height

        # Each segment reads its own scene of the prompt and of the negative (a
        # --- line starts the next of each, which is how the scenes editor stores
        # them); nodes 10 and 11 below encode the first scene's, and any later
        # scene gets its own.
        scenes = scene_prompts(params["positive_prompt"])
        negatives = scene_prompts(params["negative_prompt"])
        # A scene with a line is spoken: its segments render on the speech
        # model, each hearing its own stretch of the scene's line (the offset
        # a later segment of the same scene starts at, kept here as the plan
        # is walked in order).
        spoken = scene_speech(params)
        offsets: dict[int, int] = {}

        def segment(index, scene, start, length, last, previous=None):
            prompt_nodes, positive_ref = self.scene_prompt_nodes(index, scene, scenes, ["1", 0], ["10", 0])
            negative_nodes, negative_ref = self.scene_prompt_nodes(
                index, scene, negatives, ["1", 0], ["11", 0], role="negative")
            if spoken[scene] is not None:
                offset = offsets.get(scene, 0)
                offsets[scene] = offset + length - 1
                nodes, frames = self._speaking_segment(
                    index, scene, start, previous, length, offset,
                    positive_ref, negative_ref, (width_ref, height_ref), params)
                return {**prompt_nodes, **negative_nodes, **nodes}, frames
            clip_id, i2v_id, high_id, low_id, decode_id = (
                ("13", "14", "15", "16", "17") if index == 0
                else tuple(f"s{index}_{name}" for name in ("clip", "i2v", "high", "low", "decode"))
            )
            nodes = {
                **prompt_nodes,
                **negative_nodes,
                clip_id: {
                    "class_type": "CLIPVisionEncode",
                    "inputs": {
                        "clip_vision": ["3", 0],
                        "image": start,
                        "crop": "center",
                    },
                },
                i2v_id: {
                    "class_type": "WanImageToVideo",
                    "inputs": {
                        "positive": positive_ref,
                        "negative": negative_ref,
                        "vae": ["2", 0],
                        "clip_vision_output": [clip_id, 0],
                        "start_image": start,
                        "width": width_ref,
                        "height": height_ref,
                        "length": length,
                        "batch_size": params["batch_size"],
                    },
                },
                high_id: {
                    "class_type": "KSamplerAdvanced",
                    "inputs": {
                        "model": ["8", 0],
                        "positive": [i2v_id, 0],
                        "negative": [i2v_id, 1],
                        "latent_image": [i2v_id, 2],
                        "add_noise": "enable",
                        "noise_seed": params["noise_seed"] + index,
                        "steps": params["steps"],
                        "cfg": cfg_high,
                        "sampler_name": params["sampler_name"],
                        "scheduler": params["scheduler"],
                        "start_at_step": 0,
                        "end_at_step": split_step,
                        "return_with_leftover_noise": "enable",
                    },
                },
                low_id: {
                    "class_type": "KSamplerAdvanced",
                    "inputs": {
                        "model": ["9", 0],
                        "positive": [i2v_id, 0],
                        "negative": [i2v_id, 1],
                        "latent_image": [high_id, 0],
                        "add_noise": "disable",
                        "noise_seed": params["seed"] + index,
                        "steps": params["steps"],
                        "cfg": cfg_low,
                        "sampler_name": params["sampler_name"],
                        "scheduler": params["scheduler"],
                        "start_at_step": split_step,
                        "end_at_step": 10000,
                        "return_with_leftover_noise": "disable",
                    },
                },
                decode_id: {
                    "class_type": "VAEDecode",
                    "inputs": {"samples": [low_id, 0], "vae": ["2", 0]},
                },
            }
            return nodes, [decode_id, 0]

        # A clip longer than one segment is chained from each segment's last
        # frame (WorkflowTemplate.chain_segments); its frames come back joined.
        segments, decoded_ref, total_frames = self.chain_segments(params, start_ref, segment)
        # Scored for the frames the scenes really add up to, which is what the
        # stored clip length says whenever the form wrote it.
        foley, audio_ref = self.foley_audio_nodes(
            "22", "23", "24", decoded_ref, {**params, "frame_count": total_frames})
        # Her lines take the writer's track where she speaks: each spoken
        # scene's file at its place in the clip, the foley's own stretch where
        # a scene says nothing (WorkflowTemplate.speech_track_nodes says why
        # not both at once). A story with no line keeps the graph it always had.
        speech = {}
        if any(scene is not None for scene in spoken):
            speech = self._speech_nodes(params, spoken)
            track, audio_ref = self.speech_track_nodes("speech_", [
                (frames, [f"scene{index}_line", 0] if line is not None else None)
                for index, (frames, line) in enumerate(zip(self.scene_lengths(params), spoken))],
                audio_ref)
            speech.update(track)
        # The decode's frames are the clip's motion; the writer's are that motion
        # shown more often. Foley above watches the former, CreateVideo below
        # encodes the latter, and at the native rate they are the same frames.
        interpolate, frames_ref = self.interpolation_nodes("25", decoded_ref, params)
        return {
            **foley,
            **speech,
            **interpolate,
            **size_nodes,
            **segments,
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
                "inputs": {"unet_name": params["unet_high"], "weight_dtype": "default"},
            },
            "5": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": params["unet_low"], "weight_dtype": "default"},
            },
            **lora_high,
            **lora_low,
            "8": {
                "class_type": "ModelSamplingSD3",
                "inputs": {"model": model_high, "shift": params["shift_high"]},
            },
            "9": {
                "class_type": "ModelSamplingSD3",
                "inputs": {"model": model_low, "shift": params["shift_low"]},
            },
            "10": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["1", 0], "text": scenes[0]},
            },
            "11": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["1", 0], "text": negatives[0]},
            },
            "12": {
                "class_type": "LoadImage",
                "inputs": {"image": params["input_image"]},
            },
            "18": {
                "class_type": "CreateVideo",
                "inputs": {
                    "images": frames_ref,
                    "fps": playback_rate(params["frame_rate"]),
                    "audio": audio_ref,
                },
            },
            "19": {
                "class_type": "SaveVideo",
                "inputs": {
                    "video": ["18", 0],
                    "filename_prefix": params["filename_prefix"],
                    "format": "auto",
                    "codec": "auto",
                },
            },
        }
