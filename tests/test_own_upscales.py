from __future__ import annotations

import json
import os

from origenerator import library_views
from origenerator.db import Database
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
