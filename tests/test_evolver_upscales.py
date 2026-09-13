from __future__ import annotations

import os

from origenerator.evolver_upscales import EvolverUpscales

_LONG_AGO = (1_000_000, 1_000_000)


def _file(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def _video(tmp_path):
    return _file(tmp_path / "output" / "video" / "clip_00001_.mp4")


def _upscale(tmp_path, orientation="landscape"):
    return _file(tmp_path / "upscaled_by_orientation" / orientation / "origenerator"
                 / "clip_00001__topaz.mp4")


def _upscales(tmp_path):
    return EvolverUpscales.scan(tmp_path / "upscaled_by_orientation", "origenerator")


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
    upscale = _upscale(tmp_path)
    os.utime(upscale, _LONG_AGO)
    video = _video(tmp_path)

    assert _upscales(tmp_path).upscale_of(video) is None


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
