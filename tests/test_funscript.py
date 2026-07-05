from pathlib import Path

from origenerator.funscript import (
    ensure_funscript, funscript_path_for, read_actions, synthesize_actions,
    write_funscript,
)


def test_funscript_path_for_swaps_extension():
    assert funscript_path_for(Path("/out/video/wan22_i2v_00001_.mp4")) == Path(
        "/out/video/wan22_i2v_00001_.funscript"
    )
    assert funscript_path_for("clip.webm") == Path("clip.funscript")


def test_synthesize_actions_alternates_extremes_at_half_period():
    # 1 Hz over 2 s → a half-stroke every 500 ms, starting at the bottom.
    actions = synthesize_actions(2.0, hz=1.0, loop=False)
    assert [a["pos"] for a in actions] == [0, 100, 0, 100, 0]
    assert [a["at"] for a in actions] == [0, 500, 1000, 1500, 2000]


def test_synthesize_actions_loop_tiles_seamlessly():
    # A looping clip: the stroke must return to its start position exactly at the end,
    # so it repeats without a jump as the preview loops.
    duration = 21 / 16  # flf2v default: 21 frames at 16 fps
    actions = synthesize_actions(duration, hz=1.2, loop=True)
    assert actions[0]["pos"] == actions[-1]["pos"]
    assert actions[-1]["at"] == round(duration * 1000)
    assert len(actions) % 2 == 1  # an even number of half-strokes → odd point count


def test_synthesize_actions_empty_for_nonpositive_inputs():
    assert synthesize_actions(0.0, hz=1.0, loop=False) == []
    assert synthesize_actions(2.0, hz=0.0, loop=False) == []


def test_write_then_read_round_trips_actions(tmp_path):
    dest = tmp_path / "clip.funscript"
    actions = synthesize_actions(2.0, hz=1.0, loop=False)
    write_funscript(dest, actions)
    assert dest.exists()
    assert read_actions(dest) == actions


def test_read_actions_returns_none_for_missing_or_bad_file(tmp_path):
    assert read_actions(tmp_path / "nope.funscript") is None
    bad = tmp_path / "bad.funscript"
    bad.write_text("not json", encoding="utf-8")
    assert read_actions(bad) is None


def test_ensure_funscript_writes_sidecar_from_probed_duration(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"v")
    dest = ensure_funscript(video, loop=False, hz=1.0, duration_provider=lambda _p: 2.0)
    assert dest == funscript_path_for(video)
    assert read_actions(dest) == synthesize_actions(2.0, hz=1.0, loop=False)


def test_ensure_funscript_skips_when_sidecar_exists(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"v")
    existing = funscript_path_for(video)
    existing.write_text("keep me", encoding="utf-8")
    calls = []
    dest = ensure_funscript(
        video, loop=False, hz=1.0, duration_provider=lambda p: calls.append(p) or 2.0
    )
    assert dest == existing
    assert existing.read_text(encoding="utf-8") == "keep me"  # not overwritten
    assert calls == []  # didn't even probe


def test_ensure_funscript_returns_none_without_a_duration(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"v")
    assert ensure_funscript(video, loop=False, hz=1.0, duration_provider=lambda _p: None) is None
    assert not funscript_path_for(video).exists()
