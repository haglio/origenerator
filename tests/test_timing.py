from origenerator.timing import (
    average_label,
    average_seconds,
    clock_duration,
    estimate_label,
    estimate_seconds,
    execution_duration_seconds,
    percent_label,
    progress_status_label,
    progress_time_label,
    queue_estimate_label,
    remaining_label,
    remaining_seconds,
)


def _history(messages):
    return {"status": {"status_str": "success", "completed": True, "messages": messages}}


def test_execution_duration_from_start_and_success_timestamps():
    history = _history([
        ["execution_start", {"prompt_id": "x", "timestamp": 1_000_000}],
        ["execution_cached", {"nodes": [], "prompt_id": "x", "timestamp": 1_000_000}],
        ["execution_success", {"prompt_id": "x", "timestamp": 1_015_260}],
    ])
    assert execution_duration_seconds(history) == 15.26


def test_execution_duration_none_when_no_success_message():
    history = _history([
        ["execution_start", {"prompt_id": "x", "timestamp": 1_000_000}],
    ])
    assert execution_duration_seconds(history) is None


def test_execution_duration_none_when_no_status():
    assert execution_duration_seconds({}) is None


def test_estimate_is_median_resistant_to_outliers():
    # One slow run (GPU busy elsewhere) shouldn't drag the estimate up.
    assert estimate_seconds([10.0, 11.0, 12.0, 200.0]) == 11.5


def test_estimate_none_when_no_history():
    assert estimate_seconds([]) is None


def test_estimate_label_no_data():
    assert estimate_label([]) == "No timing data yet"


def test_estimate_label_seconds_one_run():
    assert estimate_label([11.0]) == "~11 sec (based on 1 run)"


def test_estimate_label_rounds_to_minutes_and_counts_runs():
    # Median 724s reads as a coarse "~12 min", not a false-precise "12 min 4 sec".
    assert estimate_label([700.0, 724.0, 800.0]) == "~12 min (based on 3 runs)"


def test_average_is_the_mean():
    assert average_seconds([10.0, 20.0, 30.0]) == 20.0


def test_average_none_when_empty():
    assert average_seconds([]) is None


def test_average_label_empty_when_no_data():
    # A folder with nothing timed shows no average line at all.
    assert average_label([]) == ""


def test_average_label_is_coarse_with_a_count():
    # Mean of these is ~741s -> a coarse "~12 min".
    assert average_label([700.0, 724.0, 800.0]) == "~12 min (across 3 runs)"


def test_average_label_singular_run():
    assert average_label([6.0]) == "~6 sec (across 1 run)"


# --- the live count on a running job ----------------------------------------

def test_clock_duration_always_shows_the_seconds_ticking():
    # A number the user watches move, so unlike a resting estimate it never
    # rounds the seconds away.
    assert clock_duration(7) == "0:07"
    assert clock_duration(83) == "1:23"
    assert clock_duration(724) == "12:04"


def test_clock_duration_grows_an_hours_field():
    assert clock_duration(3600) == "1:00:00"
    assert clock_duration(4265) == "1:11:05"


def test_clock_duration_floors_a_negative_at_zero():
    assert clock_duration(-5) == "0:00"


def test_remaining_counts_down_from_the_typical_time():
    # Early on, before the run's own pace is worth reading: 724s typical, 100s in.
    assert remaining_seconds(100.0, (1, 20), 724.0) == 624.0


def test_remaining_ignores_the_pace_of_the_first_few_steps():
    # Step one carries the model load, so extrapolating from it would predict a
    # run several times longer than the real one. Only the typical time counts here.
    assert remaining_seconds(60.0, (1, 20), 700.0) == 640.0


def test_remaining_follows_a_run_going_slower_than_usual():
    # 15 of 20 steps in 900s: 300s left by its own pace, while the typical time
    # has already run out. The pace is what's left to believe.
    assert remaining_seconds(900.0, (15, 20), 724.0) == 300.0


def test_remaining_uses_the_pace_alone_with_no_history():
    assert remaining_seconds(200.0, (10, 20), None) == 200.0


def test_remaining_hands_over_to_the_pace_as_the_run_settles():
    # The bug this guards. A run half-done in 90s is on course for 180s of its
    # own, while the workflow's median says 724s — a median over runs of every
    # length, so a weak claim about this one. Half-way through, the estimate sits
    # half-way between the two; by the last steps the run's own pace is what
    # decides, so a run faster than its median stops finishing with minutes still
    # on its clock.
    assert remaining_seconds(90.0, (10, 20), 724.0) == 362.0        # 452 projected
    assert round(remaining_seconds(180.0, (18, 20), 724.0)) == 72   # 252 projected
    assert remaining_seconds(200.0, (20, 20), 724.0) == 0.0         # 200: the pace


