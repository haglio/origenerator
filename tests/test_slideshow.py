"""The slideshow playlists — ordering, wrap navigation, holds, and advance policy."""

from origenerator.slideshow import LIVE, AutoGeneratePlaylist, SlideshowPlaylist


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


def test_peek_names_the_items_either_side_wrapping():
    playlist = SlideshowPlaylist(
        [("a", "image"), ("b", "image"), ("c", "image")], shuffle=lambda order: None,
    )  # order == [0, 1, 2], current == a
    assert playlist.peek(1) == ("b", "image")
    assert playlist.peek(-1) == ("c", "image")  # wraps to the end of the pass
    assert SlideshowPlaylist([]).peek(1) is None


# --- AutoGeneratePlaylist: the growing rotation behind the auto-generate view


def _grown(n=2):
    """A rotation seeded with *n* finished items, sitting on the live slot."""
    playlist = AutoGeneratePlaylist()
    for i in range(n):
        playlist.add_finished(f"item{i}.png", "image", f"id-{i}", stay_live=True)
    return playlist


def test_opens_on_the_live_slot():
    playlist = AutoGeneratePlaylist()
    assert playlist.count == 1
    assert playlist.current() is LIVE
    assert playlist.on_live()


def test_seeding_grows_the_rotation_but_stays_on_the_live_slot():
    playlist = _grown(3)
    assert playlist.count == 4
    assert playlist.current() is LIVE
    assert playlist.index == 3  # the live slot trails the finished items


def test_peek_names_the_slots_either_side_wrapping_across_the_live_one():
    playlist = _grown(2)          # two finished items, then the live slot (current)
    assert playlist.peek(-1)[2] == "id-1"  # the newest finished item, behind it
    assert playlist.peek(1)[2] == "id-0"   # and wrapping round to the oldest
    playlist.back()                        # onto the newest finished item
    assert playlist.peek(1) is LIVE        # the live slot is what's next


def test_a_completion_hands_the_live_slot_over_to_the_finished_item():
    playlist = _grown(1)
    playlist.add_finished("done.png", "image", "id-done")  # no stay_live: it landed
    assert playlist.current() == ("done.png", "image", "id-done", None)
    assert playlist.on_live() is False
    assert playlist.count == 3  # both finished items, plus the next one's live slot


def test_a_completion_elsewhere_leaves_the_shown_item_alone():
    playlist = _grown(2)
    playlist.back()  # step off the live slot onto the newest finished item
    shown = playlist.current()
    playlist.add_finished("done.png", "image", "id-done")
    assert playlist.current() == shown


def test_advance_and_back_wrap_across_items_and_live_slot():
    playlist = _grown(2)                      # on the live slot (index 2)
    assert playlist.advance()[2] == "id-0"    # wraps to the oldest
    assert playlist.advance()[2] == "id-1"
    assert playlist.advance() is LIVE
    assert playlist.back()[2] == "id-1"


def test_the_loop_ending_drops_the_live_slot_onto_the_newest_item():
    playlist = _grown(2)
    playlist.set_live(False)
    assert playlist.count == 2
    assert playlist.current()[2] == "id-1"


def test_the_loop_ending_with_nothing_finished_empties_the_rotation():
    playlist = AutoGeneratePlaylist()
    playlist.set_live(False)
    assert playlist.count == 0
    assert playlist.current() is None


def test_remove_current_drops_a_finished_item_and_moves_to_the_next():
    playlist = _grown(3)
    playlist.advance()  # wrap onto id-0
    playlist.remove_current()
    assert playlist.current()[2] == "id-1"
    assert playlist.count == 3


def test_removing_the_newest_item_lands_on_the_live_slot():
    playlist = _grown(1)
    playlist.back()  # onto id-0, the only finished item
    playlist.remove_current()
    assert playlist.current() is LIVE


def test_remove_current_is_a_no_op_on_the_live_slot():
    playlist = _grown(1)
    playlist.remove_current()  # sitting on the live slot
    assert playlist.count == 2


def test_lock_holds_the_dwell_and_toggles_off():
    playlist = _grown(1)
    assert playlist.dwell_ms() == 4000  # the live slot dwells like an image
    assert playlist.toggle_lock() is True
    assert playlist.dwell_ms() is None
    playlist.unlock()
    assert not playlist.locked
    assert playlist.dwell_ms() == 4000


def test_finished_videos_advance_on_their_end_not_a_timer():
    playlist = AutoGeneratePlaylist()
    playlist.add_finished("clip.mp4", "video", "id-v", stay_live=True)
    playlist.back()  # onto the video
    assert playlist.dwell_ms() is None
