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

Params with no field of their own (a hidden VAE, an import's extras) are here
too: the form renders them as read-only rows, and a row you cannot change is
exactly the one you most want explained.
"""

# Keyed by param name; the value is the whole tooltip. Second person, no
# trailing period on a single clause, one sentence or two at most — a tooltip
# that runs long is one nobody finishes reading.
PARAM_HELP: dict[str, str] = {
    # --- prompts and the input picture ---
    "positive_prompt": (
        "What you want to see. Comma-separated phrases work best; the earlier a "
        "phrase appears, the more weight it tends to carry."
    ),
    "negative_prompt": (
        "What you want kept out — artifacts, styles, body parts you keep getting "
        "by accident. Leaving it empty is fine."
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
        "The starting noise for the first (high-noise) sampling stage, which "
        "settles the composition. Random draws a fresh one on every Generate."
    ),
    "audio_seed": (
        "The starting noise for the generated audio, separate from the picture's "
        "seed — re-roll it to get a different take of the same scene's sound."
    ),

    # --- models ---
    "checkpoint": (
        "The model that does the generating. It sets the look more than any other "
        "setting here — style, anatomy, what the prompt words mean to it."
    ),
    "unet": "The diffusion model file this run generates with.",
    "unet_high": (
        "The high-noise model: the first stage, which settles composition and "
        "motion before the low-noise pass refines it."
    ),
    "unet_low": (
        "The low-noise model: the second stage, which refines detail on what the "
        "high-noise pass laid down."
    ),
    "vae": "The decoder that turns the model's latent output into pixels.",
    "vae_name": "The decoder that turns the model's latent output into pixels.",
    "clip_name": "The text encoder that turns your prompt into what the model reads.",
    "clip_name1": "The first of two text encoders this model reads the prompt through.",
    "clip_name2": "The second of two text encoders this model reads the prompt through.",
    "clip_vision_name": (
        "The image encoder that lets the model read the input picture the way it "
        "reads the prompt."
    ),
    "upscale_model": (
        "The enlarger used before the enhance pass — an ESRGAN-family model that "
        "reconstructs edges rather than resampling them."
    ),
    "depth_model": (
        "The model that reads depth out of the input picture, producing the map "
        "the ControlNet holds the structure to."
    ),
    "pose_bbox_detector": "The detector that finds people in the input picture before posing them.",
    "pose_estimator": "The model that reads the skeleton out of each person it found.",
    "foley_model": "The model that scores the finished video with sound.",
    "foley_vae": "The decoder that turns the scoring model's output into audio.",
    "foley_synchformer": "The model that keeps the generated sound aligned to the motion on screen.",

    # --- LoRAs ---
    "lora_high": (
        "An add-on trained for a specific look or subject, applied to the "
        "high-noise stage. \"None\" leaves the base model unmodified."
    ),
    "lora_low": (
        "An add-on trained for a specific look or subject, applied to the "
        "low-noise stage. \"None\" leaves the base model unmodified."
    ),
    "lora_strength_high": (
        "How hard the high-noise LoRA pulls. 1.0 is its intended strength; below "
        "0.5 it barely shows, above 1.2 it tends to take over the picture."
    ),
    "lora_strength_low": (
        "How hard the low-noise LoRA pulls. 1.0 is its intended strength; below "
        "0.5 it barely shows, above 1.2 it tends to take over the picture."
    ),

    # --- sampling ---
    "steps": (
        "How many refinement passes the model makes. More steps means more "
        "settled detail and a longer wait, with little gain past the point the "
        "model has converged."
    ),
    "cfg": (
        "How strictly the model obeys the prompt. Too low drifts off it; too high "
        "burns contrast and flattens detail."
    ),
    "guidance": (
        "Flux's own prompt-adherence dial. It behaves like CFG but wants much "
        "smaller numbers — this model's usable range sits low."
    ),
    "sampler_name": (
        "The algorithm that walks the noise down to an image. They differ in look "
        "and in how many steps they need to settle."
    ),
    "scheduler": (
        "How the noise level is spaced across the steps. It changes where the "
        "detail lands more than whether the image is good."
    ),
    "denoise": (
        "How much of the starting image is thrown away. 1.0 generates from pure "
        "noise; lower keeps more of what was there and only re-imagines the rest."
    ),
    "shift": (
        "Where this model spends its sampling effort — higher favors composition, "
        "lower favors fine detail."
    ),
    "shift_high": "Where the high-noise stage spends its effort: higher favors composition.",
    "shift_low": "Where the low-noise stage spends its effort: lower favors fine detail.",

    # --- the enhance tail (off the form; the Enhance subpanel owns these) ---
    "enhance": (
        "Whether this run finishes with the upscale and low-denoise re-sample. "
        "Enhancement is applied as a separate layer now, from the Enhance panel, "
        "so nothing sets this by hand any more."
    ),
    "enhance_scale": (
        "How much bigger the enhanced version is than the render it came from. "
        "2x is the usual finish; past 3x the pass has to invent a lot."
    ),
    "enhance_steps": (
        "How many refinement passes the enhance makes over the enlarged picture. "
        "Around 20 is enough to build texture without redrawing anything."
    ),
    "enhance_denoise": (
        "How far the enhance may stray from the picture it is refining. 0.15 adds "
        "skin and fabric texture; by 0.3 it starts re-imagining anatomy, which is "
        "where creases turn into wounds."
    ),

    # --- structure transfer ---
    "control_mode": (
        "Which structure is lifted out of the input picture and held onto: its "
        "depth, or the skeleton of the people in it."
    ),
    "controlnet": "The ControlNet that applies the structure map to the generation.",
    "controlnet_strength": (
        "How firmly the output is held to the input's structure. Lower lets the "
        "prompt reshape things; higher traces the source closely."
    ),
    "controlnet_end": (
        "How far into the sampling the structure keeps being enforced. Releasing "
        "early lets the last steps add detail the structure map has no opinion on."
    ),

    # --- size and length ---
    "width": "The output width in pixels.",
    "height": "The output height in pixels.",
    "length": "How many frames the model generates for this clip.",
    "frame_count": (
        "How many frames the video is. Divided by the frame rate, this is how many "
        "seconds you get."
    ),
    "frame_rate": (
        "Frames per second in the saved video. It sets playback speed, not how much "
        "the model generates — that is the frame count."
    ),

    # --- the authored stroke (track-conditioned video) ---
    "stroke_hz": "How many strokes per second the generated motion runs at.",
    "stroke_x": "The horizontal line the stroke travels along, in pixels across the frame.",
    "stroke_top": "The pixel row the stroke reaches at the top of its travel.",
    "stroke_bottom": "The pixel row the stroke reaches at the bottom of its travel.",
    "anchor_x": "The horizontal position of the point that stays put while the stroke moves.",
    "anchor_y": "The vertical position of the point that stays put while the stroke moves.",

    # --- audio ---
    "audio_prompt": (
        "What the generated soundtrack should be — the sounds themselves, not the "
        "picture. It watches the finished motion while it scores."
    ),
    "audio_negative_prompt": "Sounds to keep out of the generated soundtrack.",

    # --- output ---
    "batch_size": (
        "How many images this run makes from one prompt. Each gets its own file; "
        "they are siblings of one run, not versions of one image."
    ),
    "crf": (
        "The video encoder's quality dial, where lower means a bigger, cleaner "
        "file. It affects the saved file only, never what was generated."
    ),
    "filename_prefix": (
        "The folder and name stem the output is saved under, inside ComfyUI's "
        "output directory. ComfyUI appends its own counter."
    ),
}


def param_help(key: str) -> str:
    """The tooltip for one param, or ``""`` when it has none.

    Empty rather than a placeholder: Qt shows no tooltip for an empty string,
    and an explanation that says nothing is worse than no explanation at all.
    """
    return PARAM_HELP.get(key, "")
