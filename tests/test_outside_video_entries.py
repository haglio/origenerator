from __future__ import annotations

import json
import os

from origenerator import config, gallery_contract, outside_video_entries
from origenerator.db import Database
from origenerator.generation_state import GenerationSource
from origenerator.outside_videos import Places
from tests.children import run_python
from tests.media_files import write_mp4


def _places(tmp_path) -> Places:
    return Places(upscaled_dir=tmp_path / "videos" / "outbox",
                  records_folder=tmp_path / "videos" / "metadata",
                  frames_dir=tmp_path / "frames", thumb_dir=tmp_path / "thumbs",
                  skip_sources=frozenset({"this-app"}), library_root=tmp_path, journal=None)


def _the_command(tmp_path, places: Places | None, logged_to: list | None = None) -> int:
    logged_to = [] if logged_to is None else logged_to
    return outside_video_entries.main(tmp_path / "origenerator.db", places=lambda: places,
                                      log_to=lambda *where: logged_to.append(where))


def _outside_videos(tmp_path) -> list[dict]:
    return [row for row in Database(tmp_path / "origenerator.db").list_generations()
            if row["source"] == GenerationSource.OUTSIDE and "library_path" in row["output_files"]]


def test_the_command_evolver_runs_writes_an_entry_for_a_video_evolver_filed_and_says_how_many(
        tmp_path, capsys):
    places = _places(tmp_path)
    filed = write_mp4(places.upscaled_dir / "portrait" / "a-site" / "scene one_topaz.mp4")

    assert _the_command(tmp_path, places) == 0

    assert json.loads(capsys.readouterr().out) == {"brought_in": 1}
    [video] = _outside_videos(tmp_path)
    assert json.loads(video["output_files"])[0]["library_path"] == str(filed)


def test_the_command_run_again_writes_nothing_twice(tmp_path, capsys):
    places = _places(tmp_path)
    write_mp4(places.upscaled_dir / "portrait" / "a-site" / "scene one_topaz.mp4")
    _the_command(tmp_path, places)
    capsys.readouterr()

    assert _the_command(tmp_path, places) == 0

    assert json.loads(capsys.readouterr().out) == {"brought_in": 0}
    assert len(_outside_videos(tmp_path)) == 1


def test_with_no_evolver_beside_this_app_the_command_writes_nothing(tmp_path, capsys):
    assert _the_command(tmp_path, None) == 0

    assert json.loads(capsys.readouterr().out) == {"brought_in": 0}
    assert Database(tmp_path / "origenerator.db").list_generations() == []


def test_the_command_writes_its_log_where_the_app_writes_its_own(tmp_path):
    logged_to = []

    _the_command(tmp_path, None, logged_to)

    assert logged_to == [("", config.STATE_DIR / "origenerator.log")]


def test_the_command_the_document_names_answers_in_its_last_line_when_evolver_runs_it(tmp_path):
    interpreter, *arguments = gallery_contract.declaration()["outside_video_entries_command"]

    answered = run_python(arguments, env={**os.environ, "ORIGENERATOR_STATE_DIR": str(tmp_path)})

    assert interpreter == ".venv/Scripts/python.exe"
    assert answered.returncode == 0, answered.stderr
    assert json.loads(answered.stdout.strip().splitlines()[-1]) == {"brought_in": 0}
    assert (tmp_path / "origenerator.log").is_file()
