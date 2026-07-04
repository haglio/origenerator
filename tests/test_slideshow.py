"""SlideshowPlaylist — ordering, wrap navigation, pause, and advance policy."""

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


def test_pause_resume_and_toggle():
    playlist = _playlist()
    assert not playlist.paused
    playlist.pause()
    assert playlist.paused
    playlist.resume()
    assert not playlist.paused
    assert playlist.toggle_pause() is True
    assert playlist.toggle_pause() is False


def test_images_dwell_on_a_timer_but_videos_do_not():
    playlist = _playlist()  # starts on an image
    assert playlist.dwell_ms() == playlist.image_dwell_ms
    playlist.advance()  # -> the video
    assert playlist.dwell_ms() is None  # a video advances when it ends, not on a timer


def test_a_paused_or_empty_playlist_has_no_dwell():
    playlist = _playlist()
    playlist.pause()
    assert playlist.dwell_ms() is None
    assert SlideshowPlaylist([]).dwell_ms() is None


def test_remove_current_drops_the_item_and_advances():
    playlist = SlideshowPlaylist(
        [("a", "image"), ("b", "image"), ("c", "image")], shuffle=lambda order: None,
    )  # order == [0, 1, 2], current == a
    playlist.remove_current()
    assert len(playlist) == 2
    assert playlist.current() == ("b", "image")  # the next item becomes current
