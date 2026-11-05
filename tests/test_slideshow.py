from __future__ import annotations

import json

from origenerator.slideshow import (
    LIVE,
    Slide,
    SlideshowFilters,
    SlideshowPlaylist,
    SlideshowState,
    dealt,
    in_order,
)
from tests.slideshow_support import ahead


def _playlist(**kw):
    kw.setdefault("shuffle", lambda order: None)
    return SlideshowPlaylist(
        [("a.png", "image"), ("b.mp4", "video"), ("c.png", "image")], **kw
    )


def test_current_starts_at_the_first_item():
    playlist = _playlist()
    assert playlist.current() == Slide("a.png", "image")
    assert len(playlist) == 3
    assert not playlist.is_empty()


def test_a_slide_names_its_own_fields():
    slide = _playlist().current()
    assert (slide.path, slide.media_type) == ("a.png", "image")
    assert slide.prompt_id is None
    assert slide.still is None


def test_an_empty_playlist_has_no_current():
    playlist = SlideshowPlaylist([])
    assert playlist.is_empty()
    assert playlist.current() is None


def test_advance_steps_forward_and_wraps():
    playlist = _playlist()
    assert playlist.advance() == Slide("b.mp4", "video")
    assert playlist.advance() == Slide("c.png", "image")
    assert playlist.advance() == Slide("a.png", "image")


def test_back_steps_backward_and_wraps():
    playlist = _playlist()
    assert playlist.back() == Slide("c.png", "image")
    assert playlist.back() == Slide("b.mp4", "video")


def test_advance_and_back_on_an_empty_playlist_stay_empty():
    playlist = SlideshowPlaylist([])
    assert playlist.advance() is None
    assert playlist.back() is None


def test_plays_in_a_shuffled_order():
    playlist = SlideshowPlaylist(
        [("a.png", "image"), ("b.mp4", "video"), ("c.png", "image")],
        shuffle=lambda order: order.reverse(),
    )
    assert playlist.current() == Slide("c.png", "image")
    assert playlist.advance() == Slide("b.mp4", "video")
    assert playlist.advance() == Slide("a.png", "image")


def test_reshuffles_each_full_pass():
    calls = {"n": 0}

    def shuffle(order):
        calls["n"] += 1
        order.reverse()

    playlist = SlideshowPlaylist([("a.png", "image"), ("b.png", "image")], shuffle=shuffle)
    assert calls["n"] == 1
    playlist.advance()
    playlist.advance()

    assert calls["n"] == 2


def test_index_tracks_the_current_position():
    playlist = _playlist()
    assert playlist.index == 0
    playlist.advance()
    assert playlist.index == 1
    playlist.back()
    playlist.back()
    assert playlist.index == 2


def test_a_pass_can_start_on_a_named_item():
    playlist = _playlist(start=2)
    assert playlist.current() == Slide("c.png", "image")
    assert playlist.index == 2


def test_the_start_item_is_found_wherever_the_shuffle_put_it():
    playlist = SlideshowPlaylist(
        [("a.png", "image"), ("b.png", "image"), ("c.png", "image")],
        shuffle=lambda order: order.reverse(),
        start=2,
    )
    assert playlist.current() == Slide("c.png", "image")
    assert playlist.index == 0


def test_no_start_leads_with_whatever_the_pass_leads_with():
    playlist = SlideshowPlaylist(
        [("a.png", "image"), ("b.png", "image"), ("c.png", "image")],
        shuffle=lambda order: order.reverse(),
    )
    assert playlist.current() == Slide("c.png", "image")


def test_an_out_of_range_start_falls_back_to_the_front():
    assert _playlist(start=99).index == 0
    assert SlideshowPlaylist([], start=3).current() is None


def test_in_order_leaves_the_set_exactly_as_handed_over():
    playlist = _playlist(shuffle=in_order)
    assert playlist.order == [0, 1, 2]

def test_remove_current_drops_the_item_and_advances():
    playlist = SlideshowPlaylist(
        [("a", "image"), ("b", "image"), ("c", "image")], shuffle=lambda order: None,
    )
    playlist.remove_current()
    assert len(playlist) == 2
    assert playlist.current() == Slide("b", "image")


