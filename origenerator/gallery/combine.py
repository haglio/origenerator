"""Combine a gallery image with a video recipe into new i2v params.

The gallery already holds both halves of an image-to-video: a video row carries a
full recipe (workflow + settings + seed), and any image row's output file can seed
an i2v. This readies a recipe to re-run on a *different* image — the one input a
user picks — without touching a Generate tab. The recipe is either a past video's
(:func:`combined_params`, seed deliberately kept so the motion reproduces) or the
overlay's hand-tuned spec for an act (:func:`curated_params`, seeds re-rolled —
there is no past run to reproduce). Qt-free so it stays unit-testable.
"""

from origenerator.content import load_content
from origenerator.gallery.output import output_file_reference, row_output_files
from origenerator.generation_config import filled_params, randomize_seeds
from origenerator.workflows.frame_rate import MAX_PLAYBACK_FPS

_CONTENT = load_content()

# What a size-deriving workflow's stored size is recorded under. Not a recipe
# setting — it belongs to the frame the recipe ran on, not to the recipe.
_SIZE_KEYS = ("width", "height")

# How long a Genau clip is generated for, in frames at the native rate. Genau
# steers a clip as ONE stroke — see :func:`cycle_shaped` — so the ideal is the
# shortest clip that holds exactly one, and 13 frames is where the arithmetic
# lands (a stroke at the app's own cadence is 0.83 s, and 13/16 is 0.81).
#
# It is 29 because the model cannot close a loop that short. First-last-frame
# conditions both ends on the same picture, but the model needs room to come
# BACK to it, and measured over one recipe at a fixed seed the last frame lands
# this far from the first: 13 frames -2.02%, 17 +1.34%, 21 +0.99%, 29 +0.23%,
# 41 -0.19%, 81 +0.05%. Under 29 the lighting visibly pops on every repeat; at
# 29 it stops. So the length is set by the loop closing, and the ONE stroke is
# asked for in words instead (:data:`_CYCLE_WORDS`).
CYCLE_FRAMES = 29

# The words that ask a 29-frame loop for ONE stroke, and for a deep one, PER
# ACT: ``{act: {"positive": ..., "negative": ...}}`` with a ``""`` entry standing
# in for an act that has none of its own.
#
# Per act because a stroke is not one motion. What made the difference on the act
# it was tuned on was naming the cycle in stages -- out to one end, in to the
# other, back -- and the stages are different parts of the body from one act to
# the next; the wording that doubled the travel on one would be describing
# something that is not happening in another. The default carries whichever act's
# wording generalizes furthest, and an act sets its own when that is not close
# enough.
#
# In the overlay rather than here for the reason every other phrase the library
# speaks in is: this file is public, and the sanitize guard bans that vocabulary
# from the tracked tree. An overlay with none of this leaves every prompt exactly
# as its recipe wrote it.
_CYCLE_WORDS: dict = _CONTENT.get("genau_stroke_prompts") or {}


def combined_params(video_row: dict, image_row: dict, workflow) -> dict | None:
    """The video's recipe readied to re-run on a new input image, seed kept.

    ``video_row``'s stored params (anything sparse filled from ``workflow``'s
    defaults, exactly as :func:`generation_config.filled_params` — the seed is
    kept, not re-rolled), with ``input_image`` replaced by a ``LoadImage``-
    resolvable reference to ``image_row``'s output file. ``None`` when the image
    produced no file to reference.

    A size-deriving workflow's stored ``width``/``height`` are dropped on the way
    through: they size the recipe's OWN frame, and swapping the frame is the one
    thing this function does. Left in, they read as a deliberate override
    (:func:`~origenerator.workflows.derived_size.override_size`) and the graph
    scales the dropped image to that exact size with cropping disabled — a
    non-uniform stretch, which is precisely what "animate this image" must not
    do. Both ways a row comes by them are stale here: an import records whatever
    its graph's conditioning node said (``importer._extract_metadata``), and a
    generated row records an unlocked Dimensions override chosen for that other
    image. Dropped, the size re-derives from the dropped image and the new video
    keeps its proportions.
    """
    ref = output_file_reference(row_output_files(image_row))
    if ref is None:
        return None
    params = {**filled_params(video_row, workflow), "input_image": ref}
    if workflow.derives_size_from_input:
        for key in _SIZE_KEYS:
            params.pop(key, None)
    return params


def curated_params(spec: dict, image_row: dict, workflow) -> dict | None:
    """The overlay's hand-tuned act recipe readied to run on ``image_row``'s frame.

    ``spec["params"]`` over ``workflow``'s defaults, every seed re-rolled (a
    curated recipe has no exemplar run whose motion a kept seed would reproduce,
    and a pinned one would render the identical video for the same image every
    time), with ``input_image`` pointed at ``image_row``'s output file. ``None``
    when the image produced no file to reference.
    """
    ref = output_file_reference(row_output_files(image_row))
    if ref is None:
        return None
    params = dict(workflow.default_params())
    params.update(spec.get("params") or {})
    return {**randomize_seeds(params, workflow.seed_keys()), "input_image": ref}


def cycle_words(category: str = "") -> tuple[str, str]:
    """The ``(positive, negative)`` a Genau clip of ``category`` asks for, or the
    default pair when that act has none of its own -- see :data:`_CYCLE_WORDS`.

    Empty strings when the overlay carries nothing at all, which is what leaves
    a recipe's prompt untouched rather than appending a stray space.
    """
    words = _CYCLE_WORDS.get(category) or _CYCLE_WORDS.get("") or {}
    return ((words.get("positive") or "").strip(),
            (words.get("negative") or "").strip())


def cycle_shaped(params: dict, workflow, category: str = "") -> dict:
    """``params`` re-cut so the loop portrays ONE deep stroke, and plays smoothly.

    The Genau lane's whole problem: Genau does not play a clip, it scrubs it
    against the device's phase — so it steers whatever it is given as a single
    stroke running out to one extreme and back. A clip that holds two stumbles;
    a clip that holds four looks like a machine.

    Three settings answer that, and each was arrived at by measuring:

    * :data:`CYCLE_FRAMES` seconds of motion, because that is the shortest loop
      the model closes cleanly (see the note there).
    * The words, chosen by the act (:func:`cycle_words`). At 29 frames the model
      fits about two strokes on its own, so the prompt asks for one outright —
      naming the cycle in stages rather than saying "one stroke", which does
      nothing. The same wording doubled the travel, so the clip reads as a
      deliberate stroke rather than a wiggle. It rides the content overlay rather
      than this file, like every other phrase the library speaks in.
    * The top playback rate, because 29 frames of one stroke is too coarse to
      scrub slowly and the interpolator fills the rest in
      (:mod:`origenerator.workflows.frame_rate`).

    A workflow with no length or no rate to set is handed back unchanged: this
    shapes a recipe, it does not invent one.
    """
    defaults = workflow.default_params()
    if "frame_count" not in defaults or "frame_rate" not in defaults:
        return params
    positive, negative = cycle_words(category)
    shaped = {**params, "frame_count": CYCLE_FRAMES, "frame_rate": MAX_PLAYBACK_FPS}
    for key, extra in (("positive_prompt", positive),
                       ("negative_prompt", negative)):
        if extra:
            shaped[key] = f"{params.get(key) or ''} {extra}".strip()
    return shaped
