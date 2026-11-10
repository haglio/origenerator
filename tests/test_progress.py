from __future__ import annotations

import json

import pytest

from origenerator.progress import (
    SAME_PASS_AS_BEFORE,
    ProgressTracker,
    expected_pass_count,
    expected_sampling_seconds,
    sampler_costs,
    stage_names,
)
from origenerator.workflows import WORKFLOW_REGISTRY, detail_parts


@pytest.fixture
def enhance_payload(monkeypatch):
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
    return [nid for nid, node in payload.items() if node["class_type"] == class_type]


def test_a_lone_sampler_is_budgeted_at_a_still_step_per_step():
    assert expected_sampling_seconds(_payload("flux_t2i_upscaled", steps=30)) == 15, (
        "30 steps at a still's flat half second: with nothing to weigh a lone sampler against, "
        "all that matters is that the total doubles with the steps")
    assert expected_sampling_seconds(_payload("flux_t2i_upscaled", steps=60)) == 30


def test_expected_seconds_sums_the_base_and_enhance_passes():
    payload = _payload("sdxl_t2i", steps=50, enhance=True, enhance_steps=20)
    assert expected_sampling_seconds(payload) == 35, (
        "50 base steps and 20 enhance steps, each at a still's half second")


def test_the_audio_pass_is_a_sliver_of_a_video_job_not_most_of_it():
    costs = sampler_costs(_payload("wan22_i2v", steps=20))
    video = sum(steps * cost for node, (steps, cost) in costs.items() if node in ("15", "16"))
    audio = sum(steps * cost for node, (steps, cost) in costs.items() if node == "24")
    assert audio / (video + audio) < 0.02


def test_a_video_step_is_costed_by_the_length_of_the_video():
    short = sampler_costs(_payload("wan22_i2v", steps=8, frame_count=81))["15"]
    long = sampler_costs(_payload("wan22_i2v", steps=8, frame_count=161))["15"]
    assert long[1] == pytest.approx(short[1] * 161 / 81), (
        "the costs are seconds measured off this app's own finished runs and only ever read "
        "against each other: a bar needs the ratio between the passes of one job, and a faster "
        "or slower graphics card moves every one of them together")


def test_every_video_workflow_costs_its_audio_pass_against_its_video_one():
    for name in ("wan22_i2v", "wan22_flf2v_loop"):
        payload = _payload(name, steps=4)
        costs = sampler_costs(payload)
        audio = sum(steps * cost for node, (steps, cost) in costs.items()
                    if payload[node]["class_type"] == "HunyuanFoleySampler")
        total = sum(steps * cost for steps, cost in costs.values())
        assert audio / total < 0.1, name


def test_a_still_workflow_is_costed_flat_having_no_clip_to_measure():
    costs = sampler_costs(_payload("sdxl_t2i", steps=50, enhance=True, enhance_steps=20))
    assert {cost for _, cost in costs.values()} == {0.5}


def test_a_detail_fix_costs_less_per_step_than_the_render_it_patches(enhance_payload):
    payload = enhance_payload(
        enhance_steps=20, enhance_detail_fixes={"faces": 0.45, "hands": 0.5})
    costs = sampler_costs(payload)
    tail_id = _ids(payload, "KSampler")[0]
    tail = costs[tail_id][1]
    assert all(cost < tail for node, (_, cost) in costs.items() if node != tail_id)
    assert expected_sampling_seconds(enhance_payload(
        enhance_steps=20,
        enhance_detail_fixes={"faces": 0.45, "hands": 0.5})) == 16, (
        "the tail's 20 steps come to 10, and each of the two fixes' cheaper 20 to 3")


def test_expected_pass_count_is_one_for_a_lone_sampler():
    assert expected_pass_count(_payload("flux_t2i_upscaled")) == 1


def test_expected_pass_count_counts_the_tail_and_each_fix(enhance_payload):
    payload = enhance_payload(enhance_detail_fixes={"faces": 0.45, "hands": 0.5})
    assert expected_pass_count(payload) == 3
    assert expected_pass_count(enhance_payload(enhance_detail_fixes={})) == 1


def test_the_bar_does_not_refill_once_per_fix(enhance_payload):
    payload = enhance_payload(
        enhance_steps=20, enhance_detail_fixes={"faces": 0.45, "hands": 0.5})
    tail = _ids(payload, "KSampler")[0]
    faces, hands = _ids(payload, "DetailerForEach")
    tracker = ProgressTracker.for_payload(payload)
    assert tracker.update(20, 20, tail) == (10, 16)
    assert tracker.update(1, 20, faces) == (10, 16)
    assert tracker.update(20, 20, faces) == (13, 16)
    assert tracker.update(1, 20, hands) == (13, 16)
    assert tracker.update(20, 20, hands) == (16, 16)


