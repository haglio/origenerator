from __future__ import annotations

from origenerator.slideshow import LIVE
from origenerator.slideshow_deal import Dealing, newest_first, shuffled_by_weight

_THREE_VIDEOS = [("a.mp4", "video"), ("b.mp4", "video"), ("c.mp4", "video")]
_ALWAYS_SKIPPED = 0.0


def _weighing(weights: dict, **dealing) -> Dealing:
    return Dealing(weight_of=lambda path: weights[str(path)], **dealing)


def _dealt_into(playlist) -> list:
    return sorted(str(slide.path) for slide in playlist.items)


def test_a_pass_dealt_by_weight_leads_with_the_heaviest_and_keeps_each_item_no_group_holds():
    weights = {"a.png": 1.0, "b.mp4": 1e12, "c.png": 1.0}
    items = [("a.png", "image"), ("b.mp4", "video"), ("c.png", "image")]

    playlist = shuffled_by_weight(items, start=None, dealing=_weighing(weights))

    assert playlist.current().path == "b.mp4"
    assert _dealt_into(playlist) == ["a.png", "b.mp4", "c.png"]


def test_a_video_he_always_skips_sits_out_a_shuffled_pass():
    weights = {"a.mp4": _ALWAYS_SKIPPED, "b.mp4": 1.0, "c.mp4": 2.0}

    playlist = shuffled_by_weight(_THREE_VIDEOS, start=None, dealing=_weighing(weights))

    assert _dealt_into(playlist) == ["b.mp4", "c.mp4"]


def test_the_item_on_screen_and_what_is_being_made_are_never_the_ones_left_out():
    items = [("a.mp4", "video"), ("frame.png", LIVE, "g-run"), ("c.mp4", "video")]
    skipped = dict.fromkeys(("a.mp4", "frame.png", "c.mp4"), _ALWAYS_SKIPPED)
    dealing = _weighing(skipped, stays=lambda slide: slide.is_live)

    playlist = shuffled_by_weight(items, start=0, dealing=dealing)

    assert playlist.current().path == "a.mp4"
    assert _dealt_into(playlist) == ["a.mp4", "frame.png"]


def test_a_pass_is_never_dealt_empty():
    skipped = dict.fromkeys(("a.mp4", "b.mp4", "c.mp4"), _ALWAYS_SKIPPED)

    playlist = shuffled_by_weight(_THREE_VIDEOS, start=None, dealing=_weighing(skipped))

    assert _dealt_into(playlist) == ["a.mp4", "b.mp4", "c.mp4"]


def test_a_pass_of_the_latest_leaves_nothing_out_whatever_he_skips():
    skipped = dict.fromkeys(("a.mp4", "b.mp4", "c.mp4"), _ALWAYS_SKIPPED)

    playlist = newest_first(_THREE_VIDEOS, start=None, dealing=_weighing(skipped))

    assert [slide.path for slide in playlist.in_play_order()] == ["a.mp4", "b.mp4", "c.mp4"]


def test_a_pass_of_the_latest_opens_on_the_slide_it_was_asked_to_and_keeps_its_place():
    grouped = Dealing(group_of=lambda slide, _seed: "one image")

    playlist = newest_first(_THREE_VIDEOS, start=2, dealing=grouped)

    assert [slide.path for slide in playlist.in_play_order()] == ["c.mp4"]
    assert playlist.current().path == "c.mp4"