def test_peek_names_the_items_either_side_wrapping():
    playlist = SlideshowPlaylist(
        [("a", "image"), ("b", "image"), ("c", "image")], shuffle=lambda order: None,
    )
    assert ahead(playlist, 1) == Slide("b", "image")
    assert ahead(playlist, -1) == Slide("c", "image")
    assert ahead(SlideshowPlaylist([]), 1) is None


def test_an_item_that_lands_mid_pass_comes_up_next():
    playlist = SlideshowPlaylist(
        [("a", "image", "id-a"), ("b", "image", "id-b"), ("c", "image", "id-c")],
        shuffle=lambda order: None,
    )

    assert playlist.add(("d", "image", "id-d")) is True

    assert len(playlist) == 4
    assert playlist.current()[0] == "a"
    assert playlist.advance()[0] == "d"
    assert playlist.advance()[0] == "b"


def test_an_item_the_playlist_already_holds_is_not_added_twice():
    playlist = SlideshowPlaylist([("a", "image", "id-a")], shuffle=lambda order: None)
    assert playlist.add(("a", "image", "id-a")) is False
    assert len(playlist) == 1


def test_a_slide_led_with_comes_up_now_and_the_one_it_displaced_next():
    playlist = _playlist()
    playlist.advance()

    playlist.lead_with(2)

    assert playlist.current() == Slide("c.png", "image")
    assert ahead(playlist, 1) == Slide("b.mp4", "video")
    assert ahead(playlist, 2) == Slide("a.png", "image")


def test_a_slide_led_with_from_earlier_in_the_pass_still_comes_up_now():
    playlist = _playlist()
    playlist.advance()
    playlist.advance()

    playlist.lead_with(0)

    assert playlist.current() == Slide("a.png", "image")
    assert ahead(playlist, 1) == Slide("c.png", "image")
    assert ahead(playlist, 2) == Slide("b.mp4", "video")


def _keyed(**kw):
    kw.setdefault("shuffle", lambda order: None)
    return SlideshowPlaylist(
        [("a.png", "image", "id-a", "a_thumb.png"),
         ("b.png", "image", "id-b", "b_thumb.png")], **kw,
    )


def test_an_enhanced_item_is_replaced_wherever_it_sits():
    playlist = _keyed()
    playlist.advance()

    assert playlist.replace_item("id-a", "a_better.png") is True

    assert playlist.current()[0] == "b.png"
    assert playlist.back()[0] == "a_better.png"


def test_replacing_an_item_the_playlist_does_not_hold_reports_nothing():
    assert _keyed().replace_item("id-elsewhere", "x.png") is False


def test_an_upgraded_item_keeps_its_id_and_media_type():
    playlist = _keyed()
    playlist.replace_item("id-a", "a_better.png")
    assert playlist.current() == ("a_better.png", "image", "id-a", "a_thumb.png")


def test_an_upgraded_item_takes_the_new_thumbnail_when_one_comes_with_it():
    playlist = _keyed()
    playlist.replace_item("id-a", "a_better.png", "image", "a_better_thumb.png")
    assert playlist.current()[3] == "a_better_thumb.png"


def _four(**kw):
    kw.setdefault("shuffle", lambda order: None)
    return SlideshowPlaylist(
        [(f"{name}.png", "image", f"id-{name}") for name in "abcd"], **kw
    )


def test_a_resumed_pass_plays_the_order_it_was_left_in():
    playlist = _four(shuffle=lambda order: order.reverse())

    assert playlist.resume(["id-b", "id-d", "id-a", "id-c"], "id-d") is True

    assert playlist.current()[2] == "id-d"
    assert playlist.advance()[2] == "id-a"
    assert playlist.order_ids() == ["id-b", "id-d", "id-a", "id-c"]


def test_a_resumed_pass_stands_on_the_slide_wherever_the_order_puts_it():
    playlist = _four()
    assert playlist.resume(["id-c", "id-a", "id-b", "id-d"], "id-b") is True
    assert playlist.index == 2


def test_a_slide_that_is_no_longer_here_resumes_nothing():
    playlist = _four()
    assert playlist.resume(["id-elsewhere"], "id-elsewhere") is False
    assert playlist.current()[2] == "id-a"
    assert playlist.order_ids() == ["id-a", "id-b", "id-c", "id-d"]


