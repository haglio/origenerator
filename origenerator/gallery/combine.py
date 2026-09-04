"""Combine a gallery image with a video recipe into new i2v params.

The gallery already holds both halves of an image-to-video: a video row carries a
full recipe (workflow + settings + seed), and any image row's output file can seed
an i2v. This readies a recipe to re-run on a *different* image — the one input a
user picks — without touching a Generate tab. The recipe is either a past video's
(:func:`combined_params`, seed deliberately kept so the motion reproduces) or the
overlay's hand-tuned spec for an act (:func:`curated_params`, seeds re-rolled —
there is no past run to reproduce). Qt-free so it stays unit-testable.
"""

import math

from origenerator.config import STROKE_DEFAULT_HZ
from origenerator.gallery.output import output_file_reference, row_output_files
from origenerator.generation_config import filled_params, randomize_seeds

# What a size-deriving workflow's stored size is recorded under. Not a recipe
# setting — it belongs to the frame the recipe ran on, not to the recipe.
_SIZE_KEYS = ("width", "height")

# How many frames a Genau clip should end up holding. Genau does not play a clip
# at its own rate — it scrubs it against the device's phase — so at slow speeds
# it holds single frames on screen, and how smooth the motion is there is simply
# how many frames the clip has to show for one stroke. Four dozen is about where
# a slow stroke stops looking stepped; they are filled in rather than sampled
# (see :meth:`~origenerator.workflows.base.WorkflowTemplate.interpolation_nodes`),
# so this costs a cheap pass rather than sampler time.
_FRAMES_PER_STROKE = 48

# The sampler takes a frame count of 4n+1 and nothing else, so a length worked
# out from seconds has to land on one.
_LENGTH_STEP = 4
_MIN_LENGTH = 5

# The most the smoothing pass may be asked for -- the ceiling the workflow's own
# ParamDef puts on it, so a shaped recipe is a value the form can also show and
# the user can also turn back down. Reached only by a recipe sampling slowly
# enough that one stroke is a handful of frames.
_MAX_SMOOTHING = 8


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


def _sampler_length(frames: float) -> int:
    """``frames`` rounded to the nearest length the sampler will take (4n+1)."""
    steps = round((frames - 1) / _LENGTH_STEP)
    return max(_MIN_LENGTH, _LENGTH_STEP * steps + 1)


def stroke_shaped(params: dict, workflow) -> dict:
    """``params`` re-cut so the loop portrays ONE stroke, and portrays it smoothly.

    The Genau lane's whole problem: Genau steers a clip as though it ran from one
    extreme of the stroke, through the other at its midpoint, and back — and a
    loop sampled for a second and a third of a second at a natural pace fits a
    stroke and a half or two into that, so the device makes one slow stroke while
    the pixels make several. Cutting the finished clip down cannot fix it: the
    only two frames a first-last-frame loop guarantees will match are its first
    and its last, so a cut anywhere inside pops when it repeats.

    So the loop is asked for at a length ONE stroke fits in — the app's own
    cadence (:data:`~origenerator.config.STROKE_DEFAULT_HZ`) says how long that
    is, and the frame rate turns it into frames — and the endpoints do the rest:
    the sampler must return to the frame it started on, and at that length there
    is only room to go out and come back once.

    Few frames is the point, and also the cost: the same clip that reads as one
    stroke is too coarse to scrub slowly. So the smoothing pass fills it back up
    to :data:`_FRAMES_PER_STROKE`, which costs a cheap interpolation rather than
    sampler time — and, unlike sampling them, gives the model no extra room to
    fit another stroke in.

    A workflow with no length to set or no pass to run is handed back unchanged:
    this shapes a recipe, it does not invent one.
    """
    defaults = workflow.default_params()
    if "frame_count" not in defaults or "interpolation" not in defaults:
        return params
    rate = float(params.get("frame_rate") or defaults.get("frame_rate") or 0) or 16.0
    frames = _sampler_length(rate / STROKE_DEFAULT_HZ)
    return {
        **params,
        "frame_count": frames,
        "interpolation": max(1, min(_MAX_SMOOTHING,
                                    math.ceil(_FRAMES_PER_STROKE / (frames - 1)))),
    }
