"""The map around one generation: what shares its config, what shares its seed,
and what is nearest beyond that.

Fixture rows are fabricated (see CLAUDE.md); the settings-folder and model
keys they are grouped by are the gallery's own.
"""
from __future__ import annotations

import json

from origenerator import gallery
from origenerator.nav_map import (
    act_labels,
    beyond_the_row,
    one_per_stretch,
    seed_family,
    surroundings,
)


def _image(prompt_id, prompt, *, seed, steps=50, checkpoint="model_a.safetensors"):
    return {
        "prompt_id": prompt_id,
        "workflow_name": "sdxl_t2i",
        "positive_prompt": prompt,
        "seed": seed,
        "params_json": json.dumps({"positive_prompt": prompt, "seed": seed,
                                   "steps": steps, "checkpoint": checkpoint}),
        "output_files": json.dumps([{"filename": f"{prompt_id}.png"}]),
    }


def _ids(rows) -> list[str]:
    return [row["prompt_id"] for row in rows]


def test_the_seed_row_is_the_rest_of_the_items_own_settings_folder():
    current = _image("g2", "a red fox in snow", seed=2)
    sibling = _image("g1", "a red fox in snow", seed=1)
    other_config = _image("g3", "a red fox in snow", seed=3, steps=30)

    row = seed_family(current, [sibling, other_config, current], image_index={})

    assert _ids(row) == ["g2", "g1"]


def _video(prompt_id, prompt, *, noise_seed, frame, lora="lora_a", act=None):
    """A WAN image-to-video row: its sampler seed is ``noise_seed``, so the
    ``seed`` column a picture fills stays empty on it."""
    return {
        "prompt_id": prompt_id,
        "workflow_name": "wan22_i2v",
        "positive_prompt": prompt,
        "recipe_category": act,
        "seed": None,
        "params_json": json.dumps({
            "positive_prompt": prompt, "noise_seed": noise_seed, "input_image": frame,
            "unet_high": "wan_high.safetensors", "unet_low": "wan_low.safetensors",
            "lora_high": f"{lora}_high.safetensors", "lora_low": f"{lora}_low.safetensors",
        }),
        "output_files": json.dumps([{"filename": f"{prompt_id}.mp4"}]),
    }


def test_beyond_a_pictures_row_lie_the_nearest_other_configurations_of_its_model():
    current = _image("g1", "a red fox sleeping in deep snow", seed=1)
    sibling = _image("g2", "a red fox sleeping in deep snow", seed=2)
    near = _image("g3", "a red fox running in deep snow", seed=3)
    nearer = _image("g4", "a red fox sleeping in snow", seed=4)
    far = _image("g5", "a blue car parked by the harbor", seed=5)
    other_model = _image("g6", "a red fox sleeping in deep snow", seed=6,
                         checkpoint="model_b.safetensors")

    beyond = beyond_the_row(current, [far, near, sibling, nearer, other_model, current],
                            image_index={})

    assert _ids(beyond) == ["g4", "g3", "g5"]


# --- the column: a picture and the videos animated from it -----------------------


def test_a_pictures_column_is_the_videos_animated_from_it_each_named_for_its_act():
    picture = _image("i1", "a fox", seed=1)
    other_picture = _image("i2", "a fox", seed=2)
    index = gallery.build_image_config_index([picture, other_picture])
    runs = _video("v1", "the fox runs", noise_seed=5, frame="i1.png", act="alpha")
    sleeps = _video("v2", "the fox sleeps", noise_seed=6, frame="i1.png", act="beta")
    elsewhere = _video("v3", "the fox runs", noise_seed=7, frame="i2.png", act="alpha")

    around = surroundings(picture, [picture, other_picture, runs, sleeps, elsewhere],
                          image_index=index)

    assert [(row["prompt_id"], label) for row, label in around.actions] == [
        ("v1", "alpha"), ("v2", "beta")]


