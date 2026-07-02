"""Pure logic for combining a gallery image + a video's recipe into new params."""

import json

from origenerator import gallery
from origenerator.workflows import WORKFLOW_REGISTRY

_I2V = WORKFLOW_REGISTRY["wan22_i2v"]


def _video_row(**params):
    """A completed i2v video row whose params_json carries the given values."""
    return {
        "prompt_id": "vid",
        "workflow_name": "wan22_i2v",
        "params_json": json.dumps(params),
        "output_files": json.dumps([{"filename": "wan22_i2v_vid.mp4", "subfolder": ""}]),
    }


def _image_row(files):
    """An image row with the given output_files list (or None)."""
    return {
        "prompt_id": "img",
        "workflow_name": "sdxl_t2i",
        "params_json": "{}",
        "output_files": json.dumps(files) if files is not None else None,
    }


def test_combined_params_swaps_input_image_and_keeps_video_seeds():
    video = _video_row(seed=3, noise_seed=9, positive_prompt="a cat", steps=20)
    image = _image_row([{"filename": "sdxl_new.png", "subfolder": ""}])

    params = gallery.combined_params(video, image, _I2V)

    assert params["input_image"] == "sdxl_new.png [output]"
    assert params["seed"] == 3
    assert params["noise_seed"] == 9
    assert params["positive_prompt"] == "a cat"


def test_combined_params_fills_missing_params_from_workflow_defaults():
    # A sparse video row (e.g. an import) still builds a full, submittable recipe.
    video = _video_row(seed=3, noise_seed=9)
    image = _image_row([{"filename": "sdxl_new.png", "subfolder": ""}])

    params = gallery.combined_params(video, image, _I2V)

    assert params["steps"] == _I2V.default_params()["steps"]  # filled from defaults
    assert params["seed"] == 3 and params["noise_seed"] == 9   # seeds still preserved


def test_combined_params_returns_none_when_image_has_no_output_file():
    video = _video_row(seed=3, noise_seed=9)

    assert gallery.combined_params(video, _image_row([]), _I2V) is None
    assert gallery.combined_params(video, _image_row(None), _I2V) is None


def test_combined_params_references_the_images_subfolder_output():
    video = _video_row(seed=3, noise_seed=9)
    image = _image_row([{"filename": "sdxl_new.png", "subfolder": "images"}])

    params = gallery.combined_params(video, image, _I2V)

    assert params["input_image"] == "images/sdxl_new.png [output]"
