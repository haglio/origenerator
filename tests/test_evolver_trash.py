from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from origenerator import evolver_trash


def _an_evolver(tmp_path: Path, *, publishes: bool = True) -> Path:
    checkout = tmp_path / "evolver"
    checkout.mkdir()
    published = {"delete_from_trash_command": [".venv/Scripts/python.exe", "-m", "delete_from_trash"]}
    (checkout / "evolver_contract.json").write_text(
        json.dumps(published if publishes else {}), encoding="utf-8")
    return checkout


class Runner:
    def __init__(self, said: str = '{"deleted": 2}\n', fails: Exception | None = None):
        self.said, self.fails, self.asked = said, fails, []

    def __call__(self, command, **kwargs):
        self.asked.append((command, kwargs["cwd"]))
        if self.fails is not None:
            raise self.fails
        return subprocess.CompletedProcess(command, 0, stdout=self.said, stderr="")


def test_evolver_is_asked_to_end_each_video_with_the_command_it_publishes(tmp_path):
    checkout, runner = _an_evolver(tmp_path), Runner()
    videos = [tmp_path / "kino trash" / "video one.mp4", tmp_path / "genau trash" / "loop.mp4"]

    deleted = evolver_trash.delete_for_good(videos, checkout=checkout, runner=runner)

    assert deleted == 2
    assert runner.asked == [([str(checkout / ".venv/Scripts/python.exe"), "-m", "delete_from_trash",
                              *map(str, videos)], str(checkout))]


def test_a_long_list_goes_to_evolver_a_few_videos_at_a_time(tmp_path):
    checkout, runner = _an_evolver(tmp_path), Runner()
    videos = [tmp_path / f"video {number}.mp4" for number in range(evolver_trash.VIDEOS_PER_ASK + 1)]

    evolver_trash.delete_for_good(videos, checkout=checkout, runner=runner)

    assert [len(command) - 3 for command, _cwd in runner.asked] == [evolver_trash.VIDEOS_PER_ASK, 1]


def test_an_evolver_naming_no_such_command_is_asked_nothing_and_it_says_so(tmp_path, caplog):
    checkout, runner = _an_evolver(tmp_path, publishes=False), Runner()

    with caplog.at_level(logging.WARNING, logger="origenerator.evolver_trash"):
        deleted = evolver_trash.delete_for_good([tmp_path / "video.mp4"], checkout=checkout,
                                                runner=runner)

    assert (deleted, runner.asked) == (0, [])
    assert "stay in" in caplog.text


def test_an_evolver_that_cannot_be_asked_leaves_the_videos_and_says_so(tmp_path, caplog):
    checkout = _an_evolver(tmp_path)
    runner = Runner(fails=subprocess.TimeoutExpired("evolver", 1))

    with caplog.at_level(logging.WARNING, logger="origenerator.evolver_trash"):
        deleted = evolver_trash.delete_for_good([tmp_path / "video.mp4"], checkout=checkout,
                                                runner=runner)

    assert deleted == 0
    assert "could not" in caplog.text


def test_an_answer_that_is_no_count_is_counted_as_nothing(tmp_path):
    checkout = _an_evolver(tmp_path)

    deleted = evolver_trash.delete_for_good([tmp_path / "video.mp4"], checkout=checkout,
                                            runner=Runner(said="Traceback\n"))

    assert deleted == 0


def test_the_app_asks_evolver_off_its_own_thread(tmp_path):
    started = []

    evolver_trash.in_the_background([tmp_path / "video.mp4"],
                                    start=lambda **thread: started.append(thread))

    [thread] = started
    assert thread["target"] is evolver_trash.delete_for_good
    assert thread["args"] == ([tmp_path / "video.mp4"],)
