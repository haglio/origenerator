"""Cutting a clip down to the one stroke Genau plays it as.

The arithmetic is tested on funscripts written here rather than measured off a
clip: a script is the whole of what the cut is decided from, so a literal one
says exactly which case is under test. The two tests that run ffmpeg for real are
skipped where it isn't installed (the Windows CI image has none); what they
cover that nothing else can — the cut starting on the frame the stroke turns on —
is pinned everywhere else by the command test below, which is the half that
would break silently.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from origenerator import stroke_trim
from origenerator.db import Database
from origenerator.funscript import read_actions, write_funscript
from origenerator.stroke_trim import (
    NoSingleStroke,
    single_stroke_clip,
    single_stroke_span,
    windowed_actions,
)

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg is not installed here")


def _actions(*pairs):
    return [{"at": at, "pos": pos} for at, pos in pairs]


# --- finding the one stroke ---------------------------------------------------


def test_a_metronome_script_gives_its_first_whole_period():
    # The synthesized script alternates extremes from the bottom, so the first
    # whole stroke is its first two half-periods.
    span = single_stroke_span(_actions((0, 0), (500, 100), (1000, 0), (1500, 100),
                                       (2000, 0)))
    assert span == (0, 1000)


def test_a_clip_that_opens_at_the_top_is_cut_from_its_first_bottom():
    """The authored stroke starts at the top of its travel, so its first frames
    are the back half of a stroke. Genau parks the device at the bottom and shows
    the frame the clip begins on, so a cut has to begin on a bottom — the leading
    half is dropped rather than sent as the start of a stroke."""
    span = single_stroke_span(_actions((0, 100), (400, 0), (800, 100), (1200, 0)))
    assert span == (400, 1200)


def test_shaping_points_inside_a_half_stroke_are_not_turns():
    """An authored script carries a point partway through each half-stroke (the
    easing into the reversal). Reading those as extremes would cut a quarter of a
    stroke and call it one."""
    span = single_stroke_span(_actions(
        (0, 0), (275, 82), (500, 100), (775, 18), (1000, 0)))
    assert span == (0, 1000)


def test_the_fullest_stroke_wins_over_an_earlier_short_one():
    """The authored stroke lands short of the extreme now and then, on purpose.
    A stroke that ends somewhere other than it began loops with a jump, so the
    one that travels furthest is both the truest single stroke and the tidiest
    loop — even when a shorter one comes first."""
    span = single_stroke_span(_actions(
        (0, 20), (300, 70), (600, 15), (900, 100), (1200, 0)))
    assert span == (600, 1200)


def test_ties_keep_the_earliest_stroke():
    span = single_stroke_span(_actions((0, 0), (500, 100), (1000, 0), (1500, 100),
                                       (2000, 0)))
    assert span == (0, 1000)


def test_a_hold_at_the_top_turns_at_the_end_of_the_hold():
    span = single_stroke_span(_actions((0, 0), (400, 100), (600, 100), (1000, 0)))
    assert span == (0, 1000)


@pytest.mark.parametrize("actions", [
    None,
    [],
    _actions((0, 0)),
    _actions((0, 0), (500, 100)),            # out, and never back
    _actions((0, 100), (500, 0)),            # back, and never out again
    _actions((0, 50), (500, 50), (1000, 50)),  # no travel at all
], ids=["none", "empty", "one-action", "half-stroke", "trailing-half", "flat"])
def test_a_clip_with_no_whole_stroke_has_no_span(actions):
    assert single_stroke_span(actions) is None


def test_windowed_actions_rebase_the_span_and_keep_both_ends():
    windowed = windowed_actions(
        _actions((0, 100), (400, 0), (800, 100), (1200, 0), (1600, 100)), 400, 1200)
    assert windowed == _actions((0, 0), (400, 100), (800, 0))


# --- the cut itself -----------------------------------------------------------


def test_the_cut_command_seeks_accurately_and_re_encodes(tmp_path, monkeypatch):
    """``-ss``/``-t`` must come AFTER the input, and the video must be re-encoded.

    Both halves of the same fact: a stream copy, or a seek placed before the
    input, can only start on a keyframe, so the cut would open on some frame near
    the turnaround rather than on it. Nothing about the file would look wrong —
    it is the one failure of this feature that has no symptom but a stroke that
    doesn't line up.
    """
    calls = []
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: calls.append((cmd, kw)) or None)
    monkeypatch.setattr(stroke_trim.shutil, "which", lambda _name: "ffmpeg")

    stroke_trim.cut_video(tmp_path / "in.mp4", tmp_path / "out.mp4", 400, 1200)

    cmd, kwargs = calls[0]
    assert cmd[cmd.index("-ss") - 2:cmd.index("-ss")] == ["-i", str(tmp_path / "in.mp4")]
    assert cmd[cmd.index("-ss") + 1] == "0.400000"
    assert cmd[cmd.index("-t") + 1] == "0.800000"   # a duration, not an end time
    assert "copy" not in cmd
    assert kwargs["check"] is True
    # A console window per cut would flash over whatever the user is doing.
    assert "creationflags" in kwargs or "startupinfo" in kwargs


def test_a_missing_ffmpeg_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(stroke_trim.shutil, "which", lambda _name: None)
    with pytest.raises(FileNotFoundError, match="ffmpeg"):
        stroke_trim.cut_video(tmp_path / "in.mp4", tmp_path / "out.mp4", 0, 100)


# --- which clips a backfill still owes a cut ---------------------------------


def _sent(prompt_id, at, **extra):
    return {"prompt_id": prompt_id, "genau_exported_at": at, **extra}


def test_the_clips_owed_a_cut_are_the_ones_sent_before_the_lane_cut():
    rows = [
        _sent("sent-late", "2026-08-19 15:50:34"),
        _sent("sent-early", "2026-08-18 09:55:38"),
        {"prompt_id": "never-sent"},
        _sent("already-cut", "2026-08-19 06:48:19"),
        # The cut of that one -- itself sent, and itself never cut again.
        _sent("its-cut", "2026-08-19 06:49:00", trimmed_from="already-cut"),
    ]

    owed = stroke_trim.clips_sent_whole(rows)

    # Oldest send first: a backfill stopped halfway should have got through the
    # clips that have been wrong the longest.
    assert [r["prompt_id"] for r in owed] == ["sent-early", "sent-late"]


def test_a_backfill_run_twice_has_nothing_left_to_do():
    rows = [_sent("clip", "2026-08-18 09:55:38"),
            _sent("cut", "2026-08-18 09:56:00", trimmed_from="clip")]
    assert stroke_trim.clips_sent_whole(rows) == []


# --- the cut as a row of the library ------------------------------------------


FPS = 16.0
FRAMES = 16


def _write_clip(path: Path):
    """A 16-frame second of video whose every frame is a different shade, so a
    cut of it can be checked frame by frame."""
    import cv2
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (64, 64))
    for i in range(FRAMES):
        frame = np.zeros((64, 64, 3), np.uint8)
        frame[:, :] = (i * 16, 0, 255 - i * 16)
        writer.write(frame)
    writer.release()


def _shades(path: Path) -> list[int]:
    import cv2

    cap = cv2.VideoCapture(str(path))
    shades = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        shades.append(int(frame[32, 32, 0]))
    cap.release()
    return shades


@pytest.fixture
def library(tmp_path):
    """An output dir holding one four-stroke clip and its script, a thumbnail
    dir, a database, and the clip's row."""
    output_dir = tmp_path / "output"
    clip = output_dir / "video" / "flf2v_loop_00001_.mp4"
    _write_clip(clip)
    # Two whole strokes over the second: top, bottom, top, bottom, top.
    write_funscript(
        output_dir / "funscript" / "flf2v_loop_00001_.funscript",
        _actions((0, 100), (250, 0), (500, 100), (750, 0), (1000, 100)))
    db = Database(tmp_path / "t.db")
    params = json.dumps({"positive_prompt": "alpha", "seed": 7})
    db.insert_generation(
        prompt_id="clip1", workflow_name="wan22_flf2v_loop", workflow_version="v006",
        positive_prompt="alpha", seed=7, params_json=params, workflow_json="{}")
    db.update_generation("clip1", status="completed", output_files=json.dumps(
        [{"filename": clip.name, "subfolder": "video", "type": "output"}]))
    return db, db.get_generation("clip1"), clip, output_dir, tmp_path / "thumbs"