def test_items_the_remembered_order_never_saw_follow_the_ones_it_did():
    playlist = _four()
    assert playlist.resume(["id-c", "id-a"], "id-c") is True
    assert playlist.order_ids() == ["id-c", "id-a", "id-b", "id-d"]


def test_a_remembered_item_that_has_since_gone_is_skipped():
    playlist = _four()
    playlist.resume(["id-d", "id-gone", "id-b"], "id-d")
    assert playlist.order_ids() == ["id-d", "id-b", "id-a", "id-c"]


def test_a_set_with_no_ids_names_no_pass():
    playlist = _playlist()
    assert playlist.order_ids() == [None, None, None]
    assert playlist.resume([None], None) is False


def test_a_run_being_made_joins_as_a_slide_of_its_frames():
    playlist = _four()

    assert playlist.add((b"frame-1", LIVE, "id-new", None)) is True

    assert ahead(playlist, 1) == (b"frame-1", LIVE, "id-new", None)
    assert playlist.live_ids() == ["id-new"]
    assert playlist.holds("id-new")


def test_a_live_slide_takes_the_newest_frame_of_itself():
    playlist = _four()
    playlist.add((b"frame-1", LIVE, "id-new", None))

    assert playlist.update_live("id-new", b"frame-2") is True

    assert ahead(playlist, 1)[0] == b"frame-2"


def test_a_frame_for_a_slide_that_already_landed_is_ignored():
    playlist = _four()

    assert playlist.update_live("id-a", b"frame-late") is False

    assert playlist.current() == Slide("a.png", "image", "id-a")


def test_a_live_slide_becomes_the_file_it_lands_as():
    playlist = _four()
    playlist.add((b"frame-1", LIVE, "id-new", None))

    assert playlist.replace_live("id-new", "new.mp4", "video", "thumb.png") is True

    assert len(playlist) == 5
    assert ahead(playlist, 1) == ("new.mp4", "video", "id-new", "thumb.png")
    assert playlist.live_ids() == []


def test_a_run_that_lands_after_the_slideshow_moved_past_it_comes_up_next():
    playlist = _four()
    playlist.add((b"frame-1", LIVE, "id-new", None))
    for _ in range(3):
        playlist.advance()

    playlist.replace_live("id-new", "new.png", "image")

    assert playlist.current() == Slide("c.png", "image", "id-c")
    assert ahead(playlist, 1) == ("new.png", "image", "id-new", None)


def test_a_landed_run_comes_up_before_a_run_whose_frames_came_in_after_it():
    playlist = _four()
    playlist.add((b"frame-1", LIVE, "id-first", None))
    playlist.advance()
    playlist.advance()

    playlist.replace_live("id-first", "first.png", "image")
    playlist.add((b"frame-1", LIVE, "id-second", None))

    assert playlist.advance()[2] == "id-first"
    assert playlist.advance()[2] == "id-second"
    assert playlist.advance()[2] == "id-c"


def test_arrivals_keep_their_order_when_a_slide_is_dropped_from_the_set():
    playlist = _four()
    playlist.add(("e.png", "image", "id-e"))

    playlist.drop("id-c")
    playlist.add((b"frame-1", LIVE, "id-new", None))

    assert playlist.advance()[2] == "id-e"
    assert playlist.advance()[2] == "id-new"


def test_an_arrival_that_has_been_on_screen_no_longer_waits_ahead_of_new_ones():
    playlist = _four()
    playlist.add(("e.png", "image", "id-e"))
    playlist.advance()
    playlist.back()

    playlist.add((b"frame-1", LIVE, "id-new", None))

    assert playlist.advance()[2] == "id-new"


def test_a_run_that_lands_while_waiting_its_turn_keeps_its_place_in_line():
    playlist = _four()
    playlist.add((b"frame-1", LIVE, "id-first", None))
    playlist.add(("e.png", "image", "id-e"))

    playlist.replace_live("id-first", "first.png", "image")

    assert playlist.advance()[2] == "id-first"
    assert playlist.advance()[2] == "id-e"


def test_an_arrival_jumped_onto_no_longer_waits_ahead_of_new_ones():
    playlist = _four()
    playlist.add(("e.png", "image", "id-e"))
    playlist.jump_to(4)
    playlist.back()

    playlist.add((b"frame-1", LIVE, "id-new", None))

    assert playlist.advance()[2] == "id-new"


