"""The slideshow playlist — ordering, wrap navigation, holds, and advance policy."""

from origenerator.slideshow import SlideshowPlaylist, in_order


def _playlist(**kw):
    kw.setdefault("shuffle", lambda order: None)  # identity: deterministic order here
    return SlideshowPlaylist(
        [("a.png", "image"), ("b.mp4", "video"), ("c.png", "image")], **kw
    )


def test_current_starts_at_the_first_item():
    playlist = _playlist()
    assert playlist.current() == ("a.png", "image")
    assert len(playlist) == 3
    assert not playlist.is_empty()


def test_an_empty_playlist_has_no_current():
    playlist = SlideshowPlaylist([])
    assert playlist.is_empty()
    assert playlist.current() is None


def test_advance_steps_forward_and_wraps():
    playlist = _playlist()
    assert playlist.advance() == ("b.mp4", "video")
    assert playlist.advance() == ("c.png", "image")
    assert playlist.advance() == ("a.png", "image")  # wrapped to the start


def test_back_steps_backward_and_wraps():
    playlist = _playlist()
    assert playlist.back() == ("c.png", "image")     # wrapped to the end
    assert playlist.back() == ("b.mp4", "video")


def test_advance_and_back_on_an_empty_playlist_stay_empty():
    playlist = SlideshowPlaylist([])
    assert playlist.advance() is None
    assert playlist.back() is None


def test_plays_in_a_shuffled_order():
    playlist = SlideshowPlaylist(
        [("a.png", "image"), ("b.mp4", "video"), ("c.png", "image")],
        shuffle=lambda order: order.reverse(),  # a deterministic stand-in for randomness
    )
    assert playlist.current() == ("c.png", "image")  # shuffled: the last item leads
    assert playlist.advance() == ("b.mp4", "video")
    assert playlist.advance() == ("a.png", "image")


def test_reshuffles_each_full_pass():
    calls = {"n": 0}

    def shuffle(order):
        calls["n"] += 1
        order.reverse()

    playlist = SlideshowPlaylist([("a.png", "image"), ("b.png", "image")], shuffle=shuffle)
    assert calls["n"] == 1  # shuffled once at construction
    playlist.advance()      # the second of the pass
    playlist.advance()      # wraps -> a fresh shuffle

    assert calls["n"] == 2


def test_index_tracks_the_current_position():
    playlist = _playlist()
    assert playlist.index == 0
    playlist.advance()
    assert playlist.index == 1
    playlist.back()
    playlist.back()
    assert playlist.index == 2  # wrapped to the last


def test_lock_toggles_and_releases():
    playlist = _playlist()
    assert not playlist.locked
    assert playlist.toggle_lock() is True
    assert playlist.locked
    assert playlist.toggle_lock() is False
    playlist.toggle_lock()
    playlist.unlock()
    assert not playlist.locked


def test_images_dwell_on_a_timer_but_videos_do_not():
    playlist = _playlist()  # starts on an image
    assert playlist.dwell_ms() == playlist.image_dwell_ms
    playlist.advance()  # -> the video
    assert playlist.dwell_ms() is None  # a video advances when it ends, not on a timer


def test_a_locked_or_empty_playlist_has_no_dwell():
    playlist = _playlist()
    playlist.toggle_lock()
    assert playlist.dwell_ms() is None
    assert SlideshowPlaylist([]).dwell_ms() is None


def test_a_pace_of_nought_means_never_move_on():
    # What a double-clicked picture opens at: the slide holds the screen until an
    # arrow moves it, rather than advancing the instant the timer is armed with 0.
    playlist = _playlist(image_dwell_ms=0)
    assert playlist.dwell_ms() is None


def test_turning_the_pace_up_off_nought_starts_it_moving():
    playlist = _playlist(image_dwell_ms=0)
    playlist.image_dwell_ms = 3000
    assert playlist.dwell_ms() == 3000


# --- opening on a chosen item -----------------------------------------------

def test_a_pass_can_start_on_a_named_item():
    # A double-clicked picture opens on *that* picture, not on whatever the set
    # happens to lead with.
    playlist = _playlist(start=2)
    assert playlist.current() == ("c.png", "image")
    assert playlist.index == 2


