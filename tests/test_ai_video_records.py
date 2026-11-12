from __future__ import annotations

import json
import os

from PIL import Image

from origenerator import ai_video_records, config, gallery_contract
from origenerator.db import Database
from origenerator.generation_state import GenerationSource
from origenerator.outside_videos import Places
from tests.children import run_python


def _places(tmp_path) -> Places:
    return Places(kino=tmp_path / "videos" / "videos" / "kino",
                  frames_dir=tmp_path / "frames", thumb_dir=tmp_path / "thumbs",
                  skip_sources=frozenset({"this-app"}), library_root=tmp_path)


def _filed(places: Places, name: str = "c1_topaz.mp4"):
    path = places.upscaled_dir / "portrait" / "a-site" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not really a video")
    return path


def _outside(db, prompt_id: str, video) -> None:
    db.insert_rows([{"prompt_id": prompt_id, "source": GenerationSource.OUTSIDE,
                     "workflow_name": "outside:a-site", "workflow_version": "outside",
                     "status": "completed", "params_json": "{}", "workflow_json": "{}",
                     "output_files": json.dumps([{"filename": video.name,
                                                  "library_path": str(video)}])}])


def _json_file(tmp_path, name: str, value) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return str(path)


def _run(tmp_path, capsys, *argv, logged_to=None) -> dict:
    logged_to = [] if logged_to is None else logged_to
    assert ai_video_records.main(list(argv), db_path=tmp_path / "origenerator.db",
                                 places=lambda: _places(tmp_path),
                                 grab=lambda _path: Image.new("RGB", (64, 96)),
                                 log_to=lambda *where: logged_to.append(where)) == 0
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def _the_gallery(tmp_path) -> Database:
    return Database(tmp_path / "origenerator.db")


def test_a_site_record_lands_on_its_videos_row(tmp_path, capsys):
    db = _the_gallery(tmp_path)
    video = _filed(_places(tmp_path))
    _outside(db, "o1", video)
    record = {"video": {"prompt": "a slow walk on the shore", "action": "Wave"},
              "web_url": "https://example.com/watch/1"}

    said = _run(tmp_path, capsys, "record", "--video", str(video),
                "--record", _json_file(tmp_path, "record.json", record))

    row = db.get_generation("o1")
    assert said == {"done": 1, "no_row": 0}
    assert (row["positive_prompt"], row["action"], row["web_url"]) == (
        "a slow walk on the shore", "Wave", "https://example.com/watch/1")


def test_a_site_record_of_a_video_with_no_row_brings_it_in(tmp_path, capsys):
    video = _filed(_places(tmp_path))

    said = _run(tmp_path, capsys, "record", "--video", str(video),
                "--record", _json_file(tmp_path, "record.json", {"video": {"prompt": "a run"}}))

    assert said == {"done": 1, "no_row": 0}
    assert [row["positive_prompt"] for row in _the_gallery(tmp_path).list_generations()
            if row["source"] == GenerationSource.OUTSIDE] == ["a run"]


def test_a_site_record_of_a_video_that_cannot_come_in_is_counted_as_having_no_row(
        tmp_path, capsys):
    elsewhere = tmp_path / "elsewhere" / "c1_topaz.mp4"

    said = _run(tmp_path, capsys, "record", "--video", str(elsewhere),
                "--record", _json_file(tmp_path, "record.json", {}))

    assert said == {"done": 0, "no_row": 1}


def test_watch_totals_land_on_each_videos_row_and_a_video_with_none_is_counted(tmp_path, capsys):
    db = _the_gallery(tmp_path)
    video = _filed(_places(tmp_path))
    _outside(db, "o1", video)
    totals = {str(video): {"completions": 3, "skips": 1, "locks": 2},
              str(tmp_path / "gone.mp4"): {"completions": 1}}

    said = _run(tmp_path, capsys, "watched", "--totals", _json_file(tmp_path, "totals.json", totals))

    row = db.get_generation("o1")
    assert said == {"done": 1, "no_row": 1}
    assert (row["watch_completions"], row["watch_skips"], row["watch_locks"]) == (3, 1, 2)


def test_the_phones_star_goes_on_and_comes_off(tmp_path, capsys):
    db = _the_gallery(tmp_path)
    video = _filed(_places(tmp_path))
    _outside(db, "o1", video)

    on = _run(tmp_path, capsys, "favorite", "--video", str(video), "--on")
    starred = db.get_generation("o1")["starred"]
    off = _run(tmp_path, capsys, "favorite", "--video", str(video), "--off")

    assert (on, starred, off, db.get_generation("o1")["starred"]) == (
        {"done": 1, "no_row": 0}, 1, {"done": 1, "no_row": 0}, 0)


def test_an_upscales_provenance_lands_on_the_row_of_the_video_it_upscaled(tmp_path, capsys):
    db = _the_gallery(tmp_path)
    video = _filed(_places(tmp_path))
    _outside(db, "o1", video)
    provenance = {"app": "an-upscaler", "model": "made-up"}

    said = _run(tmp_path, capsys, "upscaled", "--video", str(video),
                "--provenance", _json_file(tmp_path, "provenance.json", provenance))

    assert said == {"done": 1, "no_row": 0}
    assert json.loads(db.get_generation("o1")["upscale_provenance"]) == provenance


def test_a_star_for_a_video_with_no_row_is_counted_as_having_none(tmp_path, capsys):
    said = _run(tmp_path, capsys, "favorite", "--video", str(tmp_path / "gone.mp4"), "--on")

    assert said == {"done": 0, "no_row": 1}


def test_the_command_writes_its_log_where_the_app_writes_its_own(tmp_path, capsys):
    logged_to = []

    _run(tmp_path, capsys, "favorite", "--video", str(tmp_path / "gone.mp4"), "--off",
         logged_to=logged_to)

    assert logged_to == [("", config.STATE_DIR / "origenerator.log")]


def test_the_command_the_document_names_answers_in_its_last_line_when_evolver_runs_it(tmp_path):
    interpreter, *arguments = gallery_contract.declaration()["records_command"]

    answered = run_python([*arguments, "favorite", "--video", str(tmp_path / "gone.mp4"), "--on"],
                          env={**os.environ, "ORIGENERATOR_STATE_DIR": str(tmp_path)})

    assert interpreter == ".venv/Scripts/python.exe"
    assert answered.returncode == 0, answered.stderr
    assert json.loads(answered.stdout.strip().splitlines()[-1]) == {"done": 0, "no_row": 1}
