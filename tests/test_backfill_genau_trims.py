"""Cutting the clips that went to Genau whole, after the fact.

The command decides nothing: which clips are owed a cut and how one is made are
:mod:`origenerator.stroke_trim`, tested in tests/test_stroke_trim.py against a
real clip. What is left to hold here is that the command asks that module rather
than a second opinion of its own, that a report is only a report, and that a run
that could not cut a clip says so and exits non-zero.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
import json
from pathlib import Path

import pytest

from origenerator.db import Database
from origenerator.stroke_trim import NoSingleStroke
from tools import backfill_genau_trims as backfill_tool


def _clip(db, prompt_id, *, sent=None, filename=None):
    db.insert_generation(
        prompt_id=prompt_id, workflow_name="wan22_flf2v_loop", workflow_version="v006",
        positive_prompt="alpha", seed=3, params_json="{}", workflow_json="{}")
    db.update_generation(prompt_id, status="completed", output_files=json.dumps(
        [{"filename": filename or f"{prompt_id}.mp4", "subfolder": "video",
          "type": "output"}]))
    if sent:
        db.mark_genau_exported(prompt_id)
    return db.get_generation(prompt_id)


@pytest.fixture
def library(tmp_path, monkeypatch):
    """Two clips sent to Genau and one never sent, with the cutting stubbed and
    every clip's file resolving."""
    db = Database(tmp_path / "t.db")
    _clip(db, "sent1", sent=True)
    _clip(db, "sent2", sent=True)
    _clip(db, "kept")
    monkeypatch.setattr(backfill_tool, "resolve_preview",
                        lambda row, out: (Path(f"C:/out/{row['prompt_id']}.mp4"), "video"))
    cut = []
    monkeypatch.setattr(backfill_tool, "single_stroke_clip",
                        lambda row, path, db, **kw: cut.append(row["prompt_id"])
                        or Path(f"C:/out/{row['prompt_id']}_stroke.mp4"))
    return db, tmp_path / "t.db", cut


def test_a_report_names_the_clips_and_cuts_nothing(library, capsys):
    _db, path, cut = library

    assert backfill_tool.main(["--db", str(path)]) == 0

    out = capsys.readouterr().out
    assert "2 clip(s) sent to Genau with no single-stroke cut" in out
    assert "sent1.mp4" in out and "sent2.mp4" in out
    assert "kept.mp4" not in out          # never went down the lane
    assert cut == []                      # a report is a report


def test_applying_cuts_every_clip_that_went_whole(library, capsys):
    _db, path, cut = library

    assert backfill_tool.main(["--db", str(path), "--apply"]) == 0

    assert cut == ["sent1", "sent2"]
    assert "cut 2 clip(s); 0 left alone" in capsys.readouterr().out


def test_a_limit_stops_after_that_many(library):
    _db, path, cut = library

    backfill_tool.main(["--db", str(path), "--apply", "--limit", "1"])

    assert cut == ["sent1"]


def test_a_clip_with_no_whole_stroke_is_left_alone_and_the_run_says_so(
        library, monkeypatch, capsys):
    # It is left in the library exactly as it was, and the exit code is non-zero
    # so a scripted run cannot read "nothing to do" off a run that could not.
    _db, path, _cut = library

    def no_stroke(*_args, **_kwargs):
        raise NoSingleStroke("no whole stroke")

    monkeypatch.setattr(backfill_tool, "single_stroke_clip", no_stroke)

    assert backfill_tool.main(["--db", str(path), "--apply"]) == 1

    out = capsys.readouterr().out
    assert "not cut: no whole stroke" in out
    assert "cut 0 clip(s); 2 left alone" in out


def test_a_clip_whose_file_is_gone_is_left_alone(library, monkeypatch, capsys):
    _db, path, cut = library
    monkeypatch.setattr(backfill_tool, "resolve_preview", lambda row, out: None)

    assert backfill_tool.main(["--db", str(path), "--apply"]) == 1

    assert cut == []
    assert "no video file on disk" in capsys.readouterr().out