def test_a_second_region_widens_the_total_rather_than_pinning_the_bar(enhance_payload):
    payload = enhance_payload(
        enhance_steps=20, enhance_detail_fixes={"faces": 0.45, "hands": 0.5})
    tail = _ids(payload, "KSampler")[0]
    faces, hands = _ids(payload, "DetailerForEach")
    tracker = ProgressTracker.for_payload(payload)
    for node in (tail, faces, hands):
        tracker.update(1, 20, node)
        tracker.update(20, 20, node)
    assert tracker.update(1, 20, hands) == (16, 19), (
        "Impact Pack's detailer names the same node for every region it samples, "
        "so a count starting over is a new pass too")
    assert tracker.update(20, 20, hands) == (19, 19)


def test_two_passes_of_unequal_cost_are_told_apart_by_the_node_they_name():
    tracker = ProgressTracker(100, passes=2, step_seconds={"a": 4.0, "b": 1.0})
    assert tracker.update(20, 20, "a") == (80, 100)
    assert tracker.update(20, 20, "b") == (100, 100)


def test_a_step_that_names_no_node_belongs_to_the_pass_already_running():
    tracker = ProgressTracker(100, passes=2, step_seconds={"a": 4.0, "b": 1.0})
    tracker.update(10, 20, "a")

    assert tracker.update(11, 20, SAME_PASS_AS_BEFORE) == (44, 100)


def test_each_sampler_pass_is_named_the_way_the_form_names_it():
    names = stage_names(_payload("wan22_i2v", steps=20))
    assert (names["15"], names["16"], names["24"]) == ("First pass", "Second pass", "Sound")


def test_a_stills_second_sampler_is_named_for_the_denoise_that_marks_it(enhance_payload):
    stills = _payload("sdxl_t2i", steps=50, enhance=True)
    render, enhance = _ids(stills, "KSampler")
    names = stage_names(stills)
    assert (names[render], names[enhance]) == ("Render", "Enhance")
    fixed = enhance_payload(enhance_detail_fixes={"faces": 0.45, "hands": 0.5})
    fixes = stage_names(fixed)
    tail = _ids(fixed, "KSampler")[0]
    assert [fixes[tail], *(fixes[n] for n in _ids(fixed, "DetailerForEach"))] == [
        "Enhance", "Faces fix", "Hands fix"]


def test_the_minutes_before_the_first_step_are_named_too():
    payload = _payload("wan22_i2v", steps=20)
    names = stage_names(payload)
    the_high_noise_model, *_ = _ids(payload, "UNETLoader")
    assert names[the_high_noise_model] == "Loading models"
    assert names["10"] == "Reading the prompt"
    assert names["12"] == "Loading the image"
    assert names["14"] == "Preparing the clip"
    assert names["17"] == "Decoding frames"
    assert names["19"] == "Writing the video"


def test_a_node_with_nothing_worth_saying_is_left_unnamed():
    payload = _payload("wan22_i2v", steps=20)
    named = stage_names(payload)
    instant_nodes = _ids(payload, "ModelSamplingSD3") + _ids(payload, "GetImageSize")
    assert instant_nodes
    for instant in instant_nodes:
        assert instant not in named, "an instant node's name would only flash between two real stages"


def test_current_pass_reads_the_pass_in_hand_on_its_own_count():
    tracker = ProgressTracker(60, passes=3)
    tracker.update(5, 20)
    assert tracker.current_pass() == (5, 20), (
        "shown from the first step, the pass's bar does not appear from nowhere partway through")
    tracker.update(20, 20)
    tracker.update(3, 20)
    assert tracker.current_pass() == (3, 20)
    assert tracker.current() == (23, 60)


def test_a_single_pass_run_has_no_band():
    tracker = ProgressTracker(30, passes=1)
    tracker.update(10, 30)
    assert tracker.current_pass() is None


def test_a_band_grows_when_an_unbudgeted_second_pass_turns_up():
    tracker = ProgressTracker(20, passes=1)
    tracker.update(10, 10)
    assert tracker.current_pass() is None
    tracker.update(1, 200)
    assert tracker.current_pass() == (1, 200)


def test_an_unbudgeted_pass_is_charged_at_the_cheapest_rate_the_job_knows():
    tracker = ProgressTracker(90, passes=2, step_seconds={"a": 40.0, "b": 0.1})
    tracker.update(2, 2, "a")
    assert tracker.update(1, 200, "?") == (80, 100), (
        "charged too dear, a pass nobody budgeted buries the real passes; "
        "too cheap, it only slows the tail")
    assert tracker.update(200, 200, "?") == (100, 100)


def test_no_band_before_the_first_step_or_without_a_recognized_sampler():
    assert ProgressTracker(60, passes=3).current_pass() is None
    unknown = ProgressTracker(0)
    unknown.update(3, 10)
    assert unknown.current_pass() is None


def test_snapshot_restore_brings_the_band_back_with_the_ramp():
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
    tracker = ProgressTracker(20)
    assert tracker.update(1, 10) == (1, 20)
    assert tracker.update(10, 10) == (10, 20)
    assert tracker.update(1, 10) == (11, 20)
    assert tracker.update(10, 10) == (20, 20)


def test_tracker_widens_the_total_for_a_pass_it_could_not_budget():
    tracker = ProgressTracker(20)
    tracker.update(10, 10)
    assert tracker.update(1, 200) == (11, 210)
    assert tracker.update(100, 200) == (110, 210)
    assert tracker.update(200, 200) == (210, 210)


