import pytest
from PyQt6.QtCore import Qt

from origenerator.gui.inflight_card import InFlightItem
from origenerator.gui.running_job_bar import RunningJobBar


@pytest.fixture
def bar(qtbot):
    b = RunningJobBar()
    qtbot.addWidget(b)
    b.resize(400, 48)
    b.show()
    return b


def _item(key="j1", caption="SDXL › x", status="running", frame=None,
          progress=None, reveal=None, cancel=None):
    return InFlightItem(key=key, caption=caption, status=status, frame=frame,
                        reveal=reveal or (lambda: None), progress=progress, cancel=cancel)


def test_hidden_when_nothing_is_in_flight(bar):
    bar.set_items([])
    assert not bar.isVisible()


def test_shows_the_active_job(bar):
    bar.set_items([_item(caption="my running job")])
    assert bar.isVisible()
    assert "my running job" in bar._caption.text()


def test_shows_a_queued_count_for_the_jobs_behind(bar):
    bar.set_items([
        _item(key="a"),
        _item(key="b", status="queued"),
        _item(key="c", status="queued"),
    ])
    assert "+2" in bar._queued.text()


def test_no_queued_count_for_a_lone_job(bar):
    bar.set_items([_item()])
    assert bar._queued.text() == ""


def test_progress_reflects_the_running_step_count(bar):
    bar.set_items([_item(status="running", progress=(5, 20))])
    assert bar._progress.maximum() == 20
    assert bar._progress.value() == 5


def test_progress_is_indeterminate_without_step_counts(bar):
    # A queued job, or a running one before its first progress tick, shows a moving
    # (indeterminate) bar rather than a stuck 0%.
    bar.set_items([_item(status="queued", progress=None)])
    assert bar._progress.maximum() == 0


def test_clicking_the_bar_reveals_the_job(bar, qtbot):
    revealed = []
    bar.set_items([_item(reveal=lambda: revealed.append(True))])
    qtbot.mouseClick(bar, Qt.MouseButton.LeftButton)
    assert revealed == [True]


def test_cancel_button_cancels_the_job(bar):
    cancelled = []
    bar.set_items([_item(cancel=lambda: cancelled.append(True))])
    bar._cancel.click()
    assert cancelled == [True]


def test_cancel_button_hidden_when_the_job_cannot_be_cancelled(bar):
    bar.set_items([_item(cancel=None)])
    assert not bar._cancel.isVisible()


def test_switching_from_a_job_to_idle_hides_the_bar(bar):
    bar.set_items([_item()])
    assert bar.isVisible()
    bar.set_items([])
    assert not bar.isVisible()
