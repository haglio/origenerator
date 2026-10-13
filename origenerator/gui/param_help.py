"""One line of help per workflow parameter, keyed by param name.

Every field in the Generate form carries a tooltip, and it comes from here
rather than from each workflow's own ``param_definitions``: the same key means
the same thing in every workflow that has it — ``steps`` is steps whether an
SDXL still or a WAN video is selected — so writing the explanation once is what
keeps the twelve descriptions of ``cfg`` from drifting into twelve different
claims. The grouping lives in :mod:`origenerator.gui.param_sections` for exactly
the same reason.

Each line says what moving the setting does to the result, and every number
recommends a "Good range:" for it, which the user asked for on every tooltip.
Kept Qt-free so the text is unit-testable, and guard tests keep every registered
workflow's params covered and ranged before a new one can ship.
"""
from __future__ import annotations

_COMPOSITION_FOCUS = (
    "How the steps split between composition (the layout, the poses and, in a "
    "video, the motion) and fine detail. Higher keeps the picture noisy for "
    "longer, so more of the steps decide composition; lower gives more of them to "
    "texture and detail. Good range: 5–12; 8 is the usual start, 5 for a looping "
    "clip. Where a run has two passes it sets both, and Handoff Step moves with "
    "it."
)

# Keyed by param name; the value is the whole tooltip.
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
        "The starting noise for the first pass (high noise), which settles the "
        "composition. Random draws a fresh one on every Generate."
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

    # --- LoRAs ---
    "lora_high": (
        "A LoRA trained for a specific look or subject, applied to the first "
        "pass (high noise). \"None\" leaves the model unmodified."
    ),
    "lora_low": (
        "A LoRA trained for a specific look or subject, applied to the second "
        "pass (low noise). \"None\" leaves the model unmodified."
    ),
    "lora_strength_high": (
        "How hard the first pass's LoRA (high noise) pulls. 1.0 is its intended "
        "strength; below 0.5 it barely shows, above 1.2 it tends to take over the "
        "picture. Good range: 0.6–1.2."
    ),
    "lora_strength_low": (
        "How hard the second pass's LoRA (low noise) pulls. 1.0 is its intended "
        "strength; below 0.5 it barely shows, above 1.2 it tends to take over the "
        "picture. Good range: 0.6–1.2."
    ),

    # --- calibration ---
    "steps": (
        "How many times the model goes over the picture, refining it. More steps "
        "means more settled detail and a longer wait, with little gain once the "
        "picture has stopped changing. Good range: 25–40 for SDXL pictures, 20–30 for "
        "Flux and WAN, and 4–8 when a speed LoRA is loaded."
    ),
    "cfg": (
        "How strictly the model obeys the prompt (the CFG scale underneath). Too low "
        "drifts off it; too high burns contrast and flattens detail. Good range: 3–7 "
        "for SDXL pictures, where most model pages ask for 4–5; 3–5 for WAN; 1 with a "
        "speed LoRA."
    ),
    "cfg_high": (
        "Prompt strength for the first pass (high noise; the CFG scale underneath), "
        "where the motion is settled. A LoRA's author often publishes a different "
        "number for each pass; where they publish one, put it in both. Good range: "
        "3–4, or 1 with a speed LoRA on this pass."
    ),
    "cfg_low": (
        "Prompt strength for the second pass (low noise; the CFG scale underneath), "
        "where the texture is settled. Good range: 3–4, or 1 with a speed LoRA on "
        "this pass."
    ),
    "split_step": (
        "The step where the first pass (high noise) hands over to the second (low "
        "noise; the split step). The first pass settles the layout and the motion and "
        "the second refines the detail; the two models are built to switch at one "
        "noise level, and Composition Focus decides which step reaches it, a lower "
        "focus sooner and a higher one later. Good range: 0, which hands over at half "
        "the steps and suits a Composition Focus of 8, or 40–60% of Steps. Hand over "
        "later (a bigger number) when the motion comes out weak or the layout "
        "wanders, and earlier when the detail comes out soft or smeared."
    ),
    "guidance": (
        "How strictly the model obeys the prompt (Flux's guidance value). It wants "
        "much smaller numbers than prompt strength does elsewhere. Good range: "
        "2.5–4.5; 3.5 is the usual start."
    ),
    "sampler_name": (
        "How the picture moves from noise toward the model's guess at each step; "
        "hover each choice for how it works and how long it takes. Good choices: "
        "euler_ancestral (Euler a on model pages), dpmpp_2m with Step Spacing karras "
        "(DPM++ 2M Karras) or dpmpp_sde with karras (DPM++ SDE Karras), the ones "
        "model pages recommend most."
    ),
    "scheduler": (
        "How the noise removed is spread across the steps: normal spreads it evenly, "
        "while karras and exponential take big steps first and small ones at the end, "
        "so more of the run goes to fine detail. It matters less than the Sampler and "
        "goes with it. Good choices: normal or simple with euler and euler_ancestral, "
        "karras with the dpmpp ones (DPM++ 2M Karras on model pages). To compare two, "
        "keep the seed and change only this, on two or three different prompts."
    ),
    "denoise": (
        "How much of the starting image is redrawn (the denoise strength). 1.0 "
        "generates from pure noise; lower keeps more of what was there and only "
        "re-imagines the rest. Good range: 1.0 for a new picture; 0.4–0.7 to keep "
        "more of a starting image."
    ),
    "shift": _COMPOSITION_FOCUS,
    "shift_high": _COMPOSITION_FOCUS,

    # --- the enhance tail (off the form; the Enhance subpanel owns these) ---
    "enhance_scale": (
        "How much bigger the enhanced version is than the render it came from. Past "
        "3x the pass has to invent a lot. Good range: 1.5–2x."
    ),
    "enhance_steps": (
        "How many times the enhancement goes over the enlarged picture. Around 20 is "
        "enough to build texture without redrawing anything. Good range: 15–25."
    ),
    "enhance_denoise": (
        "How far the enhance may stray from the picture it is refining (its denoise). "
        "0.15 adds skin and fabric texture; by 0.3 it starts re-imagining anatomy, "
        "which is where creases turn into wounds. Good range: 0.1–0.2."
    ),
    "enhance_detail_fixes": (
        "Which parts the enhance goes back over and redraws on their own, and how "
        "hard it redraws each. This is what mends a mouth melted into its teeth or a "
        "finger too many, and it can afford to be bold where the whole-picture pass "
        "cannot, since nothing outside the regions found is touched: around 0.45 "
        "actually re-forms a bad hand, while below 0.3 it only tidies the one it was "
        "given. Good range: 0.3–0.5 for each part."
    ),

    # --- structure transfer ---
    "control_mode": (
        "Which structure is lifted out of the structure image and held onto: its "
        "depth, or the skeleton of the people in it."
    ),
    "controlnet": "The model that holds the picture to the structure image (a ControlNet).",
    "controlnet_strength": (
        "How firmly the output is held to the structure image. Lower lets the prompt "
        "reshape things; higher traces the source closely. Good range: 0.5–0.9."
    ),
    "controlnet_end": (
        "How far into the drawing the structure keeps being held. Letting go early "
        "lets the last steps add detail the structure has no opinion on. Good range: "
        "0.6–1.0."
    ),

    # --- size and length ---
    "width": (
        "The output width in pixels. Good range: about one megapixel in all for SDXL, "
        "such as 832×1216, 1024×1024 or 1216×832; up to about two for Flux and WAN "
        "2.2 Text-to-Image."
    ),
    "height": (
        "The output height in pixels. Good range: about one megapixel in all for "
        "SDXL, such as 832×1216, 1024×1024 or 1216×832; up to about two for Flux and "
        "WAN 2.2 Text-to-Image."
    ),
    "frame_count": (
        "How long the clip runs, in seconds — of real motion, at any frame rate. Pick "
        "a length or type one; it is rounded to the frames the model works in, and "
        "stops where the model stops. Good range: 5–10 s for a clip and 1–3 s for a "
        "loop; a longer clip is made in pieces, each starting on the last frame of "
        "the one before, and can drift."
    ),
    "frame_rate": (
        "How smooth the motion looks. The model always paces the action at 16 frames "
        "a second; a higher rate fills in the frames between those, so the clip runs "
        "the same length at the same speed, just less steppy. Rates are multiples of "
        "16 because the frames are filled in a whole number at a time; anything else "
        "settles onto the nearest. Good range: 16, as the model makes it, or 32 for "
        "smoother motion."
    ),

    # --- the authored motion (track-conditioned video) ---
    "motion_hz": (
        "How many up-and-down cycles per second the generated motion runs at. Good "
        "range: 0.5–2; 1.2 to start."
    ),
    "motion_x": (
        "The horizontal line the motion travels along, in pixels across the frame. "
        "Good range: leave it at its starting value, and the app aims it from the "
        "Start Image itself; set by hand, keep it on the part that moves."
    ),
    "motion_ceiling": (
        "The pixel row the motion reaches at the high end of its travel. Good range: "
        "leave it at its starting value, and the app aims it from the Start Image "
        "itself; set by hand, keep it on the part that moves."
    ),
    "motion_floor": (
        "The pixel row the motion reaches at the low end of its travel. Good range: "
        "leave it at its starting value, and the app aims it from the Start Image "
        "itself; set by hand, keep it on the part that moves."
    ),
    "anchor_x": (
        "The horizontal position of the point that stays put while the motion moves. "
        "Good range: leave it at its starting value, and the app aims it from the "
        "Start Image itself; set by hand, keep it on the part that moves."
    ),
    "anchor_y": (
        "The vertical position of the point that stays put while the motion moves. "
        "Good range: leave it at its starting value, and the app aims it from the "
        "Start Image itself; set by hand, keep it on the part that moves."
    ),

    # --- sound ---
    "audio_prompt": (
        "What the generated soundtrack should be — the sounds themselves, not the "
        "picture. It watches the finished motion while it scores."
    ),
    "audio_negative_prompt": "Sounds to keep out of the generated soundtrack.",
}