def test_two_videos_of_one_act_share_a_row_so_the_column_steps_between_acts():
    picture = _image("i1", "a fox", seed=1)
    index = gallery.build_image_config_index([picture])
    first = _video("v1", "the fox runs", noise_seed=5, frame="i1.png", act="alpha")
    again = _video("v2", "the fox runs", noise_seed=6, frame="i1.png", act="alpha")
    sleeps = _video("v3", "the fox sleeps", noise_seed=7, frame="i1.png", act="beta")

    around = surroundings(picture, [picture, first, again, sleeps], image_index=index)

    assert [(row["prompt_id"], label) for row, label in around.actions] == [
        ("v1", "alpha"), ("v3", "beta")]


def test_a_videos_column_is_its_source_picture_then_that_pictures_other_acts():
    picture = _image("i1", "a fox", seed=1)
    index = gallery.build_image_config_index([picture])
    runs = _video("v1", "the fox runs", noise_seed=5, frame="i1.png", act="alpha")
    runs_again = _video("v2", "the fox runs", noise_seed=6, frame="i1.png", act="alpha")
    sleeps = _video("v3", "the fox sleeps", noise_seed=7, frame="i1.png", act="beta")

    around = surroundings(runs, [picture, runs, runs_again, sleeps], image_index=index)

    assert [(row["prompt_id"], label) for row, label in around.actions] == [
        ("i1", "Source image"), ("v3", "beta")]


def test_each_generation_names_its_own_row_by_the_act_it_shows():
    picture = _image("i1", "a fox", seed=1)
    index = gallery.build_image_config_index([picture])
    runs = _video("v1", "the fox runs", noise_seed=5, frame="i1.png", act="alpha")
    library = [picture, runs]

    assert surroundings(runs, library, image_index=index).label == "alpha"
    assert surroundings(picture, library, image_index=index).label == "Source image"


def test_a_source_picture_carries_the_act_it_shows_beside_being_a_source():
    picture = _image("i1", "a fox in a beta form", seed=1)
    index = gallery.build_image_config_index([picture])
    runs = _video("v1", "the fox runs", noise_seed=5, frame="i1.png", act="alpha")

    around = surroundings(runs, [picture, runs], image_index=index)

    assert [label for _row, label in around.actions] == ["Source image, beta"]


def test_a_picture_nothing_was_animated_from_is_no_source_and_names_only_its_act():
    shows_an_act = _image("i1", "a fox in a beta form", seed=1)
    shows_none = _image("i2", "a fox", seed=2)
    index = gallery.build_image_config_index([shows_an_act, shows_none])
    library = [shows_an_act, shows_none]

    assert surroundings(shows_an_act, library, image_index=index).label == "beta"
    assert surroundings(shows_none, library, image_index=index).label == ""


# --- the seed row: keyed by the picture, not by the video's own sampler ---------


def test_a_videos_seed_row_is_its_act_animated_from_its_pictures_other_seeds():
    one = _image("i1", "a fox", seed=1)
    two = _image("i2", "a fox", seed=2)
    another_config = _image("i3", "a hare", seed=3)
    index = gallery.build_image_config_index([one, two, another_config])
    current = _video("v1", "the fox runs", noise_seed=5, frame="i1.png", act="alpha")
    same_act = _video("v2", "the fox runs", noise_seed=9, frame="i2.png", act="alpha")
    other_act = _video("v3", "the fox sleeps", noise_seed=5, frame="i2.png", act="beta")
    other_family = _video("v4", "the hare runs", noise_seed=5, frame="i3.png", act="alpha")

    around = surroundings(
        current, [one, two, another_config, current, same_act, other_act, other_family],
        image_index=index)

    assert _ids(around.seeds) == ["v2"]


def test_a_videos_own_twins_join_its_row_and_it_is_known_by_id_not_by_object():
    picture = _image("i1", "a fox", seed=1)
    index = gallery.build_image_config_index([picture])
    current = _video("v1", "the fox runs", noise_seed=5, frame="i1.png", act="alpha")
    twin = _video("v2", "the fox runs", noise_seed=6, frame="i1.png", act="alpha")

    around = surroundings(dict(current), [picture, current, twin], image_index=index)

    assert _ids(around.seeds) == ["v2"]


