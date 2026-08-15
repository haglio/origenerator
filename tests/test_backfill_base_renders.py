"""Re-deriving the base render for images the inline enhance tail finished.

Those rows kept one file and no "before". The base is recoverable because it is
reproducible: the same seed and recipe with the tail off reproduces the pixels
that pass made the first time, and folding it in gives the row the
``Original`` / ``Enhance 1`` pair it should have had.
"""

import json

from origenerator import gallery
from origenerator.db import Database
from origenerator.workflows import WORKFLOW_REGISTRY
from tools.backfill_base_renders import (
    base_params_for, fold_base_into, rows_missing_their_base,
)

_SDXL = WORKFLOW_REGISTRY["sdxl_t2i"]


def _add(db, prompt_id, *, params, files, original_files=None, workflow="sdxl_t2i"):
    db.insert_generation(
        prompt_id=prompt_id, workflow_name=workflow, workflow_version="v004",
        positive_prompt=params.get("positive_prompt", ""), seed=params.get("seed"),
        params_json=json.dumps(params), workflow_json="{}",
    )
    fields = {"status": "completed", "output_files": json.dumps(files)}
    if original_files is not None:
        fields["original_files"] = json.dumps(original_files)
    db.update_generation(prompt_id, **fields)
    return db.get_generation(prompt_id)


def _file(name):
    return {"filename": name, "subfolder": "image", "type": "output"}


def test_it_picks_exactly_the_rows_that_lost_their_base(tmp_path):
    db = Database(tmp_path / "t.db")
    _add(db, "baked", params=dict(_SDXL.default_params(), enhance=True, seed=1),
         files=[_file("sdxl_t2i_a.png")])
    _add(db, "plain", params=dict(_SDXL.default_params(), enhance=False, seed=2),
         files=[_file("sdxl_t2i_b.png")])
    _add(db, "layered", params=dict(_SDXL.default_params(), enhance=False, seed=3),
         files=[_file("image_enhance_1.png"), _file("sdxl_t2i_c.png")],
         original_files=[_file("sdxl_t2i_c.png")])

    assert [r["prompt_id"] for r in rows_missing_their_base(db)] == ["baked"]


def test_an_unrebuildable_import_is_left_alone(tmp_path):
    # No registered template, so there is no recipe to re-run — and guessing
    # one would produce a "base" that is not this image's base at all.
    db = Database(tmp_path / "t.db")
    _add(db, "import", params={"enhance": True}, files=[_file("mystery.png")],
         workflow="unknown")
    assert rows_missing_their_base(db) == []


def test_the_rerun_is_the_recorded_recipe_with_the_tail_off(tmp_path):
    db = Database(tmp_path / "t.db")
    row = _add(db, "baked",
               params=dict(_SDXL.default_params(), enhance=True, seed=4242,
                           steps=37, cfg=6.5, positive_prompt="a lantern"),
               files=[_file("sdxl_t2i_a.png")])

    params = base_params_for(row, _SDXL)

    assert params["enhance"] is False   # the one thing that changes
    # Everything the pixels depend on is reproduced exactly, the seed above all.
    assert params["seed"] == 4242
    assert params["steps"] == 37
    assert params["cfg"] == 6.5
    assert params["positive_prompt"] == "a lantern"


def test_folding_the_base_in_gives_the_row_its_two_levels(tmp_path):
    db = Database(tmp_path / "t.db")
    row = _add(db, "baked", params=dict(_SDXL.default_params(), enhance=True, seed=1),
               files=[_file("sdxl_t2i_a.png")])

    fold_base_into(db, row, [_file("sdxl_t2i_a_base.png")])

    upgraded = db.get_generation("baked")
    # The enhanced file keeps its place at the head — it is still what the row
    # shows — and the base joins behind it as the original.
    assert [f["filename"] for f in gallery.row_output_files(upgraded)] == \
        ["sdxl_t2i_a.png", "sdxl_t2i_a_base.png"]
    assert [lvl.label for lvl in gallery.enhance_levels(upgraded)] == \
        ["Enhance 1", "Original"]
    assert gallery.original_files_of(upgraded)[0]["filename"] == "sdxl_t2i_a_base.png"


def test_a_folded_row_is_not_offered_again(tmp_path):
    # Interrupting the run is safe: each row is folded as it lands, and a
    # re-run picks up only what is left.
    db = Database(tmp_path / "t.db")
    row = _add(db, "baked", params=dict(_SDXL.default_params(), enhance=True, seed=1),
               files=[_file("sdxl_t2i_a.png")])
    fold_base_into(db, row, [_file("sdxl_t2i_a_base.png")])
    assert rows_missing_their_base(db) == []