def test_an_arrival_led_with_no_longer_waits_ahead_of_new_ones():
    playlist = _four()
    playlist.advance()
    playlist.add(("e.png", "image", "id-e"))
    playlist.lead_with(4)
    playlist.back()

    playlist.add((b"frame-1", LIVE, "id-new", None))

    assert playlist.advance()[2] == "id-new"


def test_a_waiting_run_the_slideshow_jumped_past_comes_up_next_when_it_lands():
    playlist = _four()
    playlist.add((b"frame-1", LIVE, "id-first", None))
    playlist.jump_to(2)

    playlist.replace_live("id-first", "first.png", "image")

    assert playlist.advance()[2] == "id-first"


def test_an_item_that_was_never_live_is_not_replaced_as_one():
    playlist = _four()
    assert playlist.replace_live("id-a", "other.png", "image") is False
    assert playlist.current() == Slide("a.png", "image", "id-a")


def test_a_slide_of_a_runs_frames_is_live_and_a_file_is_not():
    playlist = SlideshowPlaylist([(b"frame-1", LIVE, "id-new"), ("a.png", "image", "id-a")],
                                 shuffle=in_order)
    assert playlist.current_is_live()
    playlist.advance()
    assert not playlist.current_is_live()


def test_a_run_that_stopped_being_made_is_dropped_wherever_it_sits():
    playlist = _four()
    playlist.add((b"frame-1", LIVE, "id-new", None))

    assert playlist.drop("id-new") is True

    assert playlist.live_ids() == []
    assert playlist.order_ids() == ["id-a", "id-b", "id-c", "id-d"]
    assert playlist.current()[2] == "id-a"


def test_dropping_an_item_behind_the_slide_on_screen_keeps_that_slide():
    playlist = _four()
    playlist.advance()
    playlist.advance()

    assert playlist.drop("id-a") is True

    assert playlist.current()[2] == "id-c"
    assert playlist.order_ids() == ["id-b", "id-c", "id-d"]


def test_dropping_the_slide_on_screen_leaves_the_one_after_it():
    playlist = _four()
    playlist.advance()

    assert playlist.drop("id-b") is True

    assert playlist.current()[2] == "id-c"


def test_dropping_something_that_was_never_here_changes_nothing():
    playlist = _four()
    assert playlist.drop("id-elsewhere") is False
    assert playlist.order_ids() == ["id-a", "id-b", "id-c", "id-d"]


def test_where_a_slideshow_was_left_reads_back_as_it_was_saved():
    state = SlideshowState(order=("id-b", "id-a"), current="id-a", locked=True, version_index=1,
                           loop="seed", loop_pool=("id-b", "id-a", "id-far"))

    assert SlideshowState.restored(json.loads(json.dumps(state.saved()))) == state


def test_the_filters_read_back_as_they_were_saved():
    filters = SlideshowFilters(favorites=True, enhanced=True, action="alpha")

    assert SlideshowFilters.restored(json.loads(json.dumps(filters.saved()))) == filters
    assert SlideshowFilters.restored({"favorites": 1, "act": ["alpha"]}) == SlideshowFilters()


def test_the_action_filter_is_saved_under_the_key_older_copies_of_the_app_read():
    assert SlideshowFilters(action="alpha").saved() == {"favorites": False, "enhanced": False, "act": "alpha"}
    assert SlideshowFilters.restored({"act": "alpha"}) == SlideshowFilters(action="alpha")


def test_a_saved_slideshow_that_makes_no_sense_reads_back_as_nowhere():
    nonsense = {"order": "id-a", "current": 3, "locked": "yes", "version_index": -2,
                "loop": 5, "loop_pool": "id-a"}

    assert SlideshowState.restored(nonsense) == SlideshowState()
    assert SlideshowState.restored(None) == SlideshowState()


def test_restart_returns_to_the_top_of_the_pass_not_the_top_of_the_set():
    playlist = _four(shuffle=lambda order: order.reverse())
    playlist.advance()
    playlist.advance()

    playlist.restart()

    assert playlist.current()[2] == "id-d"


