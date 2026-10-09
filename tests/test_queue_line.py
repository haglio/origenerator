"""The queue's rules: where a job joins the line, and where one set aside rejoins it."""
from __future__ import annotations

from types import SimpleNamespace

from origenerator import queue_line


def _job(media_type="image", source="generated", name="", run=None):
    return SimpleNamespace(media_type=media_type, source=source, prompt_id=name,
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


def test_what_is_put_first_leads_the_line_and_each_part_keeps_its_order():
    newest, locked, older, video, also_locked = (
        _image("newest"), _image("locked"), _image("older"), _video("video"),
        _image("also locked"))
    line = [newest, locked, older, video, also_locked]

    queue_line.put_first(line, {"locked", "also locked"})

    assert line == [locked, also_locked, newest, older, video]


# --- a job that declares nothing ----------------------------------------------

def test_an_unclassifiable_job_is_treated_as_an_image():
    # Images go first and start sooner, so this is the harmless way to be wrong.
    bare = SimpleNamespace()
    assert queue_line.is_video(bare) is False
    assert queue_line.insertion_index([_video()], bare) == 0


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
