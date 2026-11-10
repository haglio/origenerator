from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing

from origenerator import library_views
from origenerator.db import Database
from origenerator.evolver_upscales import filed_at
from origenerator.own_upscales import mark_own_upscales


def _video_of_ours(tmp_path, db, prompt_id: str):
    video = tmp_path / "videos" / f"{prompt_id}.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"video")
    os.utime(video, (1_000, 1_000))
    db.insert_rows([{"prompt_id": prompt_id, "source": "generated", "workflow_name": "wan22_i2v",
                     "workflow_version": "1", "status": "completed", "params_json": "{}",
                     "workflow_json": "{}",
                     "output_files": json.dumps([{"filename": video.name, "path": str(video)}])}])
    return video


def _filed_upscale(tmp_path, monkeypatch, prompt_id: str):
    upscale = tmp_path / "kino" / "landscape" / "origenerator" / f"{prompt_id}_topaz.mp4"
    upscale.parent.mkdir(parents=True, exist_ok=True)
    upscale.write_bytes(b"video")
    monkeypatch.setattr(library_views.EvolverUpscales, "scan",
                        lambda *args: library_views.EvolverUpscales({prompt_id: upscale}))
    return upscale


def test_an_upscale_filed_for_one_of_our_videos_is_marked_on_its_row(tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    _video_of_ours(tmp_path, db, "video_one")
    upscale = _filed_upscale(tmp_path, monkeypatch, "video_one")

    marked = mark_own_upscales(db)

    assert marked == 1
    assert db.get_generation("video_one")["evolver_upscale"] == str(upscale)


def test_a_second_look_with_nothing_new_filed_writes_nothing(tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    _video_of_ours(tmp_path, db, "video_one")
    _filed_upscale(tmp_path, monkeypatch, "video_one")
    mark_own_upscales(db)
    version = db.library_version()

    marked = mark_own_upscales(db)

    assert marked == 0
    assert db.library_version() == version


def test_the_mark_carries_when_evolver_filed_the_upscale(tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    _video_of_ours(tmp_path, db, "video_one")
    upscale = _filed_upscale(tmp_path, monkeypatch, "video_one")

    mark_own_upscales(db)

    assert db.get_generation("video_one")["evolver_upscaled_at"] == filed_at(upscale).isoformat()


def test_a_mark_made_before_its_time_was_kept_is_given_the_time_on_the_next_look(
        tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    _video_of_ours(tmp_path, db, "video_one")
    upscale = _filed_upscale(tmp_path, monkeypatch, "video_one")
    with closing(sqlite3.connect(tmp_path / "test.db")) as conn, conn:
        conn.execute("UPDATE generations SET evolver_upscale = ? WHERE prompt_id = ?",
                     (str(upscale), "video_one"))

    marked = mark_own_upscales(db)

    assert marked == 1
    assert db.get_generation("video_one")["evolver_upscaled_at"] == filed_at(upscale).isoformat()


def test_an_upscale_filed_for_a_video_another_site_made_marks_nothing(tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    upscales_dir = tmp_path / "kino"
    upscale = upscales_dir / "landscape" / "example_site" / "video_one_topaz.mp4"
    upscale.parent.mkdir(parents=True)
    upscale.write_bytes(b"video")
    monkeypatch.setattr(library_views, "KINO_UPSCALES_DIR", upscales_dir)
    db.insert_rows([{"prompt_id": "video_one", "source": "imported",
                     "workflow_name": "imported", "workflow_version": "1",
                     "status": "completed", "params_json": "{}", "workflow_json": "{}",
                     "output_files": json.dumps([{"filename": upscale.name,
                                                  "path": str(upscale)}])}])
    before = db.get_generation("video_one")

    assert mark_own_upscales(db) == 0
    assert db.get_generation("video_one") == before


def test_a_video_of_ours_upscaled_after_a_newer_one_was_made_leads_latest(
        tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    _video_of_ours(tmp_path, db, "video_one")
    _video_of_ours(tmp_path, db, "video_two")
    with closing(sqlite3.connect(tmp_path / "test.db")) as conn, conn:
        conn.execute("UPDATE generations SET completed_at = ? WHERE prompt_id = ?",
                     ("2000-01-01T00:00:00+00:00", "video_one"))
        conn.execute("UPDATE generations SET completed_at = ? WHERE prompt_id = ?",
                     ("2000-01-02T00:00:00+00:00", "video_two"))
    _filed_upscale(tmp_path, monkeypatch, "video_one")

    mark_own_upscales(db)

    latest = library_views.LibrarySnapshot(db.list_generations()).recent_rows
    assert [row["prompt_id"] for row in latest] == ["video_one", "video_two"]