def test_tracker_unknown_total_passes_raw_numbers_through():
    tracker = ProgressTracker(0)
    assert tracker.update(3, 10) == (3, 10)
    assert tracker.update(1, 8) == (1, 8)


def test_tracker_for_payload_sizes_itself_from_the_workflow():
    tracker = ProgressTracker.for_payload(_payload("wan22_i2v", steps=20))
    tracker.update(10, 10, "15")
    assert tracker.update(1, 10, "16") == (446, 818)
    tracker.update(10, 10, "16")
    assert tracker.update(1, 50, "24") == (810, 818)
    assert tracker.update(50, 50, "24") == (818, 818)


def test_snapshot_restore_resumes_a_multi_stage_ramp_across_a_restart():
    tracker = ProgressTracker(20)
    tracker.update(10, 10)
    tracker.update(3, 10)
    assert tracker.current() == (13, 20)

    resumed = ProgressTracker(20)
    resumed.restore(tracker.snapshot())
    assert resumed.current() == (13, 20)
    assert resumed.update(4, 10) == (14, 20)


def test_a_snapshot_from_when_the_bar_counted_steps_is_not_resumed():
    resumed = ProgressTracker.for_payload(_payload("wan22_i2v", steps=20))
    resumed.restore({"total": 70, "banked": 10, "stage_max": 10, "last_value": 3})
    assert resumed.current() == (0, 818)
    assert resumed.update(4, 10, "15") == (162, 818)


def test_snapshot_is_json_serializable():
    tracker = ProgressTracker(20)
    tracker.update(10, 10)
    tracker.update(3, 10)
    snap = tracker.snapshot()
    assert json.loads(json.dumps(snap)) == snap, "it is stored on the job's row as text"


def test_current_is_zero_when_total_is_unknown():
    assert ProgressTracker(0).current() == (0, 0)



def _advanced(steps, start, end):
    return {"1": {"class_type": "KSamplerAdvanced", "inputs": {
        "steps": steps, "start_at_step": start, "end_at_step": end}}}


def test_a_sampler_advanced_reports_only_its_window_of_the_schedule():
    assert sampler_costs(_advanced(20, 0, 8))["1"][0] == 8
    assert sampler_costs(_advanced(20, 8, 10000))["1"][0] == 12


def test_a_sampler_advanced_end_past_the_schedule_means_to_the_end():
    assert sampler_costs(_advanced(20, 0, 10000))["1"][0] == 20


def test_a_detailer_is_budgeted_one_region_of_steps_times_cycles():
    payload = {"1": {"class_type": "DetailerForEach", "inputs": {"steps": 10, "cycle": 2}}}
    assert sampler_costs(payload)["1"][0] == 20
    payload["1"]["inputs"]["cycle"] = 0
    assert sampler_costs(payload)["1"][0] == 10
    payload["1"]["inputs"]["denoise"] = 0.4
    assert sampler_costs(payload)["1"][0] == 10, (
        "Impact Pack's detailer runs exactly its steps whatever the denoise: it widens the schedule "
        "to steps/denoise and slices steps back out of its tail")


def test_a_foley_duration_derived_in_graph_costs_as_one_second_of_audio():
    linked = {"1": {"class_type": "HunyuanFoleySampler",
                    "inputs": {"steps": 5, "duration": ["7", 0]}}}
    one_second = {"1": {"class_type": "HunyuanFoleySampler",
                        "inputs": {"steps": 5, "duration": 1}}}
    assert sampler_costs(linked) == sampler_costs(one_second)


def test_a_video_length_derived_in_graph_sizes_its_samplers_as_stills():
    payload = {
        "1": {"class_type": "WanImageToVideo", "inputs": {
            "length": ["9", 0], "width": 640, "height": 480, "batch_size": 1}},
        "2": {"class_type": "KSampler", "inputs": {"steps": 4}},
    }
    assert sampler_costs(payload)["2"][1] == 0.5


def test_a_job_budgeted_for_under_a_second_still_reports_a_total_of_one():
    tracker = ProgressTracker(0.2, step_seconds={"a": 0.01})
    assert tracker.update(1, 1, node="a") == (0, 1), (
        "a total of nothing means no reading, which shows a sweeping bar on a job that is measuring")


def test_a_snapshot_with_banked_seconds_and_no_pass_index_restores_inside_a_second_pass():
    snapshot = {"total": 60, "banked": 30.0, "stage_max": 20, "stage_seconds": 1.0,
                "last_value": 5, "node": None, "passes": 1}
    tracker = ProgressTracker(60)
    tracker.restore(snapshot)
    assert tracker.current_pass() == (5, 20)


def test_an_audio_step_is_costed_by_the_length_of_the_audio():
    def a_step_over(seconds):
        payload = {"1": {"class_type": "HunyuanFoleySampler", "inputs": {"steps": 5, "duration": seconds}}}
        return sampler_costs(payload)["1"][1]

    assert a_step_over(10) == pytest.approx(2 * a_step_over(5)), (
        "the audio pass diffuses a latent as long as the audio, so its cost follows the length the "
        "way a video step's does")
