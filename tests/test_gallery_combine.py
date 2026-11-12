from __future__ import annotations

import json

import pytest

from origenerator import gallery
from origenerator.content import EXAMPLE_CONTENT, load_content
from origenerator.gallery import combine
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.frame_rate import MAX_PLAYBACK_FPS

_I2V = WORKFLOW_REGISTRY["wan22_i2v"]


def _video_row(**params):
    return {
        "prompt_id": "vid",
        "workflow_name": "wan22_i2v",
        "params_json": json.dumps(params),
        "output_files": json.dumps([{"filename": "wan22_i2v_vid.mp4", "subfolder": ""}]),
    }


def _image(files):
    return gallery.output_file_reference(files or [])


def test_a_combination_runs_the_settings_on_the_dropped_image_with_fresh_seeds():
    video = _video_row(noise_seed=0, audio_seed=0, positive_prompt="a cat", steps=20)
    image = _image([{"filename": "sdxl_new.png", "subfolder": ""}])

    params = gallery.combined_params(video, image, _I2V)

    assert params["input_image"] == "sdxl_new.png [output]"
    assert params["positive_prompt"] == "a cat"
    assert params["steps"] == 20
    assert params["noise_seed"] != 0
    assert params["audio_seed"] != 0


def test_combined_params_fills_missing_params_from_workflow_defaults():
    video = _video_row(seed=3, noise_seed=9)
    image = _image([{"filename": "sdxl_new.png", "subfolder": ""}])

    params = gallery.combined_params(video, image, _I2V)

    assert params["steps"] == _I2V.default_params()["steps"]


def test_an_image_with_no_file_on_disk_cannot_be_combined():
    video = _video_row(seed=3, noise_seed=9)

    assert gallery.combined_params(video, _image([]), _I2V) is None
    assert gallery.combined_params(video, None, _I2V) is None


def test_combined_params_references_the_images_subfolder_output():
    video = _video_row(seed=3, noise_seed=9)
    image = _image([{"filename": "sdxl_new.png", "subfolder": "images"}])

    params = gallery.combined_params(video, image, _I2V)

    assert params["input_image"] == "images/sdxl_new.png [output]"


def test_combined_params_drops_the_videos_stored_size():
    video = _video_row(seed=3, noise_seed=9, width=720, height=928)
    image = _image([{"filename": "sdxl_new.png", "subfolder": ""}])

    params = gallery.combined_params(video, image, _I2V)

    assert "width" not in params, (
        "a source video's size sized the frame it ran on; carried onto an image of another shape "
        "it would stretch it")
    assert "height" not in params


def test_combined_params_payload_derives_the_size_from_the_dropped_image():
    video = _video_row(seed=3, noise_seed=9, width=720, height=928)
    image = _image([{"filename": "sdxl_new.png", "subfolder": ""}])

    payload = _I2V.build_api_payload(gallery.combined_params(video, image, _I2V))

    scaled = next(nid for nid, n in payload.items()
                  if n["class_type"] == "ImageScaleToTotalPixels")
    sized = next(nid for nid, n in payload.items() if n["class_type"] == "GetImageSize")
    assert payload[sized]["inputs"]["image"] == [scaled, 0]
    reader = next(n for n in payload.values()
                  if n["inputs"].get("width") == [sized, 0])
    assert reader["inputs"]["height"] == [sized, 1]


def test_combined_params_keeps_width_and_height_for_a_manual_size_workflow():
    class _ManualSize:
        derives_size_from_input = False

        def default_params(self):
            return {"input_image": "", "width": 512, "height": 512}

        def enhance_keys(self):
            return ()

        def seed_keys(self):
            return ()

    video = _video_row(width=720, height=928)
    image = _image([{"filename": "sdxl_new.png", "subfolder": ""}])

    params = gallery.combined_params(video, image, _ManualSize())

    assert (params["width"], params["height"]) == (720, 928)


def _source_video_run(**video_params):
    video = _video_row(**video_params)
    return video, gallery.combined_params(
        video, _image([{"filename": "sdxl_new.png", "subfolder": ""}]), _I2V)