# One line of help per choice a dropdown offers, keyed by param name, then choice.
OPTION_HELP: dict[str, dict[str, str]] = {
    "sampler_name": {
        "euler": (
            "Each step moves straight toward the model's guess of the finished picture, "
            "so it settles smoothly and early. One model run per step, the quickest kind."
        ),
        "euler_ancestral": (
            "Euler a on model pages: euler plus a little fresh noise after every step, so "
            "small details keep being re-imagined, with livelier texture, and a change of "
            "Steps changes the small details. One model run per step, as fast as euler."
        ),
        "heun": (
            "Takes each step, checks it with a second guess and averages the two, so each "
            "step is more accurate. Two model runs per step, about twice as slow as "
            "euler."
        ),
        "heunpp2": (
            "heun with up to a third guess per step. Up to three model runs per step, the "
            "slowest of the ones that keep to Steps."
        ),
        "dpm_2": (
            "Checks each step with a second guess from halfway along it. Two model runs "
            "per step, about twice as slow as euler."
        ),
        "dpm_2_ancestral": (
            "dpm_2 plus a little fresh noise after every step, like euler_ancestral. Two "
            "model runs per step, about twice as slow as euler."
        ),
        "lms": (
            "Aims each step with the guesses from the last few steps. One model run per "
            "step, as fast as euler; it can wobble at low Steps."
        ),
        "dpm_fast": (
            "A quick solver that spends exactly Steps model runs and ignores Step "
            "Spacing. About one model run per step, as fast as euler."
        ),
        "dpm_adaptive": (
            "Keeps going until the picture stops changing, choosing its own number of "
            "steps and ignoring Steps and Step Spacing. One model run per step or more, "
            "and the whole run often takes several times as long as euler's."
        ),
        "dpmpp_2s_ancestral": (
            "A DPM++ solver that takes a second guess at each step, plus a little fresh "
            "noise after it. Two model runs per step, about twice as slow as euler."
        ),
        "dpmpp_sde": (
            "A DPM++ solver with a second guess at each step and a measured amount of "
            "fresh noise, for detailed, lively pictures; with karras it is the DPM++ SDE "
            "Karras of model pages. Two model runs per step, about twice as slow as "
            "euler."
        ),
        "dpmpp_sde_gpu": (
            "dpmpp_sde with its fresh noise made on the graphics card, with similar "
            "results. Two model runs per step, about twice as slow as euler."
        ),
        "dpmpp_2m": (
            "Aims each step with the previous step's guess, so it is sharp and accurate "
            "at modest Steps; with karras it is the DPM++ 2M Karras many model pages "
            "recommend. One model run per step, as fast as euler."
        ),
        "dpmpp_2m_sde": (
            "dpmpp_2m plus a measured amount of fresh noise at each step, for more "
            "texture. One model run per step, as fast as euler."
        ),
        "dpmpp_2m_sde_gpu": (
            "dpmpp_2m_sde with its fresh noise made on the graphics card, with similar "
            "results. One model run per step, as fast as euler."
        ),
        "dpmpp_3m_sde": (
            "Aims each step with the last two steps' guesses, plus fresh noise; it wants "
            "a few more Steps than dpmpp_2m. One model run per step, as fast as euler."
        ),
        "dpmpp_3m_sde_gpu": (
            "dpmpp_3m_sde with its fresh noise made on the graphics card, with similar "
            "results. One model run per step, as fast as euler."
        ),
        "ddpm": (
            "The original diffusion sampler, adding fresh noise at every step; it needs "
            "many Steps to come out clean. One model run per step, as fast as euler."
        ),
        "lcm": (
            "Only for LCM models, which finish in 4 to 8 steps; on any other model it "
            "ruins the picture. One model run per step, as fast as euler."
        ),
        "ddim": (
            "An early sampler that moves straight toward the guess, much like euler. One "
            "model run per step, as fast as euler."
        ),
        "uni_pc": (
            "Aims each step from earlier guesses and corrects it afterwards, which does "
            "well at low Steps. One model run per step, as fast as euler."
        ),
        "uni_pc_bh2": (
            "uni_pc with a different correction, often a little better at very low Steps. "
            "One model run per step, as fast as euler."
        ),
    },
}

def param_help(key: str) -> str:
    """The tooltip for one param, or ``""`` when it has none.

    Empty rather than a placeholder: Qt shows no tooltip for an empty string,
    and an explanation that says nothing is worse than no explanation at all.
    """
    return PARAM_HELP.get(key, "")


def option_help(key: str, option: str) -> str:
    return OPTION_HELP.get(key, {}).get(option, "")
