"""Combine a gallery image with another video's recipe into new i2v params.

The gallery already holds both halves of an image-to-video: a video row carries a
full recipe (workflow + settings + seed), and any image row's output file can seed
an i2v. This readies that video's recipe to re-run on a *different* image — the one
input a user picks — without touching a Generate tab. Qt-free so it stays
unit-testable; the seed is deliberately kept (reused), not re-rolled.
"""

from origenerator.generation_config import filled_params
from origenerator.gallery.output import output_file_reference, row_output_files

# What a size-deriving workflow's stored size is recorded under. Not a recipe
# setting — it belongs to the frame the recipe ran on, not to the recipe.
_SIZE_KEYS = ("width", "height")


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