def test_a_run_whose_negative_prompt_moved_off_its_source_videos_differs_from_it():
    video, params = _source_video_run(positive_prompt="alpha form", negative_prompt="beta")

    assert not gallery.prompts_differ_from(params, video, _I2V)
    assert gallery.prompts_differ_from({**params, "negative_prompt": "gamma"}, video, _I2V)


@pytest.mark.parametrize(("key", "words"), [("audio_prompt", "a low hum"),
                                             ("audio_negative_prompt", "static"),
                                             ("scene_lines", ["hello there"])])
def test_the_audio_prompts_and_the_spoken_lines_are_words_of_the_settings_too(key, words):
    video, params = _source_video_run(positive_prompt="alpha form")

    assert gallery.prompts_differ_from({**params, key: words}, video, _I2V)


def test_the_same_words_spaced_or_wrapped_differently_are_still_the_source_videos():
    video, params = _source_video_run(positive_prompt="alpha form,\r\ncalm", negative_prompt="beta")

    respaced = {**params, "positive_prompt": "alpha form, calm  ", "negative_prompt": " beta"}

    assert not gallery.prompts_differ_from(respaced, video, _I2V)


def test_a_run_carrying_no_lines_says_what_settings_with_empty_lines_say():
    video, params = _source_video_run(positive_prompt="alpha form")
    params.pop("scene_lines")

    assert not gallery.prompts_differ_from(params, video, _I2V)


def test_a_run_missing_a_prompt_reads_it_as_the_workflows_default():
    video, params = _source_video_run(positive_prompt="alpha form")
    params.pop("audio_negative_prompt")

    assert not gallery.prompts_differ_from(params, video, _I2V)


def test_the_words_the_genau_lane_adds_are_words_the_source_video_never_said():
    video, params = _source_video_run(positive_prompt="alpha form", negative_prompt="beta")

    assert gallery.prompts_differ_from(gallery.cycle_shaped(params, _I2V), video, _I2V)


_SPEC = {
    "workflow": "wan22_i2v",
    "params": {"positive_prompt": "gamma form scene", "steps": 24,
               "lora_high": "example-action-high.safetensors"},
}


def test_written_params_lays_the_spec_over_defaults_and_swaps_the_image():
    image = _image([{"filename": "sdxl_new.png", "subfolder": ""}])

    params = gallery.written_params(_SPEC, image, _I2V)

    assert params["input_image"] == "sdxl_new.png [output]"
    assert params["positive_prompt"] == "gamma form scene"
    assert params["steps"] == 24
    assert params["lora_high"] == "example-action-high.safetensors"
    assert params["shift_high"] == _I2V.default_params()["shift_high"]


def test_written_params_rerolls_every_seed():
    image = _image([{"filename": "sdxl_new.png", "subfolder": ""}])

    params = gallery.written_params(_SPEC, image, _I2V)

    for key in _I2V.seed_keys():
        assert params[key] != _I2V.default_params()[key]


def test_an_image_with_no_file_on_disk_runs_nothing():
    assert gallery.written_params(_SPEC, _image([]), _I2V) is None
    assert gallery.written_params(_SPEC, _image(None), _I2V) is None


def test_settings_written_against_the_shared_strength_still_render_at_it():
    spec = {"workflow": "wan22_i2v",
            "params": {"cfg": 1.0, "cfg_high": 0.0, "cfg_low": 0.0, "steps": 8}}

    params = gallery.written_params(spec, _image([{"filename": "a.png", "subfolder": ""}]), _I2V)
    samplers = [n for n in _I2V.build_api_payload(params).values()
                if n["class_type"] == "KSamplerAdvanced"]

    assert [n["inputs"]["cfg"] for n in samplers] == [1.0, 1.0]

_LOOP = WORKFLOW_REGISTRY["wan22_flf2v_loop"]


def _shaped(category="", **over):
    return gallery.cycle_shaped(dict(_LOOP.default_params(), **over), _LOOP, category)


