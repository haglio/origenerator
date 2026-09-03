import pytest

from origenerator.progress import (
    ProgressTracker, expected_pass_count, expected_progress_steps,
)
from origenerator.workflows import WORKFLOW_REGISTRY, detail_parts


@pytest.fixture
def enhance_payload(monkeypatch):
    """Builds ``image_enhance`` payloads — the multi-pass run, and the one the
    detail fixes belong to.

    The detectors are stood in for: a part with no installed detector builds no
    pass at all, so what the suite's machine happens to have under ComfyUI would
    otherwise decide how many passes these budget.
    """
    monkeypatch.setattr(detail_parts, "list_detector_files",
                        lambda: ["face_yolov8m.pt", "hand_yolov8s.pt"])
    wf = WORKFLOW_REGISTRY["image_enhance"]

    def build(**params):
        return wf.build_api_payload({**wf.default_params(), **params})

    return build


def test_expected_steps_single_ksampler_is_its_step_count():
    wf = WORKFLOW_REGISTRY["flux_t2i_upscaled"]
    payload = wf.build_api_payload({**wf.default_params(), "steps": 30})
    assert expected_progress_steps(payload) == 30


def test_expected_steps_sums_the_base_and_enhance_passes():
    # sdxl_t2i's enhance tail runs a second KSampler after the base one; the
    # bar's total covers both, so it ramps once across the whole job.
    payload = WORKFLOW_REGISTRY["sdxl_t2i"].build_api_payload(
        {**WORKFLOW_REGISTRY["sdxl_t2i"].default_params(),
         "steps": 50, "enhance": True, "enhance_steps": 20}
    )
    assert expected_progress_steps(payload) == 70


def test_expected_steps_dual_sampler_sums_the_two_passes():
    # WAN i2v splits the step schedule across a high- and low-noise sampler; the
    # two passes together run `steps`. On top of that comes the 50-step audio
    # pass that scores the video — the larger half of the run, and the half a
    # total of 20 used to leave the bar pinned at 100% for.
    wf = WORKFLOW_REGISTRY["wan22_i2v"]
    payload = wf.build_api_payload({**wf.default_params(), "steps": 20})
    assert expected_progress_steps(payload) == 70


def test_expected_steps_counts_the_audio_pass_of_every_video_workflow():
    # The bug this guards: the audio sampler's 50 steps are a fixed cost, so the
    # shorter the video schedule the more of the run the bar was blind to. A
    # 4-step loop spent 93% of its reported steps outside its own total.
    for name in ("wan22_i2v", "wan22_flf2v_loop", "wan21_ati_i2v"):
        wf = WORKFLOW_REGISTRY[name]
        payload = wf.build_api_payload({**wf.default_params(), "steps": 4})
        assert expected_progress_steps(payload) == 54, name


def test_expected_steps_budgets_each_detail_fix_at_one_region(enhance_payload):
    # An enhance that fixes faces and hands runs three sampler passes: the tail,
    # then a detailer per part. How many regions each detailer finds isn't
    # knowable up front, but one is — and budgeting that floor is what keeps the
    # bar from filling and emptying once per fix.
    payload = enhance_payload(
        enhance_steps=20, enhance_detail_fixes={"faces": 0.45, "hands": 0.5})
    assert expected_progress_steps(payload) == 60


def test_expected_pass_count_is_one_for_a_lone_sampler():
    # Nothing to split a bar over: this job is one pass from end to end.
    wf = WORKFLOW_REGISTRY["flux_t2i_upscaled"]
    assert expected_pass_count(wf.build_api_payload(wf.default_params())) == 1


def test_expected_pass_count_counts_the_tail_and_each_fix(enhance_payload):
    payload = enhance_payload(enhance_detail_fixes={"faces": 0.45, "hands": 0.5})
    assert expected_pass_count(payload) == 3
    # A detailer counts once however many regions it goes on to sample: the
    # extra ones are found by a detector, not budgeted by anyone.
    assert expected_pass_count(enhance_payload(enhance_detail_fixes={})) == 1