def test_a_video_made_from_no_picture_the_library_holds_keeps_its_own_folder_as_its_row():
    current = _video("v1", "the fox runs", noise_seed=5, frame="gone.png", act="alpha")
    reroll = _video("v2", "the fox runs", noise_seed=6, frame="gone.png", act="alpha")

    around = surroundings(current, [current, reroll], image_index={})

    assert (_ids(around.seeds), around.actions, around.label) == (["v2"], (), "alpha")


def test_an_action_loop_plays_the_picture_and_every_video_of_it_twins_included():
    picture = _image("i1", "a fox", seed=1)
    index = gallery.build_image_config_index([picture])
    runs = _video("v1", "the fox runs", noise_seed=5, frame="i1.png", act="alpha")
    runs_again = _video("v2", "the fox runs", noise_seed=6, frame="i1.png", act="alpha")
    sleeps = _video("v3", "the fox sleeps", noise_seed=7, frame="i1.png", act="beta")

    around = surroundings(runs, [picture, runs, runs_again, sleeps], image_index=index)

    assert _ids(around.group) == ["i1", "v2", "v3"]


# --- what an act filter matches a generation on --------------------------------


def test_the_whole_library_says_what_each_generation_is_named_for():
    source = _image("i1", "a fox in a beta form", seed=1)
    plain = _image("i2", "a fox", seed=2)
    index = gallery.build_image_config_index([source, plain])
    runs = _video("v1", "the fox runs", noise_seed=5, frame="i1.png", act="alpha")

    assert act_labels([source, plain, runs], image_index=index) == {
        "i1": "Source image, beta", "i2": "", "v1": "alpha"}


# --- "more seeds": what lies just beyond the row -------------------------------


def test_beyond_a_videos_row_lie_videos_of_its_act_from_the_pictures_most_like_its_own():
    own = _image("i1", "a red fox sleeping in deep snow", seed=1)
    alike = _image("i2", "a red fox sleeping in snow", seed=2)
    unlike = _image("i3", "a blue car parked by the harbor", seed=3)
    index = gallery.build_image_config_index([own, alike, unlike])
    current = _video("v1", "it runs", noise_seed=1, frame="i1.png", act="alpha")
    far = _video("v2", "it runs", noise_seed=2, frame="i3.png", act="alpha")
    near = _video("v3", "it runs", noise_seed=3, frame="i2.png", act="alpha")
    another_act = _video("v4", "it sleeps", noise_seed=4, frame="i2.png", act="beta")

    beyond = beyond_the_row(current, [own, alike, unlike, current, far, near, another_act],
                            image_index=index)

    assert _ids(beyond) == ["v3", "v2"]


def test_no_more_than_six_lie_beyond_a_row_however_many_are_near():
    current = _image("g0", "a red fox in snow", seed=0)
    alike = [_image(f"n{n}", "a red fox in snow at dawn", seed=n, steps=20 + n)
             for n in range(9)]

    assert len(beyond_the_row(current, [current, *alike], image_index={})) == 6


def test_nothing_lies_beyond_a_row_when_the_model_holds_nothing_else():
    current = _image("g1", "a red fox in snow", seed=1)
    sibling = _image("g2", "a red fox in snow", seed=2)
    other_model = _image("g3", "a red fox in snow", seed=3, checkpoint="model_b.safetensors")

    assert beyond_the_row(current, [current, sibling, other_model], image_index={}) == []


def test_a_generation_with_no_prompt_words_is_as_far_from_every_other_as_can_be():
    current = _image("g1", "", seed=1)
    wordy = _image("g3", "a red fox in snow", seed=3, steps=20)
    wordless = _image("g2", "", seed=2, steps=30)

    beyond = beyond_the_row(current, [current, wordy, wordless], image_index={})

    assert _ids(beyond) == ["g2", "g3"]      # nothing to tell them apart but their ids


