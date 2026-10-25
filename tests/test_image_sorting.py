"""Fixture values are fabricated throughout (see CLAUDE.md)."""
from __future__ import annotations

import json

from origenerator.gallery.enhance import enhance_file_stem
from origenerator.image_sorting import images_to_sort


def _row(prompt_id, filename, *, prompt="scene one", created="2026-01-01 00:00:00",
         state=None, **extra):
    files = [{"filename": filename, "subfolder": "", "type": "output"}] if filename else []
    return {
        "prompt_id": prompt_id, "workflow_name": "sdxl_t2i", "workflow_version": "v001",
        "status": "completed", "positive_prompt": prompt, "params_json": "{}",
        "output_files": json.dumps(files) if files else None,
        "created_at": created, "image_state": state, **extra,
    }


def _ids(rows):
    return [row["prompt_id"] for row in rows]


def test_only_finished_stills_nobody_has_sorted_are_offered():
    rows = [
        _row("still", "scene_00001_.png"),
        _row("sorted", "scene_00002_.png", state="state one"),
        _row("clip", "scene_00003_.mp4"),
        _row("no-file", None),
    ]

    assert _ids(images_to_sort(rows)) == ["still"]


def test_an_enhancement_waiting_to_be_folded_is_not_a_second_image_to_sort():
    rows = [
        _row("still", "scene_00001_.png"),
        _row("its-better-version", f"{enhance_file_stem()}_00001_.png"),
    ]

    assert _ids(images_to_sort(rows)) == ["still"]


def test_the_favorites_come_first_and_each_half_runs_newest_backwards():
    rows = [
        _row("plain-old", "a_00001_.png", created="2026-01-01 00:00:00"),
        _row("favorite-old", "b_00001_.png", created="2026-01-02 00:00:00", starred=1),
        _row("plain-new", "c_00001_.png", created="2026-01-03 00:00:00"),
        _row("favorite-new", "d_00001_.png", created="2026-01-04 00:00:00", starred=1),
    ]

    assert _ids(images_to_sort(rows)) == [
        "favorite-new", "favorite-old", "plain-new", "plain-old"]
