from origenerator.timing import (
    average_label,
    average_seconds,
    clock_duration,
    estimate_label,
    estimate_seconds,
    execution_duration_seconds,
    progress_time_label,
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


def test_remaining_holds_the_typical_time_through_the_tail():
    # Every sampler step is done but the VAE decode and audio pass aren't — the
    # step count can't see those, so the typical time is what carries the number
    # rather than dropping it to zero while the job visibly keeps working.
    assert remaining_seconds(600.0, (20, 20), 724.0) == 124.0


def test_remaining_is_zero_not_none_once_a_run_is_over_its_time():
    assert remaining_seconds(900.0, (20, 20), 724.0) == 0.0


def test_remaining_is_none_with_nothing_to_go_on():
    assert remaining_seconds(30.0, None, None) is None


def test_progress_time_label_reads_elapsed_and_left():
    # 724s typical less the 83s already spent, the pace agreeing there's more to go.
    assert progress_time_label(83.0, (10, 20), 724.0) == "1:23 elapsed · ~10:41 left"


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
