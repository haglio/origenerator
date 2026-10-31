from __future__ import annotations

import os
import time
from pathlib import Path

from origenerator.evolver_upscales import EvolverUpscales

_LONG_AGO = (1_000_000, 1_000_000)


def _file(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def _video(tmp_path):
    return _file(tmp_path / "output" / "video" / "clip_00001_.mp4")


def _upscale(tmp_path, shape="landscape"):
    return _file(tmp_path / "upscaled_by_shape" / shape / "origenerator"
                 / "clip_00001__topaz.mp4")


def _upscales(tmp_path):
    return EvolverUpscales.scan(tmp_path / "upscaled_by_shape", "origenerator")


def test_a_video_is_matched_to_the_upscale_evolver_filed_for_it(tmp_path):
    video = _video(tmp_path)
    os.utime(video, _LONG_AGO)
    upscale = _upscale(tmp_path)

    assert _upscales(tmp_path).upscale_of(video) == upscale


def test_a_portrait_video_is_found_under_its_own_shape(tmp_path):
    video = _video(tmp_path)
    os.utime(video, _LONG_AGO)
    upscale = _upscale(tmp_path, "portrait")

    assert _upscales(tmp_path).upscale_of(video) == upscale


def test_a_later_video_that_reuses_an_older_ones_name_is_not_given_its_upscale(tmp_path):
    _upscale(tmp_path)
    video = _video(tmp_path)
    an_hour_on = time.time() + 3600
    os.utime(video, (an_hour_on, an_hour_on))

    assert _upscales(tmp_path).upscale_of(video) is None


def test_an_upscale_left_with_a_1970_file_date_is_still_matched(tmp_path):
    video = _video(tmp_path)
    os.utime(video, _LONG_AGO)
    upscale = _upscale(tmp_path)
    os.utime(upscale, (2_000, 2_000))

    assert _upscales(tmp_path).upscale_of(video) == upscale


def test_only_a_video_has_an_upscale(tmp_path):
    still = _file(tmp_path / "output" / "image" / "clip_00001_.png")
    os.utime(still, _LONG_AGO)
    _upscale(tmp_path)

    assert _upscales(tmp_path).upscale_of(still) is None


def test_an_upscale_moved_away_since_the_library_was_read_is_no_upscale(tmp_path):
    video = _video(tmp_path)
    os.utime(video, _LONG_AGO)
    upscale = _upscale(tmp_path)
    upscales = _upscales(tmp_path)
    upscale.unlink()

    assert upscales.upscale_of(video) is None


def test_a_folder_of_upscales_unchanged_since_its_last_reading_is_not_listed_again(
        tmp_path, monkeypatch):
    # Listed afresh at every look, Evolver's folder of upscales was read three to
    # eight times over before a double-clicked slideshow could open.
    filed_in = _upscale(tmp_path).parent
    os.utime(filed_in, _LONG_AGO)
    _upscales(tmp_path)
    listed = []
    iterdir = Path.iterdir
    monkeypatch.setattr(Path, "iterdir", lambda folder: listed.append(folder) or iterdir(folder))

    _upscales(tmp_path)

    assert filed_in not in listed


def test_an_upscale_filed_since_the_last_reading_is_found(tmp_path):
    video = _video(tmp_path)
    os.utime(video, _LONG_AGO)
    _file(tmp_path / "upscaled_by_orientation" / "landscape" / "origenerator" / "other_topaz.mp4")
    _upscales(tmp_path)

    upscale = _upscale(tmp_path)

    assert _upscales(tmp_path).upscale_of(video) == upscale


def test_an_upscale_filed_in_the_same_clock_tick_as_the_last_reading_is_found(tmp_path):
    # Windows stamps a folder from a clock that moves in steps of about 16 ms,
    # so a file filed just after a reading can leave the folder's time as it was.
    video = _video(tmp_path)
    os.utime(video, _LONG_AGO)
    folder = _file(tmp_path / "upscaled_by_orientation" / "landscape" / "origenerator"
                   / "other_topaz.mp4").parent
    read_at = folder.stat().st_mtime_ns
    _upscales(tmp_path)

    upscale = _upscale(tmp_path)
    os.utime(folder, ns=(read_at, read_at))

    assert _upscales(tmp_path).upscale_of(video) == upscale
