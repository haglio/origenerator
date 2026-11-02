from __future__ import annotations

import json

from origenerator.gallery.tree import placeable_rows
from origenerator.generation_state import GenerationSource


def _row(prompt_id, **kw):
    base = {
        "prompt_id": prompt_id,
        "workflow_name": "sdxl_t2i",
        "params_json": "{}",
        "output_files": json.dumps([f"{prompt_id}.png"]),
        "status": "completed",
    }
    base.update(kw)
    return base


def test_a_re_derived_base_render_earns_no_place_beside_the_image_it_repairs():
    rows = [_row("keep"), _row("repair", source=GenerationSource.BASE_RENDER)]
    assert [row["prompt_id"] for row in placeable_rows(rows)] == ["keep"]


def test_a_rejected_experiment_whose_files_went_to_the_trash_has_no_place():
    rows = [_row("keep"), _row("rejected", output_files=None, status="rejected")]
    assert [row["prompt_id"] for row in placeable_rows(rows)] == ["keep"]
