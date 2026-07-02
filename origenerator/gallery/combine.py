"""Combine a gallery image with another video's recipe into new i2v params.

The gallery already holds both halves of an image-to-video: a video row carries a
full recipe (workflow + settings + seed), and any image row's output file can seed
an i2v. This readies that video's recipe to re-run on a *different* image — the one
input a user picks — without touching a Generate tab. Qt-free so it stays
unit-testable; the seed is deliberately kept (reused), not re-rolled.
"""

from origenerator.generation_config import filled_params
from origenerator.gallery.output import output_file_reference, row_output_files


def combined_params(video_row: dict, image_row: dict, workflow) -> dict | None:
    """The video's recipe readied to re-run on a new input image, seed kept.

    ``video_row``'s stored params (anything sparse filled from ``workflow``'s
    defaults, exactly as :func:`generation_config.filled_params` — the seed is
    kept, not re-rolled), with ``input_image`` replaced by a ``LoadImage``-
    resolvable reference to ``image_row``'s output file. ``None`` when the image
    produced no file to reference.
    """
    ref = output_file_reference(row_output_files(image_row))
    if ref is None:
        return None
    return {**filled_params(video_row, workflow), "input_image": ref}