def test_the_bar_does_not_refill_once_per_fix(enhance_payload):
    # The complaint this fixes: a multi-fix enhance used to fill to 100%, snap
    # back near zero and fill again for every fix, so one job read as a queue of
    # them. Each pass now starts where the last ended.
    tracker = ProgressTracker.for_payload(enhance_payload(
        enhance_steps=20, enhance_detail_fixes={"faces": 0.45, "hands": 0.5}))
    assert tracker.update(20, 20) == (20, 60)   # the upscale tail finishes: a third
    assert tracker.update(1, 20) == (21, 60)    # faces begins from there, not from 1/60
    assert tracker.update(20, 20) == (40, 60)
    assert tracker.update(1, 20) == (41, 60)    # and so does hands
    assert tracker.update(20, 20) == (60, 60)


def test_a_second_region_widens_the_total_rather_than_pinning_the_bar(enhance_payload):
    # The one dip left: a detector that finds two hands runs a pass nobody
    # budgeted. The bar rescales to admit it — which says there is more to do —
    # rather than sitting at 100% through it.
    tracker = ProgressTracker.for_payload(enhance_payload(
        enhance_steps=20, enhance_detail_fixes={"faces": 0.45, "hands": 0.5}))
    for _ in range(3):                          # tail, faces, the first hand
        tracker.update(1, 20)
        tracker.update(20, 20)
    assert tracker.update(1, 20) == (61, 80)    # a second hand turns up
    assert tracker.update(20, 20) == (80, 80)


def test_current_pass_reads_the_pass_in_hand_on_its_own_count():
    # The lower band: it restarts per pass, which is exactly what the reading
    # above it must not do.
    tracker = ProgressTracker(60, passes=3)
    tracker.update(5, 20)
    assert tracker.current_pass() == (5, 20)
    tracker.update(20, 20)
    tracker.update(3, 20)                        # the next pass begins
    assert tracker.current_pass() == (3, 20)     # band back to 3/20...
    assert tracker.current() == (23, 60)         # ...while the run reads 23/60


def test_a_single_pass_run_has_no_band():
    # A band counting the same steps as the bar above it says nothing twice.
    tracker = ProgressTracker(30, passes=1)
    tracker.update(10, 30)
    assert tracker.current_pass() is None


def test_a_band_grows_when_an_unbudgeted_second_pass_turns_up():
    # A run budgeted for one pass that runs two: there IS something to say now,
    # so the band appears rather than staying hidden for the rest of the job.
    tracker = ProgressTracker(20, passes=1)
    tracker.update(10, 10)
    assert tracker.current_pass() is None
    tracker.update(1, 200)
    assert tracker.current_pass() == (1, 200)


def test_no_band_before_the_first_step_or_without_a_recognized_sampler():
    assert ProgressTracker(60, passes=3).current_pass() is None  # nothing reported yet
    unknown = ProgressTracker(0)
    unknown.update(3, 10)
    # Its bar is already showing raw per-node numbers, which ARE this reading.
    assert unknown.current_pass() is None


def test_snapshot_restore_brings_the_band_back_with_the_ramp():
    # A reconnected multi-pass job must show which pass it is in, not a whole
    # bar until its next tick.
    tracker = ProgressTracker(60, passes=3)
    tracker.update(20, 20)
    tracker.update(7, 20)
    resumed = ProgressTracker(60, passes=3)
    resumed.restore(tracker.snapshot())
    assert resumed.current_pass() == (7, 20)
    assert resumed.current() == (27, 60)


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


def test_tracker_widens_the_total_for_a_pass_it_could_not_budget():
    # Some passes can't be counted up front — every region past the first a
    # detailer finds, a tiled upscale sized off the image. Pinning the bar at 100%
    # for the length of one says the job is done when it isn't; the total widens
    # to admit it instead, so the bar keeps moving.
    tracker = ProgressTracker(20)
    tracker.update(10, 10)                        # only budgeted pass finishes
    assert tracker.update(1, 200) == (11, 210)    # a 200-step pass turns up
    assert tracker.update(100, 200) == (110, 210)  # and the bar tracks it
    assert tracker.update(200, 200) == (210, 210)  # ending, correctly, at 100%


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
    # Second pass continues from 10, proving it measured the full 20-step run...
    tracker.update(10, 10)
    assert tracker.update(1, 10) == (11, 70)
    # ...and the audio pass that follows has its own 50 steps of the bar to climb
    # rather than a bar already full.
    tracker.update(10, 10)
    assert tracker.update(1, 50) == (21, 70)
    assert tracker.update(50, 50) == (70, 70)


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