def test_genau_settings_are_generated_at_the_shortest_length_that_closes():
    assert _shaped()["frame_count"] == combine.CYCLE_FRAMES == 29, (
        "the model cannot close a loop shorter than this: under 29 frames the last frame lands "
        "visibly off the first and the lighting pops on every repeat")


def test_genau_settings_play_at_the_top_rate_the_writer_allows():
    assert _shaped()["frame_rate"] == MAX_PLAYBACK_FPS, (
        "29 frames of one cycle are far too coarse to scrub slowly, which is most of what Genau is "
        "for; the frames between are interpolated after decode, so the top rate costs a pass and "
        "no sampler time")


def test_the_words_that_ask_for_one_cycle_are_added_to_the_videos_own():
    shaped = _shaped(positive_prompt="alpha form", negative_prompt="beta")

    assert shaped["positive_prompt"] != "alpha form", (
        "Genau does not play a video, it scrubs it against the device's phase as a single cycle "
        "out and back, and left to itself the model fits about two cycles into 29 frames, so "
        "the words ask for one outright")
    assert shaped["positive_prompt"].startswith("alpha form "), (
        "added to the video's prompt rather than replacing it: the prompt says what the video "
        "is of, and these words say how it moves")
    assert len(shaped["positive_prompt"]) > len("alpha form ")
    assert shaped["negative_prompt"].startswith("beta ")


def test_a_loop_of_several_actions_takes_the_words_of_each_that_has_its_own(monkeypatch):
    monkeypatch.setattr(combine, "_CYCLE_WORDS", {
        "": {"positive": "a default cycle"},
        "alpha": {"positive": "an alpha cycle", "negative": "no alpha"},
        "third box": {"positive": "a third box ending"}})

    assert combine.cycle_words("Alpha", "beta", "Third Box") == (
        "an alpha cycle a third box ending", "no alpha")
    assert combine.cycle_words("beta") == ("a default cycle", "")


def test_a_loop_whose_own_actions_have_no_words_takes_its_images_words(monkeypatch):
    monkeypatch.setattr(combine, "_CYCLE_WORDS", {"alpha": {"positive": "an alpha cycle"}})

    assert combine.cycle_names(("beta",), ("alpha",)) == ("beta", "alpha")
    assert combine.cycle_names(("alpha", "beta"), ("gamma",)) == ("alpha", "beta")


def test_an_action_with_its_own_words_gets_them_and_the_rest_get_the_default():
    own = combine.cycle_words("beta")
    default = combine.cycle_words("")

    assert own != default, (
        "a cycle is not one motion: its stages are different parts of the body from one action "
        "to the next")
    assert combine.cycle_words("an action with no entry") == default
    assert (_shaped(positive_prompt="x", category="beta")["positive_prompt"]
            != _shaped(positive_prompt="x")["positive_prompt"])


def test_an_actions_cycle_words_are_the_ones_the_overlay_gives_it():
    overlaid = load_content(EXAMPLE_CONTENT)["genau_flick_prompts"]["beta"]

    assert combine.cycle_words("beta") == (overlaid["positive"], overlaid["negative"]), (
        "the cycle words come from the overlay, as every other phrase the library speaks in "
        "does: this code is public, and the blocked-word check bans that vocabulary from the "
        "tracked tree")


def test_an_overlay_carrying_no_words_leaves_the_prompt_exactly_as_it_was(monkeypatch):
    monkeypatch.setattr(combine, "_CYCLE_WORDS", {})
    params = dict(_LOOP.default_params(), positive_prompt="alpha", negative_prompt="")

    shaped = gallery.cycle_shaped(params, _LOOP)

    assert (shaped["positive_prompt"], shaped["negative_prompt"]) == ("alpha", ""), (
        "an overlay with no cycle words leaves both prompts exactly as the settings wrote them, "
        "without even a stray space added")
    assert shaped["frame_count"] == combine.CYCLE_FRAMES


def test_settings_with_nothing_to_shape_are_handed_back_as_they_are():
    params = {"positive_prompt": "alpha", "seed": 3}

    assert gallery.cycle_shaped(params, WORKFLOW_REGISTRY["sdxl_t2i"]) == params
