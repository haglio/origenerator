"""SlideshowPlaylist — ordering, wrap navigation, pause, and advance policy."""

from origenerator.slideshow import SlideshowPlaylist


def _playlist(**kw):
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


def test_adjusting_the_dwell_clamps_to_bounds():
    playlist = _playlist(image_dwell_ms=4000)
    assert playlist.adjust_dwell(1000) == 5000
    for _ in range(100):
        playlist.adjust_dwell(5000)
    assert playlist.image_dwell_ms == playlist.MAX_DWELL_MS
    for _ in range(100):
        playlist.adjust_dwell(-5000)
    assert playlist.image_dwell_ms == playlist.MIN_DWELL_MS