def test_the_start_item_is_found_wherever_the_shuffle_put_it():
    playlist = SlideshowPlaylist(
        [("a.png", "image"), ("b.png", "image"), ("c.png", "image")],
        shuffle=lambda order: order.reverse(),  # order == [2, 1, 0]
        start=2,
    )
    assert playlist.current() == ("c.png", "image")
    assert playlist.index == 0  # which is where the reversed pass begins


def test_no_start_leads_with_whatever_the_pass_leads_with():
    # A shuffled show opens on the front of its pass, not on the set's first item.
    playlist = SlideshowPlaylist(
        [("a.png", "image"), ("b.png", "image"), ("c.png", "image")],
        shuffle=lambda order: order.reverse(),
    )
    assert playlist.current() == ("c.png", "image")


def test_an_out_of_range_start_falls_back_to_the_front():
    assert _playlist(start=99).index == 0
    assert SlideshowPlaylist([], start=3).current() is None


def test_in_order_leaves_the_set_exactly_as_handed_over():
    # A folder played from a double-click is the browser's own listing, not a pass.
    playlist = _playlist(shuffle=in_order)
    assert playlist.order == [0, 1, 2]

def test_a_paused_playlist_has_no_dwell_either():
    # What a spoken request puts on the show while the sentence is being said.
    playlist = _playlist()
    playlist.set_paused(True)
    assert playlist.dwell_ms() is None
    assert playlist.holding()

    playlist.set_paused(False)
    assert playlist.dwell_ms() == playlist.image_dwell_ms


def test_the_pause_and_the_lock_are_independent_holds():
    # Releasing one must not release the other: a slide the user locked stays
    # locked when a request ends, and stepping (which drops the lock) must not
    # quietly resume a show that is still listening.
    playlist = _playlist()
    playlist.toggle_lock()
    playlist.set_paused(True)

    playlist.set_paused(False)
    assert playlist.locked and playlist.holding()

    playlist.set_paused(True)
    playlist.unlock()
    assert playlist.paused and playlist.holding()


def test_remove_current_drops_the_item_and_advances():
    playlist = SlideshowPlaylist(
        [("a", "image"), ("b", "image"), ("c", "image")], shuffle=lambda order: None,
    )  # order == [0, 1, 2], current == a
    playlist.remove_current()
    assert len(playlist) == 2
    assert playlist.current() == ("b", "image")  # the next item becomes current


def test_peek_names_the_items_either_side_wrapping():
    playlist = SlideshowPlaylist(
        [("a", "image"), ("b", "image"), ("c", "image")], shuffle=lambda order: None,
    )  # order == [0, 1, 2], current == a
    assert playlist.peek(1) == ("b", "image")
    assert playlist.peek(-1) == ("c", "image")  # wraps to the end of the pass
    assert SlideshowPlaylist([]).peek(1) is None


# --- an item that lands while the show runs ---------------------------------

def test_an_item_that_lands_mid_pass_comes_up_next():
    # Watching a folder fill is watching for the new one, and at the end of a
    # hundred-item pass it would be an hour away.
    playlist = SlideshowPlaylist(
        [("a", "image", "id-a"), ("b", "image", "id-b"), ("c", "image", "id-c")],
        shuffle=lambda order: None,
    )  # order == [0, 1, 2], current == a

    assert playlist.add(("d", "image", "id-d")) is True

    assert len(playlist) == 4
    assert playlist.current()[0] == "a"     # what's on screen is undisturbed
    assert playlist.advance()[0] == "d"     # and the arrival is what follows
    assert playlist.advance()[0] == "b"     # then the pass resumes where it was


def test_an_item_the_playlist_already_holds_is_not_added_twice():
    playlist = SlideshowPlaylist([("a", "image", "id-a")], shuffle=lambda order: None)
    assert playlist.add(("a", "image", "id-a")) is False
    assert len(playlist) == 1


# --- an item that gets enhanced while the show runs -------------------------

def _keyed(**kw):
    kw.setdefault("shuffle", lambda order: None)
    return SlideshowPlaylist(
        [("a.png", "image", "id-a", "a_thumb.png"),
         ("b.png", "image", "id-b", "b_thumb.png")], **kw,
    )


