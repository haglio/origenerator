"""The queue plate in the fullscreen show's bottom-left corner.

What it says about each job, how much of a long line it spells out, and where it
puts itself — plus the plate taking itself off the screen when nothing is being
made, which is most of the time a show is playing.
"""

import time

import pytest
from PyQt6.QtWidgets import QWidget

from origenerator.gui.inflight import InFlightItem
from origenerator.gui.slideshow_queue import (
    BOTTOM_MARGIN, LEFT_MARGIN, MAX_LINES, SlideshowQueue, job_line, queue_lines,
)


def _item(key="j1", status="queued", **kw):
    kw.setdefault("caption", "Alpha Workflow › a paper kite")
    kw.setdefault("frame", None)
    kw.setdefault("reveal", lambda: None)
    return InFlightItem(key=key, status=status, **kw)


@pytest.fixture
def plate(qtbot):
    """The plate on a screen-sized host. Yielded rather than returned so the host
    stays referenced for the test — the plate is its child, and a collected host
    takes the plate down with it."""
    host = QWidget()
    host.resize(1920, 1080)
    qtbot.addWidget(host)
    yield SlideshowQueue(host)


# --- what one job's line says -------------------------------------------------


def test_a_waiting_job_says_what_it_costs_and_what_it_is():
    assert job_line(_item(typical_seconds=120, job_kind="I2V")) == "~2 min · I2V"


def test_a_running_job_says_how_far_along_it_is():
    now = 1000.0
    line = job_line(
        _item(status="running", progress=(5, 10), typical_seconds=100,
              started_at=now - 60),
        now=now,
    )
    assert line.startswith("50%")
    assert "elapsed" in line


def test_a_running_job_with_nothing_to_report_falls_back_to_its_price():
    """Handed over but not started: no elapsed, no steps. The corner says what it
    would have said in the line rather than sitting blank."""
    assert job_line(_item(status="running", typical_seconds=30, job_kind="Image")) \
        == "~30 sec · Image"


def test_a_running_job_waiting_on_another_app_says_so():
    line = job_line(_item(status="running", foreign_ahead=3, typical_seconds=30))
    assert line == "Waiting behind 3 jobs from another app"


def test_a_held_video_is_marked_as_held():
    """Every video is held while a show plays — the mark is what separates the
    ones the GPU could take from the ones the show is standing on."""
    assert job_line(_item(typical_seconds=600, job_kind="T2V", held=True)) \
        == "~10 min · T2V · held"


def test_an_auto_looped_request_keeps_the_marks_the_strip_gives_it():
    line = job_line(_item(typical_seconds=60, job_kind="Image",
                          auto_generating=True, requested=True))
    assert line == "~1 min · Image · Auto · Request"


# --- the whole line -----------------------------------------------------------


def test_nothing_in_flight_says_nothing():
    assert queue_lines([]) == []


def test_every_job_gets_a_line_in_the_order_given():
    items = [_item("a", typical_seconds=30, job_kind="Image"),
             _item("b", typical_seconds=120, job_kind="I2V", held=True)]
    assert queue_lines(items) == ["~30 sec · Image", "~2 min · I2V · held"]


def test_a_long_line_spells_out_the_first_few_and_counts_the_rest():
    items = [_item(str(i), typical_seconds=30, job_kind="Image") for i in range(9)]
    lines = queue_lines(items)
    assert len(lines) == MAX_LINES + 1
    assert lines[-1] == f"+{9 - MAX_LINES} more"


def test_a_line_exactly_at_the_limit_counts_nothing():
    items = [_item(str(i), typical_seconds=30) for i in range(MAX_LINES)]
    assert not any(line.endswith("more") for line in queue_lines(items))


# --- the plate ----------------------------------------------------------------


def test_the_plate_stays_off_screen_with_nothing_in_flight(plate):
    plate.set_items([])
    assert plate.isHidden()


def test_the_plate_shows_the_line_and_hides_again_when_it_drains(plate):
    plate.set_items([_item(typical_seconds=30, job_kind="Image")])
    assert not plate.isHidden()
    assert plate.lines() == ["~30 sec · Image"]
    plate.set_items([])
    assert plate.isHidden()


def test_the_plate_sits_in_the_bottom_left_corner(plate):
    host = plate.parentWidget()
    plate.set_items([_item(typical_seconds=30, job_kind="Image")])
    assert plate.x() == LEFT_MARGIN
    assert plate.y() + plate.height() == host.height() - BOTTOM_MARGIN


def test_the_plate_grows_upward_as_the_line_does(plate):
    """Its first line — the job with the GPU — stays where the eye last found it."""
    plate.set_items([_item("a", typical_seconds=30)])
    top_of_one = plate.y()
    plate.set_items([_item("a", typical_seconds=30), _item("b", typical_seconds=30)])
    assert plate.y() < top_of_one
    assert plate.y() + plate.height() == plate.parentWidget().height() - BOTTOM_MARGIN


def test_the_plate_re_places_itself_when_the_show_is_resized(plate):
    host = plate.parentWidget()
    plate.set_items([_item(typical_seconds=30)])
    host.resize(1280, 720)
    plate.reposition()
    assert plate.y() + plate.height() == 720 - BOTTOM_MARGIN


def test_the_clock_runs_only_while_something_is_being_rendered(plate):
    """A line of waiting work says the same thing until the queue changes, so
    nothing is counting over it."""
    plate.set_items([_item(status="running", progress=(1, 10),
                           started_at=time.time())])
    assert plate._tick.isActive()
    plate.set_items([_item(typical_seconds=30)])
    assert not plate._tick.isActive()
    plate.set_items([])
    assert not plate._tick.isActive()
