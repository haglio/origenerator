from origenerator.progress import ProgressTracker, expected_progress_steps
from origenerator.workflows import WORKFLOW_REGISTRY


def test_expected_steps_single_ksampler_is_its_step_count():
    payload = WORKFLOW_REGISTRY["sdxl_t2i"].build_api_payload(
        {**WORKFLOW_REGISTRY["sdxl_t2i"].default_params(), "steps": 50}
    )
    assert expected_progress_steps(payload) == 50


def test_expected_steps_dual_sampler_sums_the_two_passes():
    # WAN i2v splits the step schedule across a high- and low-noise sampler; the
    # two passes together run `steps`, which is what ComfyUI reports in total.
    wf = WORKFLOW_REGISTRY["wan22_i2v"]
    payload = wf.build_api_payload({**wf.default_params(), "steps": 20})
    assert expected_progress_steps(payload) == 20


def test_tracker_single_stage_reports_value_over_total():
    tracker = ProgressTracker(50)
    assert tracker.update(1, 50) == (1, 50)
    assert tracker.update(25, 50) == (25, 50)
    assert tracker.update(50, 50) == (50, 50)


def test_tracker_second_stage_continues_instead_of_resetting():
    # The heart of the fix: a two-pass job (10 + 10 steps). When the second pass
    # restarts its own count at 1, the bar must read 11/20, not snap back to 1/20.
    tracker = ProgressTracker(20)
    assert tracker.update(1, 10) == (1, 20)     # first pass begins
    assert tracker.update(10, 10) == (10, 20)   # first pass ends at the halfway mark
    assert tracker.update(1, 10) == (11, 20)    # second pass carries on, no reset
    assert tracker.update(10, 10) == (20, 20)   # and finishes at 100%


def test_tracker_clamps_progress_past_the_total_to_100_percent():
    # A post-sampling node (e.g. video encoding) can emit its own progress after
    # the samplers are done. Rather than overshoot, the bar sits pinned at 100%.
    tracker = ProgressTracker(20)
    tracker.update(10, 10)          # only pass finishes
    assert tracker.update(1, 200) == (11, 20)   # encoding starts, still climbing
    assert tracker.update(200, 200) == (20, 20)  # clamped, never past total


def test_tracker_unknown_total_passes_raw_numbers_through():
    # No sampler was recognized, so there's nothing to normalize against: report
    # ComfyUI's raw per-node numbers rather than a bogus percentage.
    tracker = ProgressTracker(0)
    assert tracker.update(3, 10) == (3, 10)
    assert tracker.update(1, 8) == (1, 8)


def test_tracker_for_payload_sizes_itself_from_the_workflow():
    wf = WORKFLOW_REGISTRY["wan22_i2v"]
    payload = wf.build_api_payload({**wf.default_params(), "steps": 20})
    tracker = ProgressTracker.for_payload(payload)
    # Second pass continues from 10, proving it measured the full 20-step run.
    tracker.update(10, 10)
    assert tracker.update(1, 10) == (11, 20)


def test_snapshot_restore_resumes_a_multi_stage_ramp_across_a_restart():
    # The persistence path: a two-pass job (10 + 10) part-way through its SECOND
    # pass. Snapshotting and restoring into a fresh tracker (an app restart) must
    # continue the ramp — the next tick reads 14/20, not 4/20 as a tracker that
    # forgot the banked first pass would.
    tracker = ProgressTracker(20)
    tracker.update(10, 10)          # first pass done -> banks 10
    tracker.update(3, 10)           # second pass at 3 -> 13/20
    assert tracker.current() == (13, 20)

    resumed = ProgressTracker(20)
    resumed.restore(tracker.snapshot())
    assert resumed.current() == (13, 20)         # seeds the bar at its last spot
    assert resumed.update(4, 10) == (14, 20)     # and carries on, not back to 4/20


def test_snapshot_is_json_serializable():
    import json
    tracker = ProgressTracker(20)
    tracker.update(10, 10)
    tracker.update(3, 10)
    snap = tracker.snapshot()
    assert json.loads(json.dumps(snap)) == snap  # it rides on the row as text


def test_current_is_zero_when_total_is_unknown():
    # No recognized sampler: nothing to seed a percentage from.
    assert ProgressTracker(0).current() == (0, 0)
