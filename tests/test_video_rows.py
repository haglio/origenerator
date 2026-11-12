from __future__ import annotations

import json

import pytest

from origenerator.video_rows import VideoRows


def _made_here(prompt_id: str, *filenames: str) -> dict:
    return {"prompt_id": prompt_id,
            "output_files": json.dumps([{"filename": name, "subfolder": "video"}
                                        for name in filenames])}


@pytest.mark.parametrize("filed_as", [
    "alpha_00007_.mp4", "alpha_00007_-audio.mp4", "alpha_00007__topaz.mp4",
    "alpha_00007_-audio_topaz.mp4", "alpha_00007_-audio_topaz (2).mp4",
    "alpha_00007_ (3)_topaz_cfr.mp4", "alpha_00007_-audio_apo8_iris2.mp4", "ALPHA_00007_-AUDIO.MP4",
])
def test_a_copy_the_library_made_of_a_video_finds_the_row_that_made_it(tmp_path, filed_as):
    rows = VideoRows([_made_here("gen-1", "alpha_00007_.mp4"), _made_here("gen-2", "beta_00007_.mp4")])

    assert rows(tmp_path / "kino" / filed_as) == "gen-1"


def test_a_row_whose_kept_copy_is_the_one_with_sound_is_found_by_the_name_without_it(tmp_path):
    rows = VideoRows([_made_here("gen-1", "alpha_00007_-audio.mp4")])

    assert rows(tmp_path / "kino" / "alpha_00007__topaz.mp4") == "gen-1"


def test_a_name_no_row_was_made_with_finds_none(tmp_path):
    assert VideoRows([_made_here("gen-1", "alpha_00007_.mp4")])(tmp_path / "alpha_00008_.mp4") is None
