"""Canonical grouping of workflow params into labeled form sections.

Every workflow must present the same kinds of params in the same sections, in the
same order, regardless of which workflow's ``param_definitions()`` produced them.
So the grouping lives here, once, keyed by param name — not on each workflow,
which would let the orderings drift apart. :class:`~origenerator.gui.param_form.
ParamForm` lays its editable fields out by this order and drops each read-only
passthrough row into the matching section too.

Kept Qt-free so the grouping is unit-testable without a QApplication.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Section:
    """One labeled, collapsible group of params.

    ``keys`` is the canonical intra-section order; ``collapsed`` is whether the
    section starts folded shut (the default a fresh form opens with).
    """

    title: str
    keys: tuple[str, ...]
    collapsed: bool


# The sections, in the order they stack down the form. Prompts and Seed lead and
# start open — the fields touched every run; the rest start collapsed so a fresh
# form is compact, one click from any group. A param's section is fixed here, so
# switching workflows never reshuffles where a given kind of setting appears.
SECTIONS: tuple[Section, ...] = (
    Section("Prompts", ("positive_prompt", "negative_prompt", "input_image"),
            collapsed=False),
    Section("Seed", ("noise_seed", "seed"), collapsed=False),
    Section("Model & LoRA", (
        "checkpoint", "unet", "unet_high", "unet_low",
        "control_mode", "controlnet", "controlnet_strength", "controlnet_end",
        "lora", "lora_strength",
        "lora_high", "lora_strength_high", "lora_low", "lora_strength_low",
        "clip_name", "clip_name1", "clip_name2", "clip_vision_name",
        "vae", "vae_name", "upscale_model",
        "depth_model", "pose_bbox_detector", "pose_estimator",
    ), collapsed=True),
    Section("Sampling", (
        "steps", "cfg", "guidance", "sampler_name", "scheduler",
        "shift", "shift_high", "shift_low", "denoise",
    ), collapsed=True),
    Section("Enhance", (
        "enhance_scale", "enhance_steps", "enhance_denoise",
    ), collapsed=True),
    Section("Stroke", (
        "stroke_hz", "stroke_x", "stroke_top", "stroke_bottom",
        "anchor_x", "anchor_y",
    ), collapsed=True),
    Section("Dimensions", ("width", "height", "length"), collapsed=True),
    Section("Frames", ("frame_count", "frame_rate"), collapsed=True),
    Section("Audio", (
        "audio_prompt", "audio_negative_prompt", "audio_seed",
        "foley_model", "foley_vae", "foley_synchformer",
    ), collapsed=True),
    Section("Output", ("batch_size", "crf", "filename_prefix"), collapsed=True),
)

# Where an unmapped param lands: a trailing catch-all so a newly added key still
# renders (and round-trips) instead of vanishing. A guard test keeps every
# registered workflow's params out of here; it exists only for forward safety.
OTHER_TITLE = "Other"
OTHER_COLLAPSED = True

_SECTION_INDEX = {key: i for i, s in enumerate(SECTIONS) for key in s.keys}
_WITHIN_INDEX = {key: j for s in SECTIONS for j, key in enumerate(s.keys)}


def section_title(key: str) -> str:
    """The section a param belongs in, or :data:`OTHER_TITLE` if unmapped."""
    i = _SECTION_INDEX.get(key)
    return SECTIONS[i].title if i is not None else OTHER_TITLE


def key_rank(key: str) -> tuple[int, int]:
    """``(section, position)`` — the total order a key sorts to across the form.

    Sorting a workflow's keys by this lays them out in canonical section order,
    each section's fields in canonical order. Unmapped keys tie at the very end,
    so a stable sort keeps them in their given order after every mapped key.
    """
    if key in _SECTION_INDEX:
        return (_SECTION_INDEX[key], _WITHIN_INDEX[key])
    return (len(SECTIONS), 0)
