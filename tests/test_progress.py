from __future__ import annotations

import pytest

from origenerator.progress import (
    ProgressTracker,
    expected_pass_count,
    expected_sampling_seconds,
    sampler_costs,
    stage_names,
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


def _payload(name, **params):
    wf = WORKFLOW_REGISTRY[name]
    return wf.build_api_payload({**wf.default_params(), **params})


def _ids(payload, class_type):
    """The payload's nodes of one class, in insertion order — how a caller of
    these functions finds a pass, since the ids are the graph's own business."""
    return [nid for nid, node in payload.items() if node["class_type"] == class_type]


def test_a_lone_sampler_is_budgeted_at_a_still_step_per_step():
    # Nothing to weigh anything against, so the total is just the step count at
    # the flat cost of a still: what matters here is only that it scales.
    assert expected_sampling_seconds(_payload("flux_t2i_upscaled", steps=30)) == 15
    assert expected_sampling_seconds(_payload("flux_t2i_upscaled", steps=60)) == 30


def test_expected_seconds_sums_the_base_and_enhance_passes():
    # sdxl_t2i's enhance tail runs a second KSampler after the base one; the
    # bar's total covers both, so it ramps once across the whole job.
    payload = _payload("sdxl_t2i", steps=50, enhance=True, enhance_steps=20)
    assert expected_sampling_seconds(payload) == 35   # 50 + 20 still steps


def test_the_audio_pass_is_a_sliver_of_a_video_job_not_most_of_it():
    # The complaint this fixes. A WAN 2.2 I2V run reports 20 video steps and 50
    # audio ones, so counting steps put three quarters of the bar on the audio —
    # and the user watched that three quarters go by in fifteen seconds after the
    # first quarter had taken eleven minutes. Costed, the audio is about 1% of
    # the run, which is what it is.
    costs = sampler_costs(_payload("wan22_i2v", steps=20))
    video = sum(steps * cost for node, (steps, cost) in costs.items() if node in ("15", "16"))
    audio = sum(steps * cost for node, (steps, cost) in costs.items() if node == "24")
    assert audio / (video + audio) < 0.02


def test_a_video_step_is_costed_by_the_length_of_the_clip():
    # Doubling the frames doubles what a step of the same schedule costs, which
    # is what makes one set of numbers fit a five-second clip and a ten-second
    # one. A flat cost per step could only ever be right for one of them.
    short = sampler_costs(_payload("wan22_i2v", steps=8, frame_count=81))["15"]
    long = sampler_costs(_payload("wan22_i2v", steps=8, frame_count=161))["15"]
    assert long[1] == pytest.approx(short[1] * 161 / 81)


def test_every_video_workflow_costs_its_audio_pass_against_its_video_one():
    # The audio sampler's 50 steps are a fixed count, so the shorter the video
    # schedule the more of the bar they used to take: a 4-step loop spent 93% of
    # its reported steps on the pass that takes seconds.
    for name in ("wan22_i2v", "wan22_flf2v_loop", "wan21_ati_i2v"):
        payload = _payload(name, steps=4)
        costs = sampler_costs(payload)
        audio = sum(steps * cost for node, (steps, cost) in costs.items()
                    if payload[node]["class_type"] == "HunyuanFoleySampler")
        total = sum(steps * cost for steps, cost in costs.values())
        assert audio / total < 0.1, name


def test_a_still_workflow_is_costed_flat_having_no_clip_to_measure():
    # No latent builder to read a length off, so every sampler is a still's.
    costs = sampler_costs(_payload("sdxl_t2i", steps=50, enhance=True, enhance_steps=20))
    assert {cost for _, cost in costs.values()} == {0.5}


def test_a_detail_fix_costs_less_per_step_than_the_render_it_patches(enhance_payload):
    # A fix samples one crop enlarged to at most 1024px; the tail it follows
    # samples the whole upscaled render. Charged the same, two fixes would take
    # two thirds of the bar for a fraction of the work.
    payload = enhance_payload(
        enhance_steps=20, enhance_detail_fixes={"faces": 0.45, "hands": 0.5})
    costs = sampler_costs(payload)
    tail_id = _ids(payload, "KSampler")[0]
    tail = costs[tail_id][1]
    assert all(cost < tail for node, (_, cost) in costs.items() if node != tail_id)
    assert expected_sampling_seconds(enhance_payload(
        enhance_steps=20,
        enhance_detail_fixes={"faces": 0.45, "hands": 0.5})) == 16  # 10 + 3 + 3


def test_expected_pass_count_is_one_for_a_lone_sampler():
    # Nothing to split a bar over: this job is one pass from end to end.
    assert expected_pass_count(_payload("flux_t2i_upscaled")) == 1


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
    payload = enhance_payload(
        enhance_steps=20, enhance_detail_fixes={"faces": 0.45, "hands": 0.5})
    tail = _ids(payload, "KSampler")[0]
    faces, hands = _ids(payload, "DetailerForEach")
    tracker = ProgressTracker.for_payload(payload)
    assert tracker.update(20, 20, tail) == (10, 16)   # the upscale tail finishes
    assert tracker.update(1, 20, faces) == (10, 16)   # faces begins from there
    assert tracker.update(20, 20, faces) == (13, 16)
    assert tracker.update(1, 20, hands) == (13, 16)   # and so does hands
    assert tracker.update(20, 20, hands) == (16, 16)


def test_a_second_region_widens_the_total_rather_than_pinning_the_bar(enhance_payload):
    # The one dip left: a detector that finds two hands runs a pass nobody
    # budgeted. The bar rescales to admit it — which says there is more to do —
    # rather than sitting at 100% through it. The node names itself the same both
    # times, so what marks the second region is its count starting over.
    payload = enhance_payload(
        enhance_steps=20, enhance_detail_fixes={"faces": 0.45, "hands": 0.5})
    tail = _ids(payload, "KSampler")[0]
    faces, hands = _ids(payload, "DetailerForEach")
    tracker = ProgressTracker.for_payload(payload)
    for node in (tail, faces, hands):           # tail, faces, the first hand
        tracker.update(1, 20, node)
        tracker.update(20, 20, node)
    assert tracker.update(1, 20, hands) == (16, 19)   # a second hand turns up
    assert tracker.update(20, 20, hands) == (19, 19)


def test_two_passes_of_unequal_cost_are_told_apart_by_the_node_they_name():
    # Both report 20 steps, and one is worth four of the other. Without the node
    # id there is nothing in the events to say which is which — a count that runs
    # 1..20 twice looks the same either way round.
    tracker = ProgressTracker(100, passes=2, step_seconds={"a": 4.0, "b": 1.0})
    assert tracker.update(20, 20, "a") == (80, 100)
    assert tracker.update(20, 20, "b") == (100, 100)


def test_each_sampler_pass_is_named_by_what_its_node_is_set_to_do():
    # A WAN pair splits one schedule between its experts, and the names are the
    # ones the app's own form uses for them ("Model (High)", "Shift (High)"). The
    # audio pass that scores the clip is the third.
    names = stage_names(_payload("wan22_i2v", steps=20))
    assert (names["15"], names["16"], names["24"]) == ("High noise", "Low noise", "Audio")


def test_a_stills_second_sampler_is_named_for_the_denoise_that_marks_it(enhance_payload):
    # The base render denoises from scratch; the tail that follows it re-samples
    # what is already there, which is the whole difference between them.
    stills = _payload("sdxl_t2i", steps=50, enhance=True)
    render, enhance = _ids(stills, "KSampler")
    names = stage_names(stills)
    assert (names[render], names[enhance]) == ("Render", "Enhance")
    fixed = enhance_payload(enhance_detail_fixes={"faces": 0.45, "hands": 0.5})
    fixes = stage_names(fixed)
    tail = _ids(fixed, "KSampler")[0]
    assert [fixes[tail], *(fixes[n] for n in _ids(fixed, "DetailerForEach"))] == [
        "Enhance", "Detail fix", "Detail fix"]


def test_the_minutes_before_the_first_step_are_named_too():
    # The complaint this answers: over a minute of a WAN run goes by with two
    # 14B models coming off disk, no sampler started, and — before these — not a
    # word on screen about what was happening.
    names = stage_names(_payload("wan22_i2v", steps=20))
    assert names["4"] == "Loading models"    # the high-noise UNET, off disk
    assert names["10"] == "Reading the prompt"
    assert names["12"] == "Loading the image"
    assert names["14"] == "Preparing the clip"
    assert names["17"] == "Decoding frames"
    assert names["19"] == "Writing the video"


def test_a_node_with_nothing_worth_saying_is_left_unnamed():
    # Naming an instantaneous node would flash a word between two real stages;
    # absent, the caption keeps the last thing it said.
    payload = _payload("wan22_i2v", steps=20)
    named = stage_names(payload)
    assert "8" not in named    # ModelSamplingSD3, a setting applied in no time
    assert "21" not in named   # GetImageSize, likewise


def test_current_pass_reads_the_pass_in_hand_on_its_own_count():
    # The lower band: it restarts per pass and counts steps, which is exactly
    # what the reading above it must not do.
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


def test_an_unbudgeted_pass_is_charged_at_the_cheapest_rate_the_job_knows():
    # A node this app has never sized reports 200 steps. Charged at the video
    # rate it would bury the run it interrupted; charged at the cheapest pass's
    # rate it widens the bar a little and the tail creeps, which is the way round
    # that costs less to be wrong about.
    tracker = ProgressTracker(90, passes=2, step_seconds={"a": 40.0, "b": 0.1})
    tracker.update(2, 2, "a")                    # the budgeted pass finishes
    assert tracker.update(1, 200, "?") == (80, 100)
    assert tracker.update(200, 200, "?") == (100, 100)


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
    tracker = ProgressTracker.for_payload(_payload("wan22_i2v", steps=20))
    # Second pass continues from where the first ended, proving it measured the
    # whole 20-step schedule...
    tracker.update(10, 10, "15")
    assert tracker.update(1, 10, "16") == (446, 818)
    # ...and the audio pass that follows has a sliver of the bar left to climb,
    # not the three quarters its step count would have claimed.
    tracker.update(10, 10, "16")
    assert tracker.update(1, 50, "24") == (810, 818)
    assert tracker.update(50, 50, "24") == (818, 818)


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


def test_a_snapshot_from_when_the_bar_counted_steps_is_not_resumed():
    # Its banked figure is a step count, and there is no honest way to read one
    # against a total of seconds: a job caught mid-run by the upgrade takes its
    # position from ComfyUI's next push instead of wearing a wrong one to the end.
    resumed = ProgressTracker.for_payload(_payload("wan22_i2v", steps=20))
    resumed.restore({"total": 70, "banked": 10, "stage_max": 10, "last_value": 3})
    assert resumed.current() == (0, 818)
    assert resumed.update(4, 10, "15") == (162, 818)


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