@needs_ffmpeg
def test_the_cut_holds_one_stroke_and_starts_where_it_turns(library):
    db, row, clip, output_dir, thumbs = library

    cut = single_stroke_clip(row, clip, db, output_dir=output_dir, thumb_dir=thumbs)

    # The script's stroke runs 250-750 ms, which at 16 fps is frames 4 through 11.
    assert cut.name == "flf2v_loop_00001__stroke.mp4"
    shades = _shades(cut)
    assert len(shades) == 8
    source = _shades(clip)
    assert min(range(FRAMES), key=lambda i: abs(source[i] - shades[0])) == 4
    assert min(range(FRAMES), key=lambda i: abs(source[i] - shades[-1])) == 11


@needs_ffmpeg
def test_the_cut_carries_the_stroke_it_was_cut_to(library):
    """The cut is a video in the gallery like any other, and the OSR2 drive reads
    a script off whatever is on screen. Windowing the source's is exact, where
    re-deriving one would be a second opinion about the same motion."""
    db, row, clip, output_dir, thumbs = library

    cut = single_stroke_clip(row, clip, db, output_dir=output_dir, thumb_dir=thumbs)

    assert read_actions(output_dir / "funscript" / f"{cut.stem}.funscript") == _actions(
        (0, 0), (250, 100), (500, 0))


