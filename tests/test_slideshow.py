"""The slideshow playlist — ordering, wrap navigation, holds, and advance policy."""

from origenerator.slideshow import SlideshowPlaylist


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

