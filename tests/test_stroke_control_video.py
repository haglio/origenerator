from pathlib import Path

import pytest

from origenerator.workflows import stroke_control_video as scv


def test_marker_positions_ride_the_plan_and_sway_the_anchor():
    # The primary marker rides the plan's series (resampled onto the frame
    # count) at the stroke column; the secondary echoes 15% of the primary's
    # travel from the stroke top, down at the anchor — synchronized, so the
    # pair reads as two hands in one rhythm.
    series = [100.0, 150.0, 200.0]
    positions = scv.control_marker_positions(
        series, stroke_x=50.0, stroke_top=100.0, anchor_x=40.0, anchor_y=300.0,
        frame_count=3,
    )
    assert [p for p, _ in positions] == [(50.0, 100.0), (50.0, 150.0), (50.0, 200.0)]
    assert [s for _, s in positions] == [
        (40.0, 300.0), (40.0, pytest.approx(307.5)), (40.0, pytest.approx(315.0))
    ]


def test_marker_positions_resample_the_fixed_series_onto_any_frame_count():
    series = [float(v) for v in range(121)]
    five = scv.control_marker_positions(series, 0, 0, 0, 0, frame_count=5)
    assert [p[1] for p, _ in five] == [0.0, 30.0, 60.0, 90.0, 120.0]
    one = scv.control_marker_positions(series, 0, 0, 0, 0, frame_count=1)
    assert [p[1] for p, _ in one] == [0.0]  # a single frame sits at the start


def test_render_is_content_addressed_and_idempotent(tmp_path, monkeypatch):
    # The same inputs name the same file and skip the encode; different inputs
    # name a different file. The encode itself is faked — its contract is just
    # "dest exists afterward".
    monkeypatch.setattr(scv, "COMFYUI_INPUT_DIR", tmp_path)
    encodes = []

    def fake_encode(pattern, rate, dest):
        encodes.append(dest)
        Path(dest).write_bytes(b"v")

    monkeypatch.setattr(scv, "_encode", fake_encode)
    positions = scv.control_marker_positions([1.0, 2.0], 5, 1, 4, 9, frame_count=2)

    first = scv.render_control_video(positions, 32, 64, 16.0)
    again = scv.render_control_video(positions, 32, 64, 16.0)
    assert first == again
    assert len(encodes) == 1                  # second call reused the file
    assert first.parent == tmp_path / "stroke_control"

    other = scv.render_control_video(positions, 32, 64, 24.0)
    assert other != first                     # any input change renames
    assert len(encodes) == 2
