from __future__ import annotations

from dataclasses import dataclass

from origenerator.workflows.lora_rows import LORA_KEYS, keys_with_strengths
from origenerator.workflows.wan_experts import FIRST_PASS_LORA_KEYS, SECOND_PASS_LORA_KEYS


@dataclass(frozen=True)
class Section:
    title: str
    keys: tuple[str, ...]
    collapsed: bool


WORKFLOW_TITLE = "Workflow, Models & LoRAs"

SECTIONS: tuple[Section, ...] = (
    Section("Prompts", ("positive_prompt", "scene_frames", "scene_lines",
                        "negative_prompt", "input_image", "video", "video_start"),
            collapsed=False),
    Section("Seed", ("noise_seed", "seed"), collapsed=False),
    Section(WORKFLOW_TITLE, (
        "checkpoint", "unet", *keys_with_strengths(LORA_KEYS), "unet_high", "unet_low", "unet_s2v",
        "control_mode", "controlnet", "controlnet_strength", "controlnet_end",
        *keys_with_strengths(FIRST_PASS_LORA_KEYS),
        *keys_with_strengths(SECOND_PASS_LORA_KEYS),
        "upscale_model", "model", "style",
    ), collapsed=False),
    Section("Calibration", (
        "steps", "split_step", "cfg", "cfg_high", "cfg_low",
        "guidance", "sampler_name", "scheduler",
        "shift", "shift_high", "creativity",
    ), collapsed=True),
    Section("Size", ("width", "height", "resolution", "aspect_ratio", "quality"),
            collapsed=True),
    Section("Video", ("frame_count", "frame_rate"), collapsed=True),
    Section("Sound", (
        "audio_prompt", "audio_negative_prompt", "audio_seed",
        "voice", "voice_sample", "voice_sample_text",
    ), collapsed=True),
)

OTHER_TITLE = "Other"
OTHER_COLLAPSED = True

_SECTION_INDEX = {key: i for i, s in enumerate(SECTIONS) for key in s.keys}
_WITHIN_INDEX = {key: j for s in SECTIONS for j, key in enumerate(s.keys)}


def section_title(key: str) -> str:
    i = _SECTION_INDEX.get(key)
    return SECTIONS[i].title if i is not None else OTHER_TITLE


def key_rank(key: str) -> tuple[int, int]:
    if key in _SECTION_INDEX:
        return (_SECTION_INDEX[key], _WITHIN_INDEX[key])
    return (len(SECTIONS), 0)
