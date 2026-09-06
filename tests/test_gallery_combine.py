"""Pure logic for combining a gallery image + a video's recipe into new params."""

import json

from origenerator import gallery
from origenerator.gallery import combine
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.frame_rate import MAX_PLAYBACK_FPS

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


def test_curated_params_moves_a_recipe_pinned_under_a_retired_key():
    """The overlay is the fourth home for a ParamDef key, and the only one
    nobody can migrate: it is the user's own file, hand-edited, git-ignored.

    Nothing validates a params key set, so a recipe still pinning the old
    spelling would silently fall back to the workflow's defaults for those
    values and write the dead keys into the run it started.
    """
    image = _image_row([{"filename": "sdxl_new.png", "subfolder": ""}])
    spec = {"workflow": "wan22_i2v", "params": {"stroke_hz": 1.5, "stroke_top": 490}}

    params = gallery.curated_params(spec, image, _I2V)

    assert params["motion_hz"] == 1.5
    assert params["motion_ceiling"] == 490
    assert "stroke_hz" not in params and "stroke_top" not in params


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

# --- shaping a recipe into one cycle, for the lane that scrubs it ------------

_LOOP = WORKFLOW_REGISTRY["wan22_flf2v_loop"]


def _shaped(category="", **over):
    return gallery.cycle_shaped(dict(_LOOP.default_params(), **over), _LOOP, category)


def test_a_genau_recipe_is_generated_at_the_shortest_length_that_closes():
    """Genau steers whatever it is given as ONE cycle, so the ideal clip is the
    shortest that holds exactly one — 13 frames by the cadence arithmetic. It is
    29 because the model cannot CLOSE a loop that short: measured at a fixed
    seed, the last frame lands 2% off the first at 13 frames and 0.2% off at 29,
    and under 29 the lighting pops on every repeat."""
    assert _shaped()["frame_count"] == combine.CYCLE_FRAMES == 29


def test_a_genau_recipe_plays_at_the_top_rate_the_writer_allows():
    """29 frames of one cycle is far too coarse to scrub slowly, which is most
    of what Genau is for. The frames in between are interpolated after decode, so
    asking for the top rate costs a pass rather than sampler time."""
    assert _shaped()["frame_rate"] == MAX_PLAYBACK_FPS


def test_the_words_that_ask_for_one_cycle_are_added_to_the_recipes_own():
    """At 29 frames the model fits about two cycles left to itself, so the lane
    asks for one outright. Added to the recipe's prompt rather than replacing it:
    the recipe says what the clip is OF, and this says how it moves."""
    shaped = _shaped(positive_prompt="alpha form", negative_prompt="beta")

    assert shaped["positive_prompt"].startswith("alpha form ")
    assert len(shaped["positive_prompt"]) > len("alpha form ")
    assert shaped["negative_prompt"].startswith("beta ")


def test_an_act_with_its_own_words_gets_them_and_the_rest_get_the_default():
    """A cycle is not one motion: what made the difference on the act it was
    tuned on was naming the cycle in STAGES, and the stages are different parts of
    the body from one act to the next."""
    own = combine.cycle_words("beta")
    default = combine.cycle_words("")

    assert own != default
    assert combine.cycle_words("an act with no entry") == default
    assert _shaped(positive_prompt="x", category="beta")["positive_prompt"] !=         _shaped(positive_prompt="x")["positive_prompt"]


def test_an_overlay_carrying_no_words_leaves_the_prompt_exactly_as_it_was(monkeypatch):
    # The wording is the library's, not this repo's, so a checkout without it
    # still shapes the length and the rate and says nothing about the motion.
    monkeypatch.setattr(combine, "_CYCLE_WORDS", {})
    params = dict(_LOOP.default_params(), positive_prompt="alpha", negative_prompt="")

    shaped = gallery.cycle_shaped(params, _LOOP)

    assert shaped["positive_prompt"] == "alpha"
    assert shaped["frame_count"] == combine.CYCLE_FRAMES


def test_a_recipe_with_nothing_to_shape_is_handed_back_as_it_is():
    # This shapes a recipe; it does not invent one. A workflow with no length and
    # no rate to set has neither.
    params = {"positive_prompt": "alpha", "seed": 3}

    assert gallery.cycle_shaped(params, WORKFLOW_REGISTRY["sdxl_t2i"]) == params
