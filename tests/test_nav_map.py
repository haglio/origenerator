"""The map around one generation: what shares its config, what shares its seed,
and what is nearest beyond that.

Fixture rows are fabricated (see CLAUDE.md); the settings-folder and model
keys they are grouped by are the gallery's own.
"""
from __future__ import annotations

import json

from origenerator import gallery
from origenerator.nav_map import config_family, seed_family, widened_family


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


def _video(prompt_id, prompt, *, noise_seed, frame, lora="lora_a"):
    """A WAN image-to-video row: its sampler seed is ``noise_seed``, so the
    ``seed`` column a picture fills stays empty on it."""
    return {
        "prompt_id": prompt_id,
        "workflow_name": "wan22_i2v",
        "positive_prompt": prompt,
        "seed": None,
        "params_json": json.dumps({
            "positive_prompt": prompt, "noise_seed": noise_seed, "input_image": frame,
            "unet_high": "wan_high.safetensors", "unet_low": "wan_low.safetensors",
            "lora_high": f"{lora}_high.safetensors", "lora_low": f"{lora}_low.safetensors",
        }),
        "output_files": json.dumps([{"filename": f"{prompt_id}.mp4"}]),
    }


def test_the_config_column_is_the_same_seed_under_other_settings_of_the_same_model():
    current = _image("g1", "a red fox in snow", seed=7)
    tweaked = _image("g2", "a red fox at dawn", seed=7)
    other_model = _image("g3", "a red fox at dawn", seed=7, checkpoint="model_b.safetensors")
    reroll = _image("g4", "a red fox in snow", seed=8)
    collision = _video("v1", "the fox runs", noise_seed=7, frame="g1.png")

    column = config_family(current, [tweaked, other_model, reroll, collision, current],
                           image_index={})

    assert _ids(column) == ["g1", "g2"]


def test_a_video_reads_its_seed_off_its_sampler_not_off_a_column_it_never_fills():
    picture = _image("i1", "a fox", seed=1)
    index = gallery.build_image_config_index([picture])
    current = _video("v1", "the fox runs", noise_seed=5, frame="i1.png")
    twin = _video("v2", "the fox sleeps", noise_seed=5, frame="i1.png")
    reroll = _video("v3", "the fox sleeps", noise_seed=6, frame="i1.png")

    assert _ids(config_family(current, [twin, reroll, current], image_index=index)) == ["v1", "v2"]
    assert _ids(seed_family(twin, [twin, reroll, current], image_index=index)) == ["v2", "v3"]


def test_widening_adds_the_nearest_other_configurations_of_the_same_model():
    current = _image("g1", "a red fox sleeping in deep snow", seed=1)
    sibling = _image("g2", "a red fox sleeping in deep snow", seed=2)
    near = _image("g3", "a red fox running in deep snow", seed=3)
    nearer = _image("g4", "a red fox sleeping in snow", seed=4)
    far = _image("g5", "a blue car parked by the harbor", seed=5)
    other_model = _image("g6", "a red fox sleeping in deep snow", seed=6,
                         checkpoint="model_b.safetensors")

    row = widened_family(current, [far, near, sibling, nearer, other_model, current],
                         image_index={})

    assert _ids(row) == ["g1", "g2", "g4", "g3", "g5"]


def test_no_more_than_six_join_however_many_are_near():
    current = _image("g0", "a red fox in snow", seed=0)
    alike = [_image(f"n{n}", "a red fox in snow at dawn", seed=n, steps=20 + n)
             for n in range(9)]

    row = widened_family(current, [current, *alike], image_index={})

    assert len(row) == 1 + 6


def test_there_is_no_wider_row_when_the_model_holds_nothing_else():
    current = _image("g1", "a red fox in snow", seed=1)
    sibling = _image("g2", "a red fox in snow", seed=2)
    other_model = _image("g3", "a red fox in snow", seed=3, checkpoint="model_b.safetensors")

    assert widened_family(current, [current, sibling, other_model], image_index={}) is None


def test_a_videos_own_source_picture_and_lora_come_before_a_likelier_prompt():
    pictures = [_image("i1", "a fox", seed=1), _image("i2", "a hare", seed=2)]
    index = gallery.build_image_config_index(pictures)
    current = _video("v1", "the fox runs through snow", noise_seed=1, frame="i1.png")
    same_picture = _video("v2", "the fox sits", noise_seed=2, frame="i1.png")
    other_lora = _video("v3", "the fox runs through snow", noise_seed=3, frame="i1.png",
                        lora="lora_b")
    other_picture = _video("v4", "the fox runs through snow", noise_seed=4, frame="i2.png")

    row = widened_family(current, [other_picture, other_lora, same_picture, current],
                         image_index=index)

    assert _ids(row) == ["v1", "v2", "v4", "v3"]


def test_a_generation_with_no_prompt_words_is_as_far_from_every_other_as_can_be():
    current = _image("g1", "", seed=1)
    wordy = _image("g3", "a red fox in snow", seed=3, steps=20)
    wordless = _image("g2", "", seed=2, steps=30)

    row = widened_family(current, [current, wordy, wordless], image_index={})

    assert _ids(row) == ["g1", "g2", "g3"]      # nothing to tell them apart but their ids