def test_remaining_is_zero_through_a_tail_that_reports_no_steps():
    # Every step ComfyUI reports is done and the job is still saving its output.
    # Nothing measures that tail, so the honest reading is zero — which the label
    # says as "finishing" — not the typical time's guess at how long it runs.
    assert remaining_seconds(600.0, (20, 20), 724.0) == 0.0


def test_remaining_is_zero_not_none_once_a_run_is_over_its_time():
    assert remaining_seconds(900.0, (20, 20), 724.0) == 0.0


def test_remaining_is_none_with_nothing_to_go_on():
    assert remaining_seconds(30.0, None, None) is None


def test_progress_time_label_reads_elapsed_and_left():
    # Half the steps done in 83s: the run's own pace is on course for 166s, the
    # workflow's median for 724s, and half-way through the estimate splits them.
    assert progress_time_label(83.0, (10, 20), 724.0) == "1:23 elapsed · ~6:02 left"


def test_progress_time_label_is_elapsed_alone_with_no_estimate():
    assert progress_time_label(83.0, None, None) == "1:23 elapsed"


def test_progress_time_label_says_finishing_rather_than_zero():
    # A run past its usual time with no steps left to pace off: "0:00 left" would
    # read as stuck, and a negative number as broken.
    assert progress_time_label(900.0, (20, 20), 724.0) == "15:00 elapsed · finishing"


def test_progress_time_label_is_empty_before_a_job_starts():
    # A queued job has no elapsed time; a zero counting up beside an unmoved bar
    # would say it was running.
    assert progress_time_label(None, None, 724.0) == ""


def test_a_queued_jobs_estimate_rounds_to_one_unit():
    # The queue's rows are scanned, not studied: "~2 min" is the whole of what a
    # median of past runs can back up, and is what a wait gets added up out of.
    assert queue_estimate_label(126.0) == "~2 min"
    assert queue_estimate_label(41.0) == "~41 sec"


def test_an_untimed_workflow_admits_it_rather_than_guess():
    # A workflow nobody has run yet has nothing to estimate from, and a number
    # invented for that slot would be read as one measured.
    assert queue_estimate_label(None) == "~?"


def test_percent_label_rounds_down_to_a_whole_percent():
    assert percent_label((10, 20)) == "50%"
    assert percent_label((1, 3)) == "33%"
    assert percent_label((20, 20)) == "100%"


def test_percent_label_is_empty_with_nothing_to_read_it_off():
    # A workflow reporting no step counts, or a job before its first tick: "0%"
    # would be a reading, and there isn't one.
    assert percent_label(None) == ""
    assert percent_label((0, 0)) == ""


def test_progress_status_label_leads_with_how_far_along_it_is():
    # The one line every in-flight surface writes across its bar — the strip's
    # queue, the shelf's cards, a folder's re-roll tile — so one run reads the
    # same wherever it is being watched.
    assert progress_status_label(83.0, (10, 20), 724.0) == "50% · 1:23 elapsed · ~6:02 left"


def test_progress_status_label_drops_whichever_half_is_unknown():
    assert progress_status_label(83.0, None, None) == "1:23 elapsed"   # no steps reported
    assert progress_status_label(None, (10, 20), 724.0) == "50%"       # not started yet
    assert progress_status_label(None, None, 724.0) == ""              # neither


def test_the_compact_line_keeps_how_far_along_and_how_much_longer():
    # A gallery tile is a third of the strip's width, and the full line runs half
    # again wider than the tile at the app's own font — so a tile carrying it
    # would elide the countdown away on exactly the long runs worth counting down.
    assert progress_status_label(83.0, (10, 20), 724.0, compact=True) == "50% · ~6:02 left"
    assert progress_status_label(900.0, (20, 20), 724.0, compact=True) == "100% · finishing"
    assert progress_status_label(83.0, None, None, compact=True) == ""


def test_remaining_label_is_the_countdown_on_its_own():
    assert remaining_label(83.0, (10, 20), 724.0) == "~6:02 left"
    assert remaining_label(900.0, (20, 20), 724.0) == "finishing"
    assert remaining_label(83.0, None, None) == ""   # nothing to count down from
    assert remaining_label(None, (10, 20), 724.0) == ""  # not started yet
