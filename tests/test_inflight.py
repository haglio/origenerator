"""The wordings every surface showing work in flight shares, and the reading.

Pure functions, tested here rather than through the three panes that draw them:
a wording is one sentence for the whole app, so the place to read what it says
is the module that owns it.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import pytest

from origenerator.gui.generation_job import JobState
from origenerator.gui.inflight import (
    InFlightItem,
    RunReading,
    discard_run_text,
    discard_run_tooltip,
    foreign_queue_text,
    held_row_text,
    queue_held_text,
    queue_lead_text,
    queue_lead_tooltip,
    queue_wait_text,
    starting_row_text,
    stop_loop_text,
    stop_loop_tooltip,
)


def _item(**over) -> InFlightItem:
    fields = dict(key="p1", caption="Alpha Recipe › a cat",
                  reading=RunReading(status=JobState.QUEUED, typical_seconds=120.0),
                  reveal=lambda: None)
    fields.update(over)
    return InFlightItem(**fields)


# --- the head of a queue row -------------------------------------------------

def test_the_price_comes_first_because_that_is_what_a_wait_is_added_up_out_of():
    assert queue_lead_text(_item()).startswith("~2 min")


def test_a_row_says_what_kind_of_work_it_is_when_the_workflow_is_one_we_know():
    assert queue_lead_text(_item(job_kind="Video")) == "~2 min · Video"
    assert queue_lead_text(_item(job_kind="")) == "~2 min"


def test_the_act_follows_the_kind_so_two_runs_on_one_picture_read_apart():
    assert queue_lead_text(_item(job_kind="Video", recipe_category="alpha")) == (
        "~2 min · Video · alpha")


def test_the_two_marks_at_the_end_are_only_ever_added():
    plain = queue_lead_text(_item(job_kind="Image"))
    assert plain == "~2 min · Image"
    assert queue_lead_text(_item(job_kind="Image", auto_generating=True)) == plain + " · Auto"
    assert queue_lead_text(_item(job_kind="Image", requested=True)) == plain + " · Request"
    assert queue_lead_text(_item(job_kind="Image", auto_generating=True, requested=True)) == (
        plain + " · Auto · Request")


# --- and the hover that spells it out ----------------------------------------

def test_a_row_not_sent_yet_says_so_before_anything_about_timing():
    assert queue_lead_tooltip(_item(starting=True)).splitlines()[0] == (
        "Not sent to ComfyUI yet — this row stands in until it is")


def test_a_workflow_with_no_earlier_runs_says_so_rather_than_guessing():
    item = _item(reading=RunReading(status=JobState.QUEUED, typical_seconds=None))
    assert queue_lead_tooltip(item).splitlines()[0] == "No timing data for this workflow yet"


def test_the_hover_expands_the_abbreviated_estimate():
    assert queue_lead_tooltip(_item()).splitlines()[0] == (
        "About 2 min on this workflow's recent runs")


@pytest.mark.parametrize("kind,line", [
    ("Image", "An image"),
    ("Video", "A video made from a start image"),
    ("Enhance", "An enhancement of an image already made"),
])
def test_each_kind_of_work_is_spelled_out_on_hover(kind, line):
    assert line in queue_lead_tooltip(_item(job_kind=kind)).splitlines()


def test_a_workflow_this_build_has_no_template_for_contributes_no_line():
    lines = queue_lead_tooltip(_item(job_kind="")).splitlines()
    assert len(lines) == 1


def test_the_hover_names_who_asked_when_it_was_not_a_press_of_generate():
    lines = queue_lead_tooltip(_item(auto_generating=True, requested=True,
                                     recipe_category="beta")).splitlines()
    assert lines[1:] == [
        "The “beta” act, picked in Combine",
        "Queued by its folder's auto-generate loop",
        "Queued by a request — spoken, or one image of a request made of a whole folder",
    ]


# --- how the run itself is going ---------------------------------------------

def test_a_run_is_rendering_only_while_comfyui_is_working_on_it():
    assert RunReading(status=JobState.RUNNING).rendering is True
    assert RunReading(status=JobState.QUEUED).rendering is False


def test_a_run_still_waiting_reports_no_bars_because_it_has_nothing_to_report():
    waiting = RunReading(status=JobState.QUEUED, progress=(3, 20), pass_progress=(1, 2))
    assert waiting.bars() == (None, None)


def test_a_running_run_reports_both_its_counts():
    running = RunReading(status=JobState.RUNNING, progress=(3, 20), pass_progress=(1, 2))
    assert running.bars() == ((3, 20), (1, 2))


def test_the_line_over_the_bar_names_what_the_app_is_doing():
    running = RunReading(status=JobState.RUNNING, progress=(5, 20), stage="Upscaling")
    assert "Upscaling" in running.caption()


# --- the button that throws the run away -------------------------------------

def test_the_discard_button_promises_a_stop_only_when_a_stop_is_what_it_gets():
    assert discard_run_text(auto_generating=False) == "Cancel"
    assert discard_run_text(auto_generating=True) == "Next seed"


def test_the_discard_hover_says_which_of_the_two_the_press_will_do():
    assert discard_run_tooltip(auto_generating=False) == "Cancel this generation"
    assert discard_run_tooltip(auto_generating=True) == (
        "Throw away this seed and start the next")


def test_the_menu_carries_the_act_the_button_has_no_room_for():
    assert stop_loop_text() == "Cancel and stop auto-generating"
    assert stop_loop_tooltip() == "Throw this run away and switch the loop off"


# --- the waits -----------------------------------------------------------

def test_only_another_apps_work_earns_a_line_about_waiting():
    assert queue_wait_text(None) is None
    assert queue_wait_text(0) is None


def test_a_wait_on_another_app_counts_its_jobs_and_says_job_or_jobs():
    assert queue_wait_text(1) == "Waiting on 1 job from another app"
    assert queue_wait_text(4) == "Waiting on 4 jobs from another app"


def test_a_queue_holding_videos_back_says_so_and_says_what_ends_it():
    assert queue_held_text(None) is None
    assert queue_held_text(0) is None
    assert queue_held_text(1) == "1 video held until the slideshow closes"
    assert queue_held_text(3) == "3 videos held until the slideshow closes"


def test_a_row_that_is_not_a_job_yet_says_it_is_not_in_the_line():
    assert starting_row_text(starting=True) == "Starting…"
    assert starting_row_text(starting=False) is None


def test_a_held_row_says_the_same_thing_in_one_rows_width():
    assert held_row_text(held=True) == "Held until the slideshow closes"
    assert held_row_text(held=False) is None


def test_the_line_to_read_before_pressing_generate_counts_the_foreign_queue():
    assert foreign_queue_text(None) is None
    assert foreign_queue_text(0) is None
    assert foreign_queue_text(1) == "1 job from another app is queued on ComfyUI"
    assert foreign_queue_text(6) == "6 jobs from another app are queued on ComfyUI"
