from __future__ import annotations

import json

from origenerator.gallery import (
    ALL_KEY,
    all_group,
    build_gallery_tree,
    build_image_config_index,
    child_groups,
)
from origenerator.gallery.placement import Placement


def _image(prompt_id, checkpoint, *, steps=30, seed=1, starred=0):
    return {
        "prompt_id": prompt_id,
        "workflow_name": "sdxl_t2i",
        "status": "completed",
        "starred": starred,
        "params_json": json.dumps({"positive_prompt": "a lamp", "checkpoint": checkpoint,
                                   "steps": steps, "seed": seed}),
        "output_files": json.dumps([{"filename": f"sdxl_t2i_{prompt_id}.png"}]),
    }


def _library(rows):
    return all_group(build_gallery_tree(rows))


def _models(library):
    (workflow,) = child_groups(library)
    return {model.label: model for model in child_groups(workflow)}


def _placement(library):
    return Placement(library, build_image_config_index([]))


def test_all_and_every_folder_above_a_row_hold_it():
    rows = [_image("p1", "alpha.safetensors"), _image("p2", "beta.safetensors")]
    library = _library(rows)
    alpha = _models(library)["alpha"]

    placement = _placement(library)

    assert placement.held_by(ALL_KEY, rows) == rows
    assert placement.held_by(alpha.key, rows) == [rows[0]]
    assert placement.holds(alpha.key, "p1") and not placement.holds(alpha.key, "p2")


def test_a_deleted_row_is_held_by_the_folders_it_was_deleted_from():
    live = _image("p1", "alpha.safetensors")
    deleted = _image("p2", "alpha.safetensors", seed=2)
    library = _library([live, _image("p3", "beta.safetensors")])
    models = _models(library)

    placement = _placement(library)

    assert placement.held_by(models["alpha"].key, [deleted]) == [deleted]
    assert placement.held_by(models["beta"].key, [deleted]) == []


def test_a_tally_counts_a_row_once_in_every_folder_holding_it():
    rows = [_image("p1", "alpha.safetensors"), _image("p2", "alpha.safetensors", steps=40),
            _image("p3", "beta.safetensors")]
    library = _library(rows)
    models = _models(library)

    tally = _placement(library).tally(rows)

    assert tally[ALL_KEY] == 3
    assert tally[models["alpha"].key] == 2
    assert tally[models["beta"].key] == 1


def test_a_folder_favors_its_starred_rows_and_the_rows_of_favorite_folders_below_it():
    rows = [_image("p1", "alpha.safetensors", starred=1),
            _image("p2", "beta.safetensors"), _image("p3", "beta.safetensors", steps=40)]
    library = _library(rows)
    models = _models(library)
    (beta_lora,) = child_groups(models["beta"])
    beta_lora.favorite = True

    tally = _placement(library).tally_favorites(rows)

    assert tally[ALL_KEY] == 3
    assert tally[models["alpha"].key] == 1
    assert tally[models["beta"].key] == 2
    assert tally[beta_lora.key] == 0


def test_a_generation_the_tree_does_not_hold_is_no_favorite_of_its_folder():
    kept = _image("p1", "beta.safetensors")
    failed = {**_image("p2", "beta.safetensors", seed=2), "status": "error", "output_files": None}
    library = _library([kept])
    (beta_lora,) = child_groups(_models(library)["beta"])
    beta_lora.favorite = True

    assert _placement(library).tally_favorites([kept, failed])[ALL_KEY] == 1