def test_the_lora_that_animated_a_video_comes_before_a_likelier_picture():
    own = _image("i1", "a red fox sleeping in deep snow", seed=1)
    alike = _image("i2", "a red fox sleeping in snow", seed=2)
    unlike = _image("i3", "a blue car parked by the harbor", seed=3)
    index = gallery.build_image_config_index([own, alike, unlike])
    current = _video("v1", "it runs", noise_seed=1, frame="i1.png", act="alpha")
    likelier_picture = _video("v2", "it runs", noise_seed=2, frame="i2.png", act="alpha",
                              lora="lora_b")
    same_lora = _video("v3", "it runs", noise_seed=3, frame="i3.png", act="alpha")

    beyond = beyond_the_row(current, [own, alike, unlike, current, likelier_picture, same_lora],
                            image_index=index)

    assert _ids(beyond) == ["v3", "v2"]


def test_a_run_of_generations_from_one_folder_is_stood_for_by_the_newest_of_them():
    """A shelf lists newest first, and a sitting usually makes several seeds of
    one configuration in a row: the shelf's show plays the newest of each such
    run, and a folder come back to later is a run of its own."""
    newest_first = [_image("g5", "a red fox", seed=5), _image("g4", "a red fox", seed=4),
                    _image("g3", "a blue car", seed=3),
                    _image("g2", "a red fox", seed=2), _image("g1", "a red fox", seed=1)]

    assert _ids(one_per_stretch(newest_first, image_index={})) == ["g5", "g3", "g2"]


def test_an_enhanced_version_belongs_to_its_run_like_any_other_item():
    """A better version of a picture is still one of that folder's stretch, so
    it neither escapes the run nor breaks it in two."""
    better = _image("g3", "a red fox", seed=2)
    better["params_json"] = json.dumps({**json.loads(better["params_json"]), "enhance": True})
    newest_first = [_image("g4", "a red fox", seed=4), better,
                    _image("g2", "a red fox", seed=2), _image("g1", "a red fox", seed=1)]

    assert _ids(one_per_stretch(newest_first, image_index={})) == ["g4"]


# --- the column: this seed's other configurations, then the videos of it ---------


def test_the_column_opens_on_the_same_seed_under_other_configurations():
    """What the column showed before the videos joined it, and still shows
    first: the same seed drawn under another configuration of the same model."""
    current = _image("g1", "a red fox in snow", seed=7)
    tweaked = _image("g2", "a red fox at dawn", seed=7)
    other_model = _image("g3", "a red fox at dawn", seed=7, checkpoint="model_b.safetensors")
    reroll = _image("g4", "a red fox in snow", seed=8)

    around = surroundings(current, [current, tweaked, other_model, reroll], image_index={})

    assert _ids(around.configs) == ["g2"]


def test_a_configuration_sibling_is_not_also_one_of_the_acts_below_it():
    """The two halves of the column are told apart by where they sit, so a
    picture's own re-prompt is a configuration and never an act as well."""
    picture = _image("i1", "a fox", seed=1)
    tweaked = _image("i2", "a fox at dawn", seed=1)
    index = gallery.build_image_config_index([picture, tweaked])
    runs = _video("v1", "the fox runs", noise_seed=5, frame="i1.png", act="alpha")

    around = surroundings(picture, [picture, tweaked, runs], image_index=index)

    assert _ids(around.configs) == ["i2"]
    assert [(row["prompt_id"], label) for row, label in around.actions] == [("v1", "alpha")]


def test_a_video_has_no_configurations_of_its_own_because_its_seed_is_its_pictures():
    """Configurations belong to pictures.  A video's own sampler seed says
    nothing about which picture it is of, so two videos that happen to share
    one are strangers; what another configuration of this video's picture
    would be is a video of that picture, which the acts below already are."""
    picture = _image("i1", "a fox", seed=1)
    other_picture = _image("i2", "a hare", seed=2)
    index = gallery.build_image_config_index([picture, other_picture])
    current = _video("v1", "it runs", noise_seed=5, frame="i1.png", act="alpha")
    elsewhere = _video("v2", "it runs", noise_seed=5, frame="i2.png", act="alpha")

    around = surroundings(current, [picture, other_picture, current, elsewhere],
                          image_index=index)

    assert around.configs == ()
