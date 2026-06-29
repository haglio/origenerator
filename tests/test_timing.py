import pytest

from origenerator.timing import (
    average_label,
    average_seconds,
    estimate_label,
    estimate_seconds,
    execution_duration_seconds,
    format_duration,
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


@pytest.mark.parametrize("seconds,expected", [
    (8, "8 sec"),
    (9.5, "10 sec"),
    (65, "1 min 5 sec"),
    (120, "2 min"),
    (905, "15 min 5 sec"),
    (3600, "1 hr"),
    (3725, "1 hr 2 min"),
])
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


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
