from __future__ import annotations

from origenerator.timing import (
    RunProgress,
    RunTiming,
    average_label,
    average_seconds,
    clock_duration,
    elapsed_since,
    estimate_label,
    estimate_seconds,
    execution_duration_seconds,
    queue_estimate_label,
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
    assert estimate_seconds([10.0, 11.0, 12.0, 200.0]) == 11.5


def test_estimate_none_when_no_history():
    assert estimate_seconds([]) is None


def test_estimate_label_no_data():
    assert estimate_label([]) == "No timing data yet"


def test_estimate_label_seconds_one_run():
    assert estimate_label([11.0]) == "~11 sec (based on 1 run)"


def test_estimate_label_rounds_to_minutes_and_counts_runs():
    assert estimate_label([700.0, 724.0, 800.0]) == "~12 min (based on 3 runs)"


def test_average_is_the_mean():
    assert average_seconds([10.0, 20.0, 30.0]) == 20.0


def test_average_none_when_empty():
    assert average_seconds([]) is None


def test_average_label_empty_when_no_data():
    assert average_label([]) == ""


def test_average_label_is_coarse_with_a_count():
    assert average_label([700.0, 724.0, 800.0]) == "~12 min (across 3 runs)"


def test_average_label_singular_run():
    assert average_label([6.0]) == "~6 sec (across 1 run)"


def test_clock_duration_always_shows_the_seconds_ticking():
    assert clock_duration(7) == "0:07"
    assert clock_duration(83) == "1:23"
    assert clock_duration(724) == "12:04"


def test_clock_duration_grows_an_hours_field():
    assert clock_duration(3600) == "1:00:00"
    assert clock_duration(4265) == "1:11:05"


def test_clock_duration_floors_a_negative_at_zero():
    assert clock_duration(-5) == "0:00"


def test_remaining_counts_down_from_the_typical_time():
    assert RunTiming(100.0, (1, 20), 724.0).remaining_seconds() == 624.0


def test_remaining_ignores_the_pace_of_the_first_few_steps():
    assert RunTiming(60.0, (1, 20), 700.0).remaining_seconds() == 640.0
    assert RunTiming(60.0, (3, 20), 700.0).remaining_seconds() == 640.0, (
        "the opening steps carry the model coming off disk, so their pace predicts a run "
        "several times longer than the real one")


def test_remaining_follows_a_run_going_slower_than_usual():
    assert RunTiming(900.0, (15, 20), 724.0).remaining_seconds() == 300.0


def test_remaining_uses_the_pace_alone_with_no_history():
    assert RunTiming(200.0, (10, 20), None).remaining_seconds() == 200.0


def test_remaining_hands_over_to_the_pace_as_the_run_settles():
    assert RunTiming(90.0, (10, 20), 724.0).remaining_seconds() == 362.0, (
        "the typical time is a median over runs of every length, resolution and step count, "
        "which differ tenfold, so it only opens the estimate")
    assert round(RunTiming(180.0, (18, 20), 724.0).remaining_seconds()) == 72
    assert RunTiming(200.0, (20, 20), 724.0).remaining_seconds() == 0.0


def test_remaining_is_zero_through_a_tail_that_reports_no_steps():
    assert RunTiming(600.0, (20, 20), 724.0).remaining_seconds() == 0.0


def test_remaining_is_zero_not_none_once_a_run_is_over_its_time():
    assert RunTiming(900.0, (20, 20), 724.0).remaining_seconds() == 0.0


def test_remaining_is_none_with_nothing_to_go_on():
    assert RunTiming(30.0, None, None).remaining_seconds() is None


def test_a_run_past_its_prior_with_no_pace_yet_says_nothing_rather_than_finishing():
    assert RunTiming(900.0, (1, 20), 724.0).remaining_seconds() is None
    assert RunTiming(900.0, (1, 20), 724.0).remaining_label() == ""
    assert RunTiming(900.0, (1, 20), 724.0).status_label() == "5% · 15:00 elapsed"


def test_the_live_line_reads_elapsed_and_left():
    assert RunTiming(83.0, (10, 20), 724.0).time_label() == "1:23 elapsed · ~6:02 left"


def test_progress_time_label_is_elapsed_alone_with_no_estimate():
    assert RunTiming(83.0, None, None).time_label() == "1:23 elapsed"


def test_progress_time_label_says_finishing_rather_than_zero():
    assert RunTiming(900.0, (20, 20), 724.0).time_label() == "15:00 elapsed · finishing", (
        "0:00 left would read as stuck, and a negative number as broken")


def test_progress_time_label_is_empty_before_a_job_starts():
    assert RunTiming(None, None, 724.0).time_label() == "", "a zero on a queued job reads as stuck"


def test_a_queued_jobs_estimate_rounds_to_one_unit():
    assert queue_estimate_label(126.0) == "~2 min", (
        "the queue's rows are glanced at, and one unit is all a median of past runs can back up")
    assert queue_estimate_label(41.0) == "~41 sec"


def test_an_untimed_workflow_admits_it_rather_than_guess():
    assert queue_estimate_label(None) == "~?"


def test_the_percent_reading_rounds_down_to_a_whole_percent():
    assert RunProgress(10, 20).percent_label == "50%"
    assert RunProgress(1, 3).percent_label == "33%"
    assert RunProgress(20, 20).percent_label == "100%"


def test_the_percent_reading_is_empty_with_nothing_to_read_it_off():
    assert RunTiming(None, None, None).status_label() == ""
    assert RunProgress(0, 0).percent_label == "", "a 0% that never moved would be a reading, and there is none"


def test_progress_status_label_leads_with_how_far_along_it_is():
    assert RunTiming(83.0, (10, 20), 724.0).status_label() == "50% · 1:23 elapsed · ~6:02 left"


def test_the_line_leads_with_the_step_being_taken():
    assert RunTiming(83.0, (10, 20), 724.0).status_label(step="First pass") == (
        "First pass · 50% · 1:23 elapsed · ~6:02 left"), (
        "the user asked for the step's name, since the progress bar restarts each pass without "
        "saying which: it is the part that says what is happening, and a line too wide for its "
        "bar loses its right end")
    assert RunTiming(83.0, (10, 20), 724.0).status_label(step="Sound", compact=True) == (
        "Sound · 50% · ~6:02 left"), (
        "the full line is wider than a tile, which would cut the countdown off the long runs "
        "worth counting down, so a tile's line leaves the elapsed time out")


def test_a_run_with_no_step_to_name_reads_as_it_did():
    assert RunTiming(83.0, (10, 20), 724.0).status_label() == "50% · 1:23 elapsed · ~6:02 left"


def test_the_step_is_what_a_run_past_its_prior_has_left_to_say():
    assert RunTiming(900.0, (1, 20), 724.0).status_label(step="First pass") ==         "First pass · 5% · 15:00 elapsed"


def test_progress_status_label_drops_whichever_half_is_unknown():
    assert RunTiming(83.0, None, None).status_label() == "1:23 elapsed"
    assert RunTiming(None, (10, 20), 724.0).status_label() == "50%"
    assert RunTiming(None, None, 724.0).status_label() == ""


def test_the_compact_line_keeps_how_far_along_and_how_much_longer():
    assert RunTiming(83.0, (10, 20), 724.0).status_label(compact=True) == "50% · ~6:02 left"
    assert RunTiming(900.0, (20, 20), 724.0).status_label(compact=True) == "100% · finishing"
    assert RunTiming(83.0, None, None).status_label(compact=True) == ""


def test_remaining_label_is_the_countdown_on_its_own():
    assert RunTiming(83.0, (10, 20), 724.0).remaining_label() == "~6:02 left"
    assert RunTiming(900.0, (20, 20), 724.0).remaining_label() == "finishing"
    assert RunTiming(83.0, None, None).remaining_label() == ""
    assert RunTiming(None, (10, 20), 724.0).remaining_label() == ""


def test_elapsed_since_counts_from_the_moment_a_run_began():
    assert elapsed_since(1_000.0, now=lambda: 1_252.0) == 252.0


def test_elapsed_since_a_run_that_never_began_is_nothing():
    assert elapsed_since(None) is None


def test_elapsed_since_floors_a_clock_that_went_backwards_at_zero():
    assert elapsed_since(1_000.0, now=lambda: 999.0) == 0.0
