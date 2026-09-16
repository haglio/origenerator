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


# --- what gives the machine up --------------------------------------------------

def test_a_video_being_rendered_yields_to_the_users_image():
    # Minutes of GPU, most of it already spent, against seconds the user is
    # sitting waiting for: the user's own words for this queue are that their
    # work goes first, whatever it costs a video.
    assert queue_line.yields_to(_video(), _image()) is True


def test_a_video_keeps_the_machine_from_another_video():
    # Asking for a video is asking for "later", whatever is running -- and the
    # start frame of one is the opening of a video, not a picture to wait for.
    assert queue_line.yields_to(_video(), _video()) is False
    assert queue_line.yields_to(_video(), _video_frame()) is False


def test_an_image_being_rendered_yields_to_nothing():
    # Seconds from done: the newcomer waits less than starting over would cost.
    assert queue_line.yields_to(_image(), _image()) is False


def test_a_videos_start_frame_being_drawn_yields_to_nothing():
    # The prompt on the GPU is a still, seconds from done; the video it opens
    # has not started, and joins the line after the image like any video.
    assert queue_line.yields_to(_video_frame(), _image()) is False


def test_nothing_yields_to_work_nobody_asked_for():
    for source in ("experiment", "base_render"):
        assert queue_line.yields_to(_video(), _job("image", source)) is False


def test_an_unclassifiable_running_job_yields_to_nothing():
    # Read as an image (see above), and an image is left to finish.
    assert queue_line.yields_to(SimpleNamespace(), _image()) is False


# --- rejoining the line after being set aside -----------------------------------

def test_a_video_set_aside_rejoins_ahead_of_the_videos_still_waiting():
    # It was in front of them, and the pictures are what it was set aside for.
    assert queue_line.rejoin_index([_image(), _image(), _video(), _video()]) == 2


def test_a_video_set_aside_rejoins_behind_every_picture():
    assert queue_line.rejoin_index([_image()]) == 1
    assert queue_line.rejoin_index([]) == 0


def test_a_video_set_aside_rejoins_ahead_of_a_waiting_videos_start_frame():
    # The frame is the opening of a video asked for later than this one.
    assert queue_line.rejoin_index([_image(), _video_frame()]) == 1