@needs_ffmpeg
def test_the_cut_is_a_row_beside_the_clip_it_came_out_of(library):
    """Two videos, and the short one knows where it came from. Its params are the
    clip's, which is what puts the pair in one settings folder; ``trimmed_from``
    is the only thing that tells them apart, and is what the Generate tab's
    "Trimmed from" tile follows back."""
    db, row, clip, output_dir, thumbs = library

    cut = single_stroke_clip(row, clip, db, output_dir=output_dir, thumb_dir=thumbs)

    made = db.trim_of("clip1")
    assert made["trimmed_from"] == "clip1"
    assert made["source"] == stroke_trim.STROKE_TRIM_SOURCE
    assert made["status"] == "completed"
    assert made["params_json"] == row["params_json"]
    assert made["workflow_name"] == row["workflow_name"]
    assert json.loads(made["output_files"]) == [
        {"filename": cut.name, "subfolder": "video", "type": "output"}]
    assert Path(made["thumbnail_path"]).exists()


@needs_ffmpeg
def test_a_cut_is_listed_on_the_recents_shelf(library):
    """Where someone looks for what the app just made. A cut lands in the
    settings folder of the clip it came from rather than anywhere you would
    think to go looking, so left off this shelf there is nowhere at all that
    says it happened."""
    from origenerator.gallery import recent_generations

    db, row, clip, output_dir, thumbs = library
    single_stroke_clip(row, clip, db, output_dir=output_dir, thumb_dir=thumbs)

    listed = recent_generations(db.list_generations())

    cut = db.trim_of("clip1")
    assert [r["prompt_id"] for r in listed] == [cut["prompt_id"], "clip1"]


@needs_ffmpeg
def test_cutting_the_same_clip_again_hands_back_the_cut_it_already_has(library):
    """Pressing the button after a spoken send already went must not leave a
    second file and a second row for one clip."""
    db, row, clip, output_dir, thumbs = library

    first = single_stroke_clip(row, clip, db, output_dir=output_dir, thumb_dir=thumbs)
    again = single_stroke_clip(row, clip, db, output_dir=output_dir, thumb_dir=thumbs)

    assert again == first
    assert len([r for r in db.list_generations() if r.get("trimmed_from")]) == 1


def test_a_cut_is_sent_as_itself(library):
    """It is already one stroke; cutting it again would only copy it."""
    db, _row, clip, output_dir, thumbs = library
    cut_row = {"prompt_id": "cut1", "trimmed_from": "clip1"}

    assert single_stroke_clip(cut_row, clip, db,
                              output_dir=output_dir, thumb_dir=thumbs) == clip


def test_a_clip_with_no_script_is_not_cut_and_not_sent(library):
    """Sending it whole is the very thing the cut exists to stop, so this refuses
    with the sentence the dialog shows rather than falling back."""
    db, row, clip, output_dir, thumbs = library
    (output_dir / "funscript" / "flf2v_loop_00001_.funscript").unlink()

    with pytest.raises(NoSingleStroke, match="no stroke track"):
        single_stroke_clip(row, clip, db, output_dir=output_dir, thumb_dir=thumbs)


def test_a_clip_whose_script_holds_no_whole_stroke_is_not_cut(library):
    db, row, clip, output_dir, thumbs = library
    write_funscript(output_dir / "funscript" / "flf2v_loop_00001_.funscript",
                    _actions((0, 0), (500, 100)))

    with pytest.raises(NoSingleStroke, match="no whole stroke"):
        single_stroke_clip(row, clip, db, output_dir=output_dir, thumb_dir=thumbs)


def test_a_refused_cut_leaves_no_row_behind(library):
    db, row, clip, output_dir, thumbs = library
    (output_dir / "funscript" / "flf2v_loop_00001_.funscript").unlink()

    with pytest.raises(NoSingleStroke):
        single_stroke_clip(row, clip, db, output_dir=output_dir, thumb_dir=thumbs)

    assert db.trim_of("clip1") is None
