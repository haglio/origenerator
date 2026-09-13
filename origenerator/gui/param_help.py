"""One line of help per workflow parameter, keyed by param name.

Every field in the Generate form carries a tooltip, and it comes from here
rather than from each workflow's own ``param_definitions``: the same key means
the same thing in every workflow that has it — ``steps`` is steps whether an
SDXL still or a WAN video is selected — so writing the explanation once is what
keeps the twelve descriptions of ``cfg`` from drifting into twelve different
claims. The grouping lives in :mod:`origenerator.gui.param_sections` for exactly
the same reason.

Written for someone who knows what they want the picture to do and not what a
sampler is: each line says what moving the number does to the result, and where
a value has a practical range or a known trap, it says that too. Kept Qt-free so
the text is unit-testable, and a guard test keeps every registered workflow's
params covered — a new param must be explained before it can ship.
"""
from __future__ import annotations

# Keyed by param name; the value is the whole tooltip. Second person, no
# trailing period on a single clause, one sentence or two at most — a tooltip
# that runs long is one nobody finishes reading.
PARAM_HELP: dict[str, str] = {
    # --- prompts and the picture a run starts from ---
    "positive_prompt": (
        "What you want to see. Comma-separated phrases work best; the earlier a "
        "phrase appears, the more weight it tends to carry. A video can tell a "
        "story: add a scene and each runs for its own length, starting on the "
        "last frame of the one before."
    ),
    "scene_frames": (
        "How long each scene of the story runs, at the rate the model paces "
        "motion. Every scene after the first starts on the last frame of the one "
        "before it, so the clip is the scenes end to end."
    ),
    "scene_lines": (
        "What she says in this scene, spoken in the voice set under Sound. A "
        "scene with lines renders on the speaking model, and her speaking is all "
        "that happens in it — its prompts go unused, so a scene is one or the "
        "other. Words past the scene's end are cut; a scene left blank renders "
        "as it always has, prompts and soundtrack and all."
    ),
    "voice": (
        "Whose voice speaks the lines: one of the speech model's preset speakers, "
        "the same voice every run, or Custom voice, a recording of your own named "
        "in the Voice Sample field that appears."
    ),
    "voice_sample": (
        "A recording, five to fifteen seconds of one clean voice, for the lines to "
        "be spoken in a copy of that voice. Browse to the file."
    ),
    "voice_sample_text": (
        "The words the Voice Sample says, exactly. With them the copy carries the "
        "recording's manner as well as its timbre; without them only the timbre."
    ),
    "unet_s2v": (
        "The model a scene with lines renders on, in place of the two pass "
        "models; it hears her lines and moves her lips to them."
    ),
    "negative_prompt": (
        "What you want kept out — artifacts, styles, body parts you keep getting "
        "by accident. Leaving it empty is fine. In a story each scene keeps out "
        "its own, and a new scene starts with the one before it."
    ),
    "input_image": (
        "The picture this run is built from: the start frame for a video, or the "
        "structure to re-skin. Browse to any file, or drop a generation on it."
    ),

    # --- seeds ---
    "seed": (
        "The starting noise. The same seed with the same settings reproduces the "
        "same image exactly; Random draws a fresh one on every Generate."
    ),
    "noise_seed": (
        "The starting noise for the first pass, which settles the composition. "
        "Random draws a fresh one on every Generate."
    ),
    "audio_seed": (
        "The starting noise for the generated sound, separate from the picture's "
        "seed — re-roll it to get a different take of the same scene's sound."
    ),

    # --- models ---
    "checkpoint": (
        "The model that does the generating. It sets the look more than any other "
        "setting here — style, anatomy, what the prompt words mean to it."
    ),
    "unet": "The model file this run generates with.",
    "unet_high": (
        "The model for the first pass (the high-noise expert), which settles "
        "composition and motion before the second pass refines it."
    ),
    "unet_low": (
        "The model for the second pass (the low-noise expert), which refines "
        "detail on what the first pass laid down."
    ),
    "upscale_model": (
        "The enlarger the enhancement runs first (an ESRGAN-family model), which "
        "rebuilds edges rather than stretching them."
    ),

    # --- add-ons ---
    "lora_high": (
        "An add-on (a LoRA) trained for a specific look or subject, applied to "
        "the first pass. \"None\" leaves the model unmodified."
    ),
    "lora_low": (
        "An add-on (a LoRA) trained for a specific look or subject, applied to "
        "the second pass. \"None\" leaves the model unmodified."
    ),
    "lora_strength_high": (
        "How hard the first pass's add-on pulls. 1.0 is its intended strength; "
        "below 0.5 it barely shows, above 1.2 it tends to take over the picture."
    ),
    "lora_strength_low": (
        "How hard the second pass's add-on pulls. 1.0 is its intended strength; "
        "below 0.5 it barely shows, above 1.2 it tends to take over the picture."
    ),

    # --- drawing ---
    "steps": (
        "How many times the model goes over the picture, refining it. More steps "
        "means more settled detail and a longer wait, with little gain once the "
        "picture has stopped changing."
    ),
    "cfg": (
        "How strictly the model obeys the prompt (the CFG scale underneath). Too "
        "low drifts off it; too high burns contrast and flattens detail."
    ),
    "cfg_high": (
        "Prompt strength for the first pass (the CFG scale underneath), where the "
        "motion is settled. An add-on's author often publishes a different number "
        "for each pass; where they publish one, put it in both."
    ),
    "cfg_low": (
        "Prompt strength for the second pass (the CFG scale underneath), where "
        "the texture is settled."
    ),
    "split_step": (
        "The step where the first pass hands over to the second (the split step). "
        "Earlier leaves more of the work to the second pass; 0 hands over at half "
        "the steps."
    ),
    "guidance": (
        "How strictly the model obeys the prompt (Flux's guidance value). It wants "
        "much smaller numbers than prompt strength does elsewhere — this model's "
        "usable range sits low."
    ),
    "sampler_name": (
        "The method that walks the noise down to a picture. They differ in look "
        "and in how many steps they need to settle."
    ),
    "scheduler": (
        "How the noise level is spaced across the steps. It changes where the "
        "detail lands more than whether the image is good."
    ),
    "denoise": (
        "How much of the starting image is redrawn (the denoise strength). 1.0 "
        "generates from pure noise; lower keeps more of what was there and only "
        "re-imagines the rest."
    ),
    "shift": (
        "Where this model spends its effort — higher favors composition, lower "
        "favors fine detail."
    ),
    "shift_high": "Where the first pass spends its effort: higher favors composition.",
    "shift_low": "Where the second pass spends its effort: lower favors fine detail.",

    # --- the enhance tail (off the form; the Enhance subpanel owns these) ---
    "enhance_scale": (
        "How much bigger the enhanced version is than the render it came from. "
        "2x is the usual finish; past 3x the pass has to invent a lot."
    ),
    "enhance_steps": (
        "How many times the enhancement goes over the enlarged picture. Around 20 "
        "is enough to build texture without redrawing anything."
    ),
    "enhance_denoise": (
        "How far the enhance may stray from the picture it is refining (its "
        "denoise). 0.15 adds skin and fabric texture; by 0.3 it starts re-imagining "
        "anatomy, which is where creases turn into wounds."
    ),
    "enhance_detail_fixes": (
        "Which parts the enhance goes back over and redraws on their own, and "
        "how hard it redraws each. This is what mends a mouth melted into its "
        "teeth or a finger too many, and it can afford to be bold where the "
        "whole-picture pass cannot, since nothing outside the regions found is "
        "touched: around 0.45 actually re-forms a bad hand, while below 0.3 it "
        "only tidies the one it was given."
    ),

    # --- structure transfer ---
    "control_mode": (
        "Which structure is lifted out of the structure image and held onto: its "
        "depth, or the skeleton of the people in it."
    ),
    "controlnet": "The model that holds the picture to the structure image (a ControlNet).",
    "controlnet_strength": (
        "How firmly the output is held to the structure image. Lower lets the "
        "prompt reshape things; higher traces the source closely."
    ),
    "controlnet_end": (
        "How far into the drawing the structure keeps being held. Letting go "
        "early lets the last steps add detail the structure has no opinion on."
    ),

    # --- size and length ---
    "width": "The output width in pixels.",
    "height": "The output height in pixels.",
    "frame_count": (
        "How long the clip runs, in seconds — of real motion, at any frame rate. "
        "Pick a length or type one; it is rounded to the frames the model works "
        "in, and stops where the model stops."
    ),
    "frame_rate": (
        "How smooth the motion looks. The model always paces the action at 16 "
        "frames a second; a higher rate fills in the frames between those, so "
        "the clip runs the same length at the same speed, just less steppy. "
        "Rates are multiples of 16 because the frames are filled in a whole "
        "number at a time; anything else settles onto the nearest."
    ),

    # --- the authored motion (track-conditioned video) ---
    "motion_hz": "How many cycles per second the generated motion runs at.",
    "motion_x": "The horizontal line the motion travels along, in pixels across the frame.",
    "motion_ceiling": "The pixel row the motion reaches at the high end of its travel.",
    "motion_floor": "The pixel row the motion reaches at the low end of its travel.",
    "anchor_x": "The horizontal position of the point that stays put while the motion moves.",
    "anchor_y": "The vertical position of the point that stays put while the motion moves.",

    # --- sound ---
    "audio_prompt": (
        "What the generated soundtrack should be — the sounds themselves, not the "
        "picture. It watches the finished motion while it scores."
    ),
    "audio_negative_prompt": "Sounds to keep out of the generated soundtrack.",
}


def param_help(key: str) -> str:
    """The tooltip for one param, or ``""`` when it has none.

    Empty rather than a placeholder: Qt shows no tooltip for an empty string,
    and an explanation that says nothing is worse than no explanation at all.
    """
    return PARAM_HELP.get(key, "")
