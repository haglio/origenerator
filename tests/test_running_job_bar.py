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
          progress=None, reveal=None, cancel=None, foreign_ahead=None):
    return InFlightItem(key=key, caption=caption, status=status, frame=frame,
                        reveal=reveal or (lambda: None), progress=progress, cancel=cancel,
                        foreign_ahead=foreign_ahead)


def test_keeps_its_slot_when_idle(bar):
    # The bar's space is reserved even when nothing runs, so a job appearing
    # doesn't shove the panes up. It stays laid out but blank.
    bar.set_items([])
    assert bar.isVisible()
    assert bar._caption.text() == ""
    assert not bar._cancel.isVisible()
    assert not bar._progress.isVisible()


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


def test_switching_from_a_job_to_idle_keeps_the_slot(bar):
    bar.set_items([_item()])
    assert bar._progress.isVisible()
    bar.set_items([])
    assert bar.isVisible()            # still holding its slot
    assert bar._caption.text() == ""  # but blanked


def test_idle_and_active_have_the_same_footprint(bar):
    # Reserving the slot means the bar is the same height idle or active, so the
    # layout never shifts when a job starts or ends.
    bar.set_items([])
    idle = bar.sizeHint().height()
    bar.set_items([_item()])
    assert bar.sizeHint().height() == idle


# --- waiting on another app: name it, and never mislabel the user's own queue

def test_says_how_many_jobs_another_app_has_ahead(bar):
    # The reported mystery: the bar spun with no clue another app's work was in
    # front. Now it says so, in the slot that answers "what's in the way".
    bar.set_items([_item(status="queued", foreign_ahead=3)])
    assert bar._queued.text() == "Waiting behind 3 jobs from another app"


def test_one_job_ahead_reads_in_the_singular(bar):
    bar.set_items([_item(status="queued", foreign_ahead=1)])
    assert bar._queued.text() == "Waiting behind 1 job from another app"


def test_the_users_own_queue_is_still_just_a_queued_count(bar):
    # His own three jobs read as a ComfyUI wait and sent him hunting for phantom
    # jobs. ComfyUI is generating what he asked for; the count says so plainly.
    bar.set_items([
        _item(key="a", foreign_ahead=0),
        _item(key="b", status="queued", foreign_ahead=0),
        _item(key="c", status="queued", foreign_ahead=0),
    ])
    assert bar._queued.text() == "+2 queued"


def test_another_apps_hold_wins_over_this_apps_own_count(bar):
    bar.set_items([
        _item(key="a", status="queued", foreign_ahead=4),
        _item(key="b", status="queued"),
    ])
    assert bar._queued.text() == "Waiting behind 4 jobs from another app"
