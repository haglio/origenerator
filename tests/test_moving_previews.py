"""A video's moving preview is made off the window's thread, one at a time.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json

from PyQt6.QtCore import QThread, QThreadPool

from origenerator.gui.moving_previews import MovingPreviews
from origenerator.output_places import OutputPlaces


def _on_disk(tmp_path, filename: str) -> dict:
    output = tmp_path / "output"
    output.mkdir(exist_ok=True)
    (output / filename).write_bytes(b"made somewhere")
    return {"prompt_id": filename.split(".", maxsplit=1)[0], "workflow_name": "wan22_i2v",
            "status": "completed", "params_json": "{}",
            "output_files": json.dumps([{"filename": filename, "subfolder": ""}])}


def _video(tmp_path, prompt_id: str) -> dict:
    return _on_disk(tmp_path, f"{prompt_id}.mp4")


class _Later:
    """Holds each piece of work a preview asks for until the test lets it run."""

    def __init__(self):
        self.waiting = []

    def __call__(self, work, done, *, owner):
        self.waiting.append((work, done))

    def finish_next(self):
        work, done = self.waiting.pop(0)
        done(work())


def _previews(tmp_path):
    later, asked = _Later(), []

    def make(row, _output_dir, thumb_dir):
        asked.append(row["prompt_id"])
        made = thumb_dir / f"{row['prompt_id']}_anim.webp"
        made.parent.mkdir(parents=True, exist_ok=True)
        made.write_bytes(b"a moving preview")
        return str(made)

    previews = MovingPreviews(OutputPlaces.in_one_folder(tmp_path / "output"), tmp_path / "thumbs", run=later, make=make)
    return previews, later, asked


def test_a_video_whose_moving_preview_is_made_gets_it_at_once(tmp_path):
    previews, later, asked = _previews(tmp_path)
    made = tmp_path / "thumbs" / "v1_anim.webp"
    made.parent.mkdir(parents=True)
    made.write_bytes(b"a moving preview")

    assert previews.of(_video(tmp_path, "v1")) == str(made)
    assert (later.waiting, asked) == ([], [])


def test_a_video_with_none_shows_its_still_while_one_is_made_off_the_window_thread(tmp_path):
    previews, later, asked = _previews(tmp_path)
    told = []
    previews.made.connect(lambda prompt_id, path: told.append((prompt_id, path)))

    assert previews.of(_video(tmp_path, "v1")) is None
    assert asked == []

    later.finish_next()

    assert told == [("v1", str(tmp_path / "thumbs" / "v1_anim.webp"))]
    assert previews.of(_video(tmp_path, "v1")) == str(tmp_path / "thumbs" / "v1_anim.webp")


def test_previews_are_made_one_at_a_time_the_latest_asked_for_first(tmp_path):
    previews, later, asked = _previews(tmp_path)

    for name in ("v1", "v2", "v3"):
        previews.of(_video(tmp_path, name))
    while later.waiting:
        assert len(later.waiting) == 1
        later.finish_next()

    assert asked == ["v1", "v3", "v2"]


def test_a_moving_preview_is_made_at_the_priority_every_off_thread_call_runs_at(qtbot, tmp_path):
    seen = []
    previews = MovingPreviews(OutputPlaces.in_one_folder(tmp_path / "output"), tmp_path / "thumbs",
                              make=lambda *_a: seen.append(QThread.currentThread().priority()))

    previews.of(_video(tmp_path, "v1"))
    qtbot.waitUntil(lambda: bool(seen))

    assert seen == [QThreadPool.globalInstance().threadPriority()]


def test_a_video_asked_for_twice_is_made_once(tmp_path):
    previews, later, asked = _previews(tmp_path)

    previews.of(_video(tmp_path, "v1"))
    previews.of(_video(tmp_path, "v1"))
    while later.waiting:
        later.finish_next()

    assert asked == ["v1"]


def test_an_image_asks_for_no_moving_preview(tmp_path):
    previews, later, _asked = _previews(tmp_path)

    assert previews.of(_on_disk(tmp_path, "p1.png")) is None
    assert later.waiting == []


def test_a_gallery_given_no_thumbnails_folder_shows_stills_and_makes_nothing(tmp_path):
    later = _Later()
    previews = MovingPreviews(OutputPlaces.in_one_folder(tmp_path / "output"), None, run=later, make=lambda *_a: "made")

    assert previews.of(_video(tmp_path, "v1")) is None
    assert later.waiting == []