def test_restarting_twice_keeps_the_order_the_pass_was_dealt():
    playlist = _four(shuffle=lambda order: order.reverse())
    playlist.restart()
    first = playlist.order_ids()
    playlist.restart()
    assert playlist.order_ids() == first


def test_jumping_names_the_item_by_its_place_in_the_set_not_in_the_pass():
    playlist = _four(shuffle=lambda order: order.reverse())

    assert playlist.jump_to(0) is True

    assert playlist.current()[2] == "id-a"


def test_jumping_to_a_place_the_set_does_not_have_reports_nothing_and_stays_put():
    playlist = _four()
    assert playlist.jump_to(9) is False
    assert playlist.jump_to(-1) is False
    assert playlist.current()[2] == "id-a"


def test_the_items_in_play_order_follow_the_pass_rather_than_the_set():
    playlist = _four(shuffle=lambda order: order.reverse())
    assert [slide[2] for slide in playlist.in_play_order()] == [
        "id-d", "id-c", "id-b", "id-a"]


def test_an_unnamed_generation_matches_none_of_the_unnamed_slides():
    playlist = _playlist()
    assert playlist.holds(None) is False


def _weighing(weights: dict):
    return weights.__getitem__


def test_a_pass_dealt_by_weight_leads_with_the_heaviest_and_keeps_every_item():
    playlist = SlideshowPlaylist(
        [("a.png", "image"), ("b.mp4", "video"), ("c.png", "image")],
        weight_of=_weighing({"a.png": 1e-12, "b.mp4": 1e12, "c.png": 1e-12}))

    assert playlist.current().path == "b.mp4"
    assert sorted(slide.path for slide in playlist.in_play_order()) == ["a.png", "b.mp4", "c.png"]


def test_each_new_pass_is_dealt_by_weight_again():
    playlist = SlideshowPlaylist(
        [("a.png", "image"), ("b.mp4", "video"), ("c.png", "image")],
        weight_of=_weighing({"a.png": 1e-12, "b.mp4": 1e12, "c.png": 1e-12}))

    for _ in range(3):
        playlist.advance()

    assert playlist.current().path == "b.mp4"


_THREE_VIDEOS = [("a.mp4", "video"), ("b.mp4", "video"), ("c.mp4", "video")]
_ALWAYS_SKIPPED = 0.0


def _shuffled(items, weights: dict, *, start=None) -> SlideshowPlaylist:
    return dealt(items, shuffle=None, start=start, weight_of=_weighing(weights))


def _dealt_into(playlist: SlideshowPlaylist) -> list:
    return sorted(slide.path for slide in playlist.items)


def test_a_video_he_always_skips_sits_out_a_shuffled_pass():
    playlist = _shuffled(_THREE_VIDEOS, {"a.mp4": _ALWAYS_SKIPPED, "b.mp4": 1.0, "c.mp4": 2.0})

    assert _dealt_into(playlist) == ["b.mp4", "c.mp4"]


def test_the_item_on_screen_and_what_is_being_made_are_never_the_ones_left_out():
    items = [("a.mp4", "video"), ("frame.png", LIVE, "g-run"), ("c.mp4", "video")]
    skipped = dict.fromkeys(("a.mp4", "frame.png", "c.mp4"), _ALWAYS_SKIPPED)

    playlist = _shuffled(items, skipped, start=0)

    assert playlist.current().path == "a.mp4"
    assert _dealt_into(playlist) == ["a.mp4", "frame.png"]


def test_a_pass_is_never_dealt_empty():
    skipped = dict.fromkeys(("a.mp4", "b.mp4", "c.mp4"), _ALWAYS_SKIPPED)

    assert _dealt_into(_shuffled(_THREE_VIDEOS, skipped)) == ["a.mp4", "b.mp4", "c.mp4"]


def test_a_pass_of_the_latest_leaves_nothing_out_whatever_he_skips():
    skipped = dict.fromkeys(("a.mp4", "b.mp4", "c.mp4"), _ALWAYS_SKIPPED)

    playlist = dealt(_THREE_VIDEOS, shuffle=in_order, start=None, weight_of=_weighing(skipped))

    assert [slide.path for slide in playlist.in_play_order()] == ["a.mp4", "b.mp4", "c.mp4"]
