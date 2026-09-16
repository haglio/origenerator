"""The queue's rules: where a job joins the line, and which one may start."""
from __future__ import annotations

from types import SimpleNamespace

from origenerator import queue_line


def _job(media_type="image", source="generated", name="", run=None):
    return SimpleNamespace(media_type=media_type, source=source, name=name,
                           run_media_type=run or media_type)


def _image(name=""):
    return _job("image", name=name)


def _video(name=""):
    return _job("video", name=name)


def _video_frame(name=""):
    """A chained i2v's start frame: an image prompt opening a video run."""
    return _job("image", name=name, run="video")


# --- joining the line ---------------------------------------------------------

def test_an_image_joins_the_front():
    line = [_video(), _video()]
    assert queue_line.insertion_index(line, _image()) == 0


def test_a_video_joins_the_back():
    line = [_image(), _video()]
    assert queue_line.insertion_index(line, _video()) == 2


def test_a_videos_start_frame_joins_the_back_though_it_draws_a_still():
    # Asking for a video is asking for minutes of GPU whichever prompt goes
    # first. Placed by what its own prompt makes, the frame would take the very
    # front and land the whole run ahead of every picture already waiting.
    line = [_image(), _image()]
    assert queue_line.is_video(_video_frame()) is True
    assert queue_line.insertion_index(line, _video_frame()) == 2


def test_a_show_holds_a_video_run_from_its_start_frame():
    # The frame is seconds of GPU, but the video after it cannot start while the
    # show plays, so drawing it in front of the show buys nothing.
    assert queue_line.next_ready([_video_frame()], videos_held=True) is None


def test_images_stack_newest_first():
    # Each new picture takes the front, so the last one asked for is next: it was
    # asked for while looking at the one before it.
    line = []
    for job in (older := _image("older"), newer := _image("newer")):
        line.insert(queue_line.insertion_index(line, job), job)
    assert line == [newer, older]


def test_work_nobody_asked_for_never_jumps_the_line():
    # A background experiment or a base re-render makes images too, and there can
    # be a great many of them.
    line = [_video()]
    for source in ("experiment", "base_render"):
        assert queue_line.insertion_index(line, _job("image", source)) == 1


# --- what may start now -------------------------------------------------------

def test_the_front_of_the_line_starts_when_nothing_is_held():
    head = _video()
    assert queue_line.next_ready([head, _image()], videos_held=False) is head


def test_an_empty_line_starts_nothing():
    assert queue_line.next_ready([], videos_held=False) is None
    assert queue_line.next_ready([], videos_held=True) is None


def test_a_held_video_is_passed_over_for_the_image_behind_it():
    # "Sent to the end": passing it over has exactly that effect, since
    # everything that can start goes first — and it keeps its place among the
    # videos for when the show ends.
    image = _image()
    assert queue_line.next_ready([_video(), image], videos_held=True) is image


def test_a_line_of_nothing_but_held_videos_starts_nothing():
    # The queue waits, the GPU stays out of the show's way, and the next image
    # asked for is what starts it moving again.
    assert queue_line.next_ready([_video(), _video()], videos_held=True) is None


def test_holding_videos_never_holds_an_image():
    image = _image()
    assert queue_line.next_ready([image, _video()], videos_held=True) is image


# --- saying what is held ------------------------------------------------------

def test_held_back_names_the_videos_a_show_is_holding():
    videos = [_video(), _video()]
    line = [_image(), *videos]
    assert queue_line.held_back(line, videos_held=True) == videos


def test_nothing_is_held_back_with_no_show_playing():
    assert queue_line.held_back([_video(), _image()], videos_held=False) == []


# --- a job that declares nothing ----------------------------------------------

def test_an_unclassifiable_job_is_treated_as_an_image():
    # Images go first and start sooner, so this is the harmless way to be wrong:
    # calling it a video could hold it back through a whole slideshow.
    bare = SimpleNamespace()
    assert queue_line.is_video(bare) is False
    assert queue_line.next_ready([bare], videos_held=True) is bare


# --- what takes the machine ------------------------------------------------------

def test_the_users_image_work_takes_the_machine_from_whatever_is_rendering():
    # Seconds the user is sitting waiting for, against anything already on the
    # GPU: the user's own words for this queue are that their work goes first
    # while they are working, whatever that costs the run under way.
    assert queue_line.takes_the_front(_image()) is True


def test_a_video_asked_for_takes_the_machine_from_nothing():
    # Asking for a video is asking for "later" -- and the start frame of one is
    # the opening of a video, not a picture to wait for.
    assert queue_line.takes_the_front(_video()) is False
    assert queue_line.takes_the_front(_video_frame()) is False


def test_work_nobody_asked_for_takes_the_machine_from_nothing():
    for source in ("experiment", "base_render"):
        assert queue_line.takes_the_front(_job("image", source)) is False


# --- rejoining the line after being set aside -----------------------------------

def test_a_video_set_aside_rejoins_after_the_last_picture():
    # Ahead of the videos still waiting, which it was in front of, and after
    # every picture and enhancement, which are what it was set aside for.
    newcomer = _image("new")
    line = [newcomer, _image("older"), _video(), _video()]
    assert queue_line.rejoin_index(line, _video(), newcomer) == 2


def test_a_video_set_aside_rejoins_after_a_picture_a_video_was_dragged_above():
    # "Not above any other image or enhancement" outranks "top of the videos".
    newcomer = _image("new")
    line = [newcomer, _video(), _image("older")]
    assert queue_line.rejoin_index(line, _video(), newcomer) == 3


def test_a_videos_start_frame_set_aside_rejoins_with_the_videos():
    newcomer = _image("new")
    assert queue_line.rejoin_index([newcomer, _video()], _video_frame(), newcomer) == 1


def test_a_picture_set_aside_rejoins_right_after_the_picture_that_took_its_place():
    # It was the front until the newcomer took it, so it stays ahead of the
    # pictures asked for before it, as newest-first already had it.
    newcomer = _image("new")
    line = [newcomer, _image("older"), _video()]
    assert queue_line.rejoin_index(line, _image(), newcomer) == 1


def test_a_picture_set_aside_for_a_newcomer_no_longer_in_line_takes_the_front():
    assert queue_line.rejoin_index([_image("older")], _image(), _image("gone")) == 0


def test_work_nobody_asked_for_set_aside_rejoins_at_the_back():
    # A repair from the last absence, caught rendering, goes back to where it
    # joined: after everything the user asked for.
    newcomer = _image("new")
    line = [newcomer, _video()]
    for source in ("experiment", "base_render"):
        assert queue_line.rejoin_index(line, _job("image", source), newcomer) == 2
