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
    return _job("image", name=name, run="video")


def test_an_image_joins_the_front():
    line = [_video(), _video()]
    assert queue_line.insertion_index(line, _image()) == 0, (
        "an image is seconds of the graphics card, and usually the thing being waited for")


def test_a_video_joins_the_back():
    line = [_image(), _video()]
    assert queue_line.insertion_index(line, _video()) == 2, (
        "a video is minutes of the graphics card, and asking for one means later")


def test_a_videos_start_frame_joins_the_back_though_it_draws_a_still():
    line = [_image(), _image()]
    assert queue_line.is_video(_video_frame()) is True
    assert queue_line.insertion_index(line, _video_frame()) == 2


def test_images_stack_newest_first():
    line = []
    for job in (older := _image("older"), newer := _image("newer")):
        line.insert(queue_line.insertion_index(line, job), job)
    assert line == [newer, older], (
        "the user asks for a variation while looking at the one before it, so the last asked for is "
        "the one wanted next")


def test_work_nobody_asked_for_never_jumps_the_line():
    line = [_video()]
    for source in ("experiment", "base_render"):
        assert queue_line.insertion_index(line, _job("image", source)) == 1, (
            "there can be a great many such jobs, and the user asked for none of them")


def test_what_is_put_first_leads_the_line_and_each_part_keeps_its_order():
    newest, locked, older, video, also_locked = (
        _image("newest"), _image("locked"), _image("older"), _video("video"),
        _image("also locked"))
    line = [newest, locked, older, video, also_locked]

    queue_line.put_first(line, {"locked", "also locked"})

    assert line == [locked, also_locked, newest, older, video]


def test_an_unclassifiable_job_is_treated_as_an_image():
    bare = SimpleNamespace()
    assert queue_line.is_video(bare) is False, (
        "images go first and start sooner, so guessing image is the harmless way to be wrong")
    assert queue_line.insertion_index([_video()], bare) == 0


def test_the_users_image_work_takes_the_machine_from_whatever_is_rendering():
    assert queue_line.takes_the_front(_image()) is True


def test_a_video_asked_for_takes_the_machine_from_nothing():
    assert queue_line.takes_the_front(_video()) is False
    assert queue_line.takes_the_front(_video_frame()) is False


def test_work_nobody_asked_for_takes_the_machine_from_nothing():
    for source in ("experiment", "base_render"):
        assert queue_line.takes_the_front(_job("image", source)) is False


def test_a_video_set_aside_rejoins_after_the_last_image():
    newcomer = _image("new")
    line = [newcomer, _image("older"), _video(), _video()]
    assert queue_line.rejoin_index(line, _video(), newcomer) == 2


def test_a_video_set_aside_rejoins_after_an_image_a_video_was_dragged_above():
    newcomer = _image("new")
    line = [newcomer, _video(), _image("older")]
    assert queue_line.rejoin_index(line, _video(), newcomer) == 3


def test_a_videos_start_frame_set_aside_rejoins_with_the_videos():
    newcomer = _image("new")
    assert queue_line.rejoin_index([newcomer, _video()], _video_frame(), newcomer) == 1


def test_an_image_set_aside_rejoins_right_after_the_image_that_took_its_place():
    newcomer = _image("new")
    line = [newcomer, _image("older"), _video()]
    assert queue_line.rejoin_index(line, _image(), newcomer) == 1


def test_an_image_set_aside_for_a_newcomer_no_longer_in_line_takes_the_front():
    assert queue_line.rejoin_index([_image("older")], _image(), _image("gone")) == 0


def test_work_nobody_asked_for_set_aside_rejoins_at_the_back():
    newcomer = _image("new")
    line = [newcomer, _video()]
    for source in ("experiment", "base_render"):
        assert queue_line.rejoin_index(line, _job("image", source), newcomer) == 2


def test_a_video_waits_until_a_minute_after_the_last_image_asked_for():
    assert queue_line.wait_before_starting(_video(), seconds_since_an_image=10) == 50, (
        "started within the minute, a video is set aside by the next image, its render thrown away "
        "and that image slowed by the switch; or, shielded, it keeps that image waiting")


def test_an_image_never_waits():
    assert queue_line.wait_before_starting(_image(), seconds_since_an_image=10) == 0


def test_a_video_waits_no_longer_once_the_minute_is_up():
    assert queue_line.wait_before_starting(_video(), seconds_since_an_image=75) == 0


def test_a_video_waits_for_nothing_before_any_image_is_asked_for():
    assert queue_line.wait_before_starting(_video(), seconds_since_an_image=None) == 0


def test_a_videos_start_frame_waits_with_the_videos():
    assert queue_line.wait_before_starting(_video_frame(), seconds_since_an_image=10) == 50


def _enhance(image, name=""):
    return SimpleNamespace(media_type="image", source="generated", prompt_id=name,
                           run_media_type="image", start_image=image, enhances=image)


def _video_from(image, name=""):
    return SimpleNamespace(media_type="video", source="generated", prompt_id=name,
                           run_media_type="video", start_image=image, enhances="")


def test_a_job_moved_lands_just_ahead_of_the_one_it_is_let_go_over():
    first, second, third = _video("first"), _video("second"), _video("third")

    assert queue_line.moved([first, second, third], third, second) == [first, third, second]


def test_a_job_let_go_past_the_last_one_ends_the_line():
    first, second, third = _video("first"), _video("second"), _video("third")

    assert queue_line.moved([first, second, third], first, None) == [second, third, first]


def test_a_video_moved_ahead_of_its_images_enhancement_takes_the_enhancement_along():
    other, enhance = _video("other"), _enhance("p.png", "enhance")
    video = _video_from("p.png", "video")

    assert queue_line.moved([other, enhance, video], video, other) == [enhance, video, other]


def test_an_enhancement_moved_behind_the_videos_waiting_for_it_takes_them_along():
    enhance, other = _enhance("p.png", "enhance"), _video("other")
    first, second = _video_from("p.png", "first"), _video_from("p.png", "second")

    assert queue_line.moved([enhance, first, second, other], enhance, None) == [
        other, enhance, first, second]
