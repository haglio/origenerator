"""Pure logic for combining a gallery image + a video's recipe into new params."""

import json

import pytest

from origenerator import gallery
from origenerator.config import STROKE_DEFAULT_HZ
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


def test_combined_params_drops_the_recipes_stored_size():
    # A recipe video carrying a size — an import's scraped one, or an unlocked
    # override — sized the frame IT ran on. Carried onto a differently shaped
    # image it would stretch it, so the swap drops it.
    video = _video_row(seed=3, noise_seed=9, width=720, height=928)
    image = _image_row([{"filename": "sdxl_new.png", "subfolder": ""}])

    params = gallery.combined_params(video, image, _I2V)

    assert "width" not in params and "height" not in params


def test_combined_params_payload_derives_the_size_from_the_dropped_image():
    # The end of the same story: with no size carried over, the built graph
    # scales to the pixel budget and reads the size back off the result, rather
    # than forcing the recipe's WxH onto an image of another shape.
    video = _video_row(seed=3, noise_seed=9, width=720, height=928)
    image = _image_row([{"filename": "sdxl_new.png", "subfolder": ""}])

    payload = _I2V.build_api_payload(gallery.combined_params(video, image, _I2V))

    assert payload["20"]["class_type"] == "ImageScaleToTotalPixels"
    assert payload["21"]["class_type"] == "GetImageSize"
    assert payload["14"]["inputs"]["width"] == ["21", 0]
    assert payload["14"]["inputs"]["height"] == ["21", 1]


def test_combined_params_keeps_width_and_height_for_a_manual_size_workflow():
    # The drop is gated on the workflow deriving its size, not on the key names:
    # a workflow that sizes by hand has width/height as real recipe settings.
    class _ManualSize:
        derives_size_from_input = False

        def default_params(self):
            return {"input_image": "", "width": 512, "height": 512}

        def enhance_keys(self):
            return ()

    video = _video_row(width=720, height=928)
    image = _image_row([{"filename": "sdxl_new.png", "subfolder": ""}])

    params = gallery.combined_params(video, image, _ManualSize())

    assert (params["width"], params["height"]) == (720, 928)

# --- curated_params: the overlay's hand-tuned act recipe on a dropped image ---


_SPEC = {
    "workflow": "wan22_i2v",
    "params": {"positive_prompt": "gamma form scene", "steps": 24,
               "lora_high": "example-act-high.safetensors"},
}


def test_curated_params_lays_the_spec_over_defaults_and_swaps_the_image():
    image = _image_row([{"filename": "sdxl_new.png", "subfolder": ""}])

    params = gallery.curated_params(_SPEC, image, _I2V)

    assert params["input_image"] == "sdxl_new.png [output]"
    assert params["positive_prompt"] == "gamma form scene"          # from the spec
    assert params["steps"] == 24                                    # from the spec
    assert params["lora_high"] == "example-act-high.safetensors"    # from the spec
    assert params["shift_high"] == _I2V.default_params()["shift_high"]  # unnamed → default


def test_curated_params_rerolls_every_seed():
    # A curated recipe has no exemplar run to reproduce; a pinned seed would
    # render the identical video for the same image every time.
    image = _image_row([{"filename": "sdxl_new.png", "subfolder": ""}])

    params = gallery.curated_params(_SPEC, image, _I2V)

    for key in _I2V.seed_keys():
        assert params[key] != _I2V.default_params()[key]


def test_curated_params_returns_none_when_image_has_no_output_file():
    assert gallery.curated_params(_SPEC, _image_row([]), _I2V) is None
    assert gallery.curated_params(_SPEC, _image_row(None), _I2V) is None


def test_a_recipe_written_against_the_shared_strength_still_renders_at_it():
    # A curated recipe stored before the stages had their own strength names one
    # shared number and a zero per stage; the workflow reads those the way it
    # always did, so the recipe keeps producing what it was tuned to produce.
    spec = {"workflow": "wan22_i2v",
            "params": {"cfg": 1.0, "cfg_high": 0.0, "cfg_low": 0.0, "steps": 8}}

    params = gallery.curated_params(spec, _image_row([{"filename": "a.png", "subfolder": ""}]), _I2V)
    samplers = [n for n in _I2V.build_api_payload(params).values()
                if n["class_type"] == "KSamplerAdvanced"]

    assert [n["inputs"]["cfg"] for n in samplers] == [1.0, 1.0]

# --- shaping a recipe into one stroke, for the lane that scrubs it ------------

_LOOP = WORKFLOW_REGISTRY["wan22_flf2v_loop"]


def _shaped(**over):
    return gallery.stroke_shaped(dict(_LOOP.default_params(), **over), _LOOP)


def test_a_genau_recipe_is_cut_to_the_length_one_stroke_fits_in():
    """The lane's whole problem: at 16fps a 21-frame loop is 1.3 seconds, and a
    stroke at the app's own cadence is 0.83 — so the model has room for a stroke
    and a half and Genau steers whatever it fits as one. 13 frames is 0.81."""
    shaped = _shaped()

    assert shaped["frame_count"] == 13
    assert shaped["frame_count"] / shaped["frame_rate"] == pytest.approx(
        1 / STROKE_DEFAULT_HZ, abs=0.05)


def test_the_length_lands_on_one_the_sampler_will_take():
    # 4n+1 and nothing else, whatever the rate makes of the arithmetic.
    for rate in (8.0, 12.0, 16.0, 24.0, 30.0, 60.0):
        assert (_shaped(frame_rate=rate)["frame_count"] - 1) % 4 == 0


def test_the_frames_taken_out_are_filled_back_in():
    """Few frames is the point AND the cost: the same clip that reads as one
    stroke is too coarse to scrub slowly. The pass fills it back up, which costs
    an interpolation rather than sampler time -- and gives the model no extra
    room to fit a second stroke in."""
    shaped = _shaped()

    frames_out = (shaped["frame_count"] - 1) * shaped["interpolation"] + 1
    assert frames_out >= 48
    # The seconds are unchanged: the writer's rate rises with the frames.
    assert shaped["frame_rate"] == _LOOP.default_params()["frame_rate"]


def test_the_smoothing_stays_inside_what_the_form_can_show():
    """A recipe sampling slowly enough needs a big multiplier, and a value past
    the workflow's own ceiling is one the user could not turn back down."""
    ceiling = next(pd.max_val for pd in _LOOP.param_definitions()
                   if pd.key == "interpolation")

    for rate in (4.0, 8.0, 16.0, 60.0):
        assert 1 <= _shaped(frame_rate=rate)["interpolation"] <= ceiling


def test_a_recipe_with_nothing_to_shape_is_handed_back_as_it_is():
    # This shapes a recipe; it does not invent one. A workflow with no length to
    # set and no pass to run has neither.
    params = {"positive_prompt": "alpha", "seed": 3}

    assert gallery.stroke_shaped(params, _I2V) == params
