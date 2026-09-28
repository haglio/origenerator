from __future__ import annotations

import json
from functools import partial

import pytest
from app_support.funscript import read_actions

from origenerator import config, funscript_backfill
from origenerator.funscript import (
    funscript_of,
    funscript_path_for,
    resynthesize_funscript,
    synthesize_actions,
    video_duration_seconds,
    write_funscript,
)
from origenerator.funscript_backfill import backfill
from tests.media_files import write_mp4


class FakeDB:
    def __init__(self, rows):
        self._rows = rows

    def list_generations(self):
        return list(self._rows)


def _row(prompt_id, workflow_name, filename, subfolder=""):
    return {
        "prompt_id": prompt_id,
        "workflow_name": workflow_name,
        "output_files": json.dumps([{"filename": filename, "subfolder": subfolder}]),
        "thumbnail_path": None,
    }


def _recording_write(seen):
    def write(path, *, hz, output_dir):
        seen.append(path.name)
        dest = funscript_path_for(path, output_dir=output_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("{}", encoding="utf-8")
        return dest
    return write


def test_backfill_scripts_each_video_and_skips_images(tmp_path):
    (tmp_path / "v_i2v.mp4").write_bytes(b"v")
    (tmp_path / "v_loop.mp4").write_bytes(b"v")
    (tmp_path / "still.png").write_bytes(b"p")
    db = FakeDB([
        _row("1", "wan22_i2v", "v_i2v.mp4"),
        _row("2", "wan22_flf2v_loop", "v_loop.mp4"),
        _row("3", "sdxl_t2i", "still.png"),
    ])
    seen = []
    result = backfill(db, tmp_path, write=_recording_write(seen))

    assert sorted(seen) == ["v_i2v.mp4", "v_loop.mp4"]  # the still image isn't
    assert result["written"] == 2 and result["skipped"] == 0


def test_backfill_rewrites_the_scripts_synthesized_at_an_older_pace_and_says_how_many(tmp_path):
    for name in ("older_pace.mp4", "todays_pace.mp4"):
        (tmp_path / name).write_bytes(b"v")
    older = funscript_path_for(tmp_path / "older_pace.mp4", output_dir=tmp_path)
    write_funscript(older, synthesize_actions(5.0, hz=1.2))
    write_funscript(funscript_path_for(tmp_path / "todays_pace.mp4", output_dir=tmp_path),
                    synthesize_actions(5.0, hz=0.5))
    db = FakeDB([_row("1", "wan22_i2v", "older_pace.mp4"),
                 _row("2", "wan22_i2v", "todays_pace.mp4")])

    result = backfill(db, tmp_path, hz=0.5, rewrite=partial(
        resynthesize_funscript, duration_provider=lambda _video: 5.0))

    assert read_actions(older) == synthesize_actions(5.0, hz=0.5)
    assert (result["rewritten"], result["skipped"], result["written"]) == (1, 1, 0)


def test_backfill_is_idempotent(tmp_path):
    (tmp_path / "v.mp4").write_bytes(b"v")
    db = FakeDB([_row("1", "wan22_i2v", "v.mp4")])
    backfill(db, tmp_path, write=_recording_write([]))

    seen = []
    result = backfill(db, tmp_path, write=_recording_write(seen))
    assert result["written"] == 0 and result["skipped"] == 1


def test_videos_sharing_a_name_are_each_scripted_for_their_own_length(tmp_path):
    alpha = write_mp4(tmp_path / "alpha" / "clip.mp4", seconds=2.0)
    beta = write_mp4(tmp_path / "beta" / "one" / "clip.mp4", seconds=5.0)
    write_funscript(tmp_path / "funscript" / "clip.funscript",
                    synthesize_actions(2.0, hz=1.0))
    db = FakeDB([_row("1", "unknown", "clip.mp4", subfolder="alpha"),
                 _row("2", "unknown", "clip.mp4", subfolder="beta/one")])

    backfill(db, tmp_path, hz=1.0)

    for video in (alpha, beta):
        assert read_actions(funscript_of(video, output_dir=tmp_path)) == synthesize_actions(
            video_duration_seconds(video), hz=1.0)


def test_two_types_of_one_video_name_in_one_folder_are_each_scripted(tmp_path):
    for name in ("clip.mp4", "clip.webm"):
        (tmp_path / "alpha").mkdir(exist_ok=True)
        (tmp_path / "alpha" / name).write_bytes(b"v")
    write_funscript(tmp_path / "funscript" / "clip.funscript",
                    synthesize_actions(2.0, hz=1.0))
    seen = []

    result = backfill(FakeDB([_row("1", "unknown", "clip.mp4", subfolder="alpha"),
                              _row("2", "unknown", "clip.webm", subfolder="alpha")]),
                      tmp_path, write=_recording_write(seen))

    assert sorted(seen) == ["clip.mp4", "clip.webm"]
    assert result["written"] == 2


@pytest.mark.parametrize("older_place", ["under its name", "beside it"])
def test_a_video_no_other_shares_a_name_with_keeps_the_script_an_older_version_filed(
        tmp_path, older_place):
    """Writing it again in the video's own place would leave two scripts for one
    video, and only the reader's search order would say which of them wins."""
    video = tmp_path / "video" / "clip.mp4"
    video.parent.mkdir()
    video.write_bytes(b"v")
    older = {"under its name": tmp_path / "funscript" / "clip.funscript",
             "beside it": video.with_suffix(".funscript")}[older_place]
    older.parent.mkdir(exist_ok=True)
    older.write_text("keep me", encoding="utf-8")
    seen = []

    result = backfill(FakeDB([_row("1", "wan22_i2v", "clip.mp4", subfolder="video")]),
                      tmp_path, write=_recording_write(seen))

    assert seen == [] and result["skipped"] == 1
    assert older.read_text(encoding="utf-8") == "keep me"


@pytest.mark.parametrize("older_place", ["under its name", "beside it"])
def test_a_script_an_older_version_filed_at_another_pace_is_rewritten_where_it_is(
        tmp_path, older_place):
    video = tmp_path / "video" / "clip.mp4"
    video.parent.mkdir()
    video.write_bytes(b"v")
    older = {"under its name": tmp_path / "funscript" / "clip.funscript",
             "beside it": video.with_suffix(".funscript")}[older_place]
    write_funscript(older, synthesize_actions(5.0, hz=1.2))

    result = backfill(FakeDB([_row("1", "wan22_i2v", "clip.mp4", subfolder="video")]),
                      tmp_path, hz=0.5,
                      rewrite=partial(resynthesize_funscript, duration_provider=lambda _v: 5.0))

    assert result["rewritten"] == 1
    assert read_actions(older) == synthesize_actions(5.0, hz=0.5)
    assert not funscript_path_for(video, output_dir=tmp_path).exists()


def test_backfill_counts_a_video_whose_file_is_missing(tmp_path):
    db = FakeDB([_row("1", "wan22_i2v", "gone.mp4")])  # no file on disk
    seen = []
    result = backfill(db, tmp_path, write=_recording_write(seen))
    assert seen == []  # nothing to script
    assert result["missing"] == 1 and result["written"] == 0


def test_the_output_folder_is_resolved_when_the_sweep_runs(tmp_path, monkeypatch):
    """It was a signature default -- ``output_dir: Path = COMFYUI_OUTPUT_DIR`` --
    evaluated at import, from a constant that was itself built by reading the
    content overlay at import. So the sweep could not be pointed anywhere the
    module had not already decided on before anything called it."""
    monkeypatch.setattr(config, "COMFYUI_OUTPUT_DIR", tmp_path / "elsewhere")
    seen = []

    funscript_backfill.backfill(
        FakeDB([_row("gen-alpha", "wan22_i2v", "alpha.mp4")]),
        resolve=lambda row, output_dir: seen.append(output_dir) or None,
    )

    assert seen == [tmp_path / "elsewhere"]


def test_the_cadence_is_resolved_when_the_sweep_runs_too(tmp_path, monkeypatch):
    """The same defect on the same line: the motion rate was bound at import."""
    monkeypatch.setattr(config, "MOTION_DEFAULT_HZ", 2.5)
    clip = tmp_path / "alpha.mp4"
    clip.write_bytes(b"not really a video")
    rates = []

    funscript_backfill.backfill(
        FakeDB([_row("gen-alpha", "wan22_i2v", "alpha.mp4")]),
        resolve=lambda row, output_dir: (clip, "video"),
        write=lambda path, *, hz, output_dir: rates.append(hz) or None,
    )

    assert rates == [2.5]