def test_an_enhanced_item_is_replaced_wherever_it_sits():
    # The show paged on long before the enhancement landed, so an arrival dropped
    # for being late would play the pre-enhance file every pass from here on.
    playlist = _keyed()
    playlist.advance()  # on b now; the enhancement of a arrives

    assert playlist.replace_item("id-a", "a_better.png") is True

    assert playlist.current()[0] == "b.png"        # what's on screen is untouched
    assert playlist.back()[0] == "a_better.png"    # and a comes round upgraded


def test_replacing_an_item_the_playlist_does_not_hold_reports_nothing():
    # Every landed enhancement is offered to every open show; one that belongs
    # to a folder this show isn't playing simply isn't here.
    assert _keyed().replace_item("id-elsewhere", "x.png") is False


def test_an_upgraded_item_keeps_its_id_and_media_type():
    playlist = _keyed()
    playlist.replace_item("id-a", "a_better.png")
    assert playlist.current() == ("a_better.png", "image", "id-a", "a_thumb.png")


def test_an_upgraded_item_takes_the_new_thumbnail_when_one_comes_with_it():
    # The still is what the item is drawn as while it's a neighbor; the one it
    # arrived with is of the version the swap just retired.
    playlist = _keyed()
    playlist.replace_item("id-a", "a_better.png", "image", "a_better_thumb.png")
    assert playlist.current()[3] == "a_better_thumb.png"



# --- picking a closed show's pass back up -----------------------------------

def _four(**kw):
    kw.setdefault("shuffle", lambda order: None)
    return SlideshowPlaylist(
        [(f"{name}.png", "image", f"id-{name}") for name in "abcd"], **kw
    )


def test_a_resumed_pass_plays_the_order_it_was_left_in():
    playlist = _four(shuffle=lambda order: order.reverse())  # d, c, b, a

    assert playlist.resume(["id-b", "id-d", "id-a", "id-c"], "id-d") is True

    assert playlist.current()[2] == "id-d"           # standing where it left off
    assert playlist.advance()[2] == "id-a"           # and carrying on that pass
    assert playlist.order_ids() == ["id-b", "id-d", "id-a", "id-c"]


def test_a_resumed_pass_stands_on_the_slide_wherever_the_order_puts_it():
    playlist = _four()
    assert playlist.resume(["id-c", "id-a", "id-b", "id-d"], "id-b") is True
    assert playlist.index == 2


def test_a_slide_that_is_no_longer_here_resumes_nothing():
    # Culled while the show was away, or this is another folder's set entirely:
    # a pass laid out around an item that isn't in it would open on a stranger.
    playlist = _four()
    assert playlist.resume(["id-elsewhere"], "id-elsewhere") is False
    assert playlist.current()[2] == "id-a"           # the shuffle, undisturbed
    assert playlist.order_ids() == ["id-a", "id-b", "id-c", "id-d"]


def test_items_the_remembered_order_never_saw_follow_the_ones_it_did():
    # Two landed while the show was away. They were no part of the pass being
    # picked back up, and the next pass reshuffles the lot anyway.
    playlist = _four()
    assert playlist.resume(["id-c", "id-a"], "id-c") is True
    assert playlist.order_ids() == ["id-c", "id-a", "id-b", "id-d"]


def test_a_remembered_item_that_has_since_gone_is_skipped():
    playlist = _four()
    playlist.resume(["id-d", "id-gone", "id-b"], "id-d")
    assert playlist.order_ids() == ["id-d", "id-b", "id-a", "id-c"]


def test_a_set_with_no_ids_names_no_pass():
    # A playlist assembled without ids (a test's, or a lone file's) has nothing
    # to say about where it was.
    playlist = _playlist()
    assert playlist.order_ids() == [None, None, None]
    assert playlist.resume([None], None) is False


def test_the_lock_can_be_put_back_where_a_closed_show_left_it():
    playlist = _four()
    playlist.set_locked(True)
    assert playlist.locked
    assert playlist.dwell_ms() is None     # held, so nothing moves it on
    playlist.set_locked(False)
    assert not playlist.locked
