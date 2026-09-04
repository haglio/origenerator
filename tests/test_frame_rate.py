from origenerator.workflows.frame_rate import (
    MAX_PLAYBACK_FPS,
    NATIVE_FPS,
    playback_rate,
    rate_multiplier,
)


def test_the_native_rate_needs_no_frames_between_its_frames():
    assert rate_multiplier(NATIVE_FPS) == 1
    assert playback_rate(NATIVE_FPS) == 16.0


def test_a_whole_multiple_of_the_native_rate_is_one_multiplier():
    assert [rate_multiplier(r) for r in (32, 48, 64, 80, 96, 112)] == [2, 3, 4, 5, 6, 7]
    assert [playback_rate(r) for r in (32, 48, 112)] == [32.0, 48.0, 112.0]


def test_a_rate_between_two_multiples_is_written_at_the_nearer_one():
    # The alternative is a file whose frames were interpolated to one rate and
    # whose header claims another, which is the tempo error this replaced: 60
    # fps over frames made for 64 would play at 0.94x.
    assert (rate_multiplier(60), playback_rate(60)) == (4, 64.0)
    assert (rate_multiplier(24), playback_rate(24)) == (2, 32.0)
    assert (rate_multiplier(30), playback_rate(30)) == (2, 32.0)


def test_no_rate_is_faster_than_the_video_writer_will_accept():
    # ComfyUI's CreateVideo refuses an fps over 120 at validation time, before
    # anything runs — the user sees a Generate button that does nothing. So a
    # rate past the ceiling comes back as the ceiling, not as a dead submit.
    assert MAX_PLAYBACK_FPS <= 120.0
    for asked in (113, 120, 128, 240, 10_000):
        assert playback_rate(asked) == MAX_PLAYBACK_FPS
        assert playback_rate(asked) % NATIVE_FPS == 0


def test_a_rate_under_the_native_one_still_plays_at_true_speed():
    # There is no half-rate to interpolate to, and writing 16 fps frames at 8
    # would halve the speed, so the floor is the rate the frames were made at.
    assert (rate_multiplier(8), playback_rate(8)) == (1, 16.0)
    assert (rate_multiplier(0), playback_rate(0)) == (1, 16.0)

