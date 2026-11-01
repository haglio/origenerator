"""Which finished videos stand as the sample for each animation, and the order
the 72 are worked through.

Acts and states are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json

import pytest

from origenerator import animation_samples
from origenerator.action_settings import GENAU, VIDEO

_PATHS = {
    "animation_paths": {
        VIDEO: {"alpha": ["state one", "state two"], "beta": ["state two"]},
        GENAU: {"alpha": ["state two"]},
    },
}


def _image(prompt_id, state, filename=None):
    return {
        "prompt_id": prompt_id, "workflow_name": "sdxl_t2i", "status": "completed",
        "positive_prompt": "scene one", "params_json": "{}",
        "image_state": state,
        "output_files": json.dumps([{"filename": filename or f"{prompt_id}.png"}]),
    }


def _video(prompt_id, *, made_from, act="alpha", workflow="wan22_i2v",
          created="2026-01-01 00:00:00", **marks):
    return {
        "prompt_id": prompt_id, "workflow_name": workflow, "status": "completed",
        "positive_prompt": f"a scene, {act}", "act": act,
        "params_json": json.dumps({"input_image": f"{made_from}.png [output]"}),
        "output_files": json.dumps([{"filename": f"{prompt_id}.mp4"}]),
        "created_at": created, **marks,
    }


@pytest.fixture
def samples():
    def build(rows):
        return animation_samples.samples_by_path(rows, content=_PATHS)

    return build


def test_a_kept_clip_stands_as_the_example_for_its_act_and_its_images_state(samples):
    rows = [_image("pic", "state one"), _video("clip", made_from="pic", starred=1)]

    found = samples(rows)

    assert list(found) == [(VIDEO, "alpha", "state one")]
    assert [row["prompt_id"] for row in found[(VIDEO, "alpha", "state one")]] == ["clip"]


@pytest.mark.parametrize("mark", [
    {"starred": 1},
    {"genau_exported_at": "2026-01-02 00:00:00"},
    {"evolver_exported_at": "2026-01-02 00:00:00"},
])
def test_every_way_of_keeping_a_clip_counts(samples, mark):
    rows = [_image("pic", "state one"), _video("clip", made_from="pic", **mark)]

    assert samples(rows)


def test_a_clip_nobody_kept_is_no_example(samples):
    rows = [_image("pic", "state one"), _video("clip", made_from="pic")]

    assert samples(rows) == {}


def test_a_clip_whose_image_nobody_sorted_is_no_example_yet(samples):
    rows = [_image("pic", None), _video("clip", made_from="pic", starred=1)]

    assert samples(rows) == {}


def test_only_a_looping_clip_is_an_example_for_the_loop_lane(samples):
    rows = [
        _image("pic", "state two"),
        _video("long", made_from="pic", starred=1),
        _video("loop", made_from="pic", starred=1, workflow="wan22_flf2v_loop"),
    ]

    found = samples(rows)

    assert [row["prompt_id"] for row in found[(GENAU, "alpha", "state two")]] == ["loop"]
    assert sorted(row["prompt_id"] for row in found[(VIDEO, "alpha", "state two")]) == [
        "long", "loop"]


def test_an_animation_the_table_rules_out_gets_no_example_however_it_was_made(samples):
    # A video of an act its own image cannot start is a video made before the
    # image was sorted, or sorted since: the table is what decides.
    rows = [_image("pic", "state one"), _video("clip", made_from="pic", act="beta",
                                              starred=1)]

    assert samples(rows) == {}


def test_the_newest_kept_clip_leads(samples):
    rows = [
        _image("pic", "state one"),
        _video("older", made_from="pic", starred=1, created="2026-01-01 00:00:00"),
        _video("newest", made_from="pic", starred=1, created="2026-02-01 00:00:00"),
    ]

    found = samples(rows)[(VIDEO, "alpha", "state one")]

    assert [row["prompt_id"] for row in found] == ["newest", "older"]


# --- the order the 72 are worked through -------------------------------------


def test_the_animations_with_the_most_kept_clips_come_first(samples):
    rows = [
        _image("one", "state one"), _image("two", "state two"),
        _video("a", made_from="two", act="beta", starred=1),
        _video("b", made_from="two", act="beta", starred=1),
        _video("c", made_from="one", act="alpha", starred=1),
    ]

    order = animation_samples.paths_in_order(rows, content=_PATHS)

    assert order[0] == (VIDEO, "beta", "state two")
    assert order[1] == (VIDEO, "alpha", "state one")


def test_the_animations_with_nothing_behind_them_fall_to_the_end(samples):
    rows = [_image("one", "state one"), _video("c", made_from="one", starred=1)]

    order = animation_samples.paths_in_order(rows, content=_PATHS)

    assert order[0] == (VIDEO, "alpha", "state one")
    assert len(order) == 4  # every animation the table holds, none dropped


def test_animations_nothing_separates_keep_the_tables_own_order(samples):
    order = animation_samples.paths_in_order([], content=_PATHS)

    assert order == [
        (VIDEO, "alpha", "state one"),
        (VIDEO, "alpha", "state two"),
        (VIDEO, "beta", "state two"),
        (GENAU, "alpha", "state two"),
    ]
