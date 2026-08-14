import pytest

from origenerator.gui.generation_queue import GenerationQueue
from origenerator.gui.inflight_card import InFlightItem


@pytest.fixture
def queue(qtbot):
    q = GenerationQueue()
    qtbot.addWidget(q)
    q.resize(400, 160)
    q.show()
    return q


def _item(key="j1", caption="Alpha Workflow › a kite", status="running", frame=None,
          progress=None, reveal=None, cancel=None, foreign_ahead=None, open_config=None):
    return InFlightItem(key=key, caption=caption, status=status, frame=frame,
                        reveal=reveal or (lambda: None), progress=progress, cancel=cancel,
                        foreign_ahead=foreign_ahead, open_config=open_config)


# --- the slot the queue holds -------------------------------------------------

def test_keeps_its_slot_when_idle(queue):
    # The queue's space is reserved even when nothing runs, so a job appearing
    # doesn't shove the panes up. It stays laid out but empty.
    queue.set_items([])
    assert queue.isVisible()
    assert queue.rows() == []


def test_idle_and_one_job_have_the_same_footprint(queue):
    queue.set_items([])
    idle = queue.sizeHint().height()
    queue.set_items([_item()])
    assert queue.sizeHint().height() == idle


def test_switching_from_a_job_to_idle_keeps_the_slot(queue):
    queue.set_items([_item()])
    assert len(queue.rows()) == 1
    queue.set_items([])
    assert queue.isVisible()
    assert queue.rows() == []


def test_a_long_queue_stops_growing_and_scrolls(queue):
    # Every waiting job is listed, but the strip must not eat the panes above it
    # once a batch is queued up — past its cap the list scrolls instead.
    queue.set_items([_item(key=f"j{i}", status="queued") for i in range(3)])
    capped = queue.sizeHint().height()
    queue.set_items([_item(key=f"j{i}", status="queued") for i in range(12)])
    assert len(queue.rows()) == 12       # all of them are there to scroll to
    assert queue.sizeHint().height() == capped


# --- a row per job, in the order they will run --------------------------------

def test_lists_every_job_in_the_order_it_was_given(queue):
    queue.set_items([
        _item(key="a", caption="running one"),
        _item(key="b", caption="next one", status="queued"),
        _item(key="c", caption="last one", status="queued"),
    ])
    assert [row.key for row in queue.rows()] == ["a", "b", "c"]
    assert [row.caption() for row in queue.rows()] == ["running one", "next one", "last one"]


def test_a_finished_job_leaves_the_queue(queue):
    queue.set_items([_item(key="a"), _item(key="b", status="queued")])
    queue.set_items([_item(key="b", status="running")])
    assert [row.key for row in queue.rows()] == ["b"]


def test_a_live_frame_updates_a_row_without_rebuilding_it(queue):
    # Rows carry a drag the user may be mid-gesture on, and rebuilding the strip
    # every second and a half would yank it out from under them.
    queue.set_items([_item(key="a")])
    row = queue.rows()[0]
    queue.set_items([_item(key="a", caption="renamed", progress=(3, 10))])
    assert queue.rows()[0] is row
    assert row.caption() == "renamed"


def test_progress_reflects_the_running_step_count(queue):
    queue.set_items([_item(status="running", progress=(5, 20))])
    row = queue.rows()[0]
    assert row._progress.maximum() == 20
    assert row._progress.value() == 5


def test_progress_is_indeterminate_without_step_counts(queue):
    # A queued job, or a running one before its first progress tick, shows a moving
    # (indeterminate) bar rather than a stuck 0%.
    queue.set_items([_item(status="queued", progress=None)])
    assert queue.rows()[0]._progress.maximum() == 0


# --- cancel, spelled the way the Generate tab spells it -----------------------

def test_every_row_carries_a_cancel_button(queue):
    # The word, not a ✕: the Generate tab's Cancel and this one stop the same job,
    # so they read the same.
    queue.set_items([_item(key="a", cancel=lambda: None),
                     _item(key="b", status="queued", cancel=lambda: None)])
    assert [row._cancel.text() for row in queue.rows()] == ["Cancel", "Cancel"]


def test_cancel_stops_the_job_on_its_own_row(queue):
    stopped = []
    queue.set_items([
        _item(key="a", cancel=lambda: stopped.append("a")),
        _item(key="b", status="queued", cancel=lambda: stopped.append("b")),
    ])
    queue.rows()[1]._cancel.click()
    assert stopped == ["b"]


def test_cancel_is_hidden_on_a_job_that_cannot_be_stopped_from_here(queue):
    queue.set_items([_item(cancel=None)])
    assert not queue.rows()[0]._cancel.isVisible()


# --- clicking a row opens its tab ---------------------------------------------

def test_clicking_a_row_opens_that_jobs_config_tab(queue, qtbot):
    from PyQt6.QtCore import Qt

    opened = []
    queue.set_items([
        _item(key="a", open_config=lambda: opened.append("a")),
        _item(key="b", status="queued", open_config=lambda: opened.append("b")),
    ])
    qtbot.mouseClick(queue.rows()[1], Qt.MouseButton.LeftButton)
    assert opened == ["b"]


def test_clicking_the_cancel_button_does_not_also_open_a_tab(queue):
    opened, stopped = [], []
    queue.set_items([_item(open_config=lambda: opened.append(True),
                           cancel=lambda: stopped.append(True))])
    queue.rows()[0]._cancel.click()
    assert stopped == [True]
    assert opened == []


def test_a_job_with_no_tab_to_open_is_still_clickable(queue, qtbot):
    from PyQt6.QtCore import Qt

    queue.set_items([_item(open_config=None)])
    qtbot.mouseClick(queue.rows()[0], Qt.MouseButton.LeftButton)  # no crash


# --- waiting on another app ---------------------------------------------------

def test_a_row_says_how_many_jobs_another_app_has_ahead(queue):
    queue.set_items([_item(status="queued", foreign_ahead=3)])
    assert queue.rows()[0]._wait.text() == "Waiting behind 3 jobs from another app"


def test_one_job_ahead_reads_in_the_singular(queue):
    queue.set_items([_item(status="queued", foreign_ahead=1)])
    assert queue.rows()[0]._wait.text() == "Waiting behind 1 job from another app"


def test_the_users_own_queue_needs_no_explaining(queue):
    # His own jobs each have a row of their own now, so there is nothing left for
    # a wait note to tell him — the queue itself is the answer.
    queue.set_items([_item(key="a", foreign_ahead=0),
                     _item(key="b", status="queued", foreign_ahead=0)])
    assert [row._wait.text() for row in queue.rows()] == ["", ""]


# --- dragging a row to reorder the queue --------------------------------------

def test_moving_a_row_asks_for_the_new_order(queue):
    asked = []
    queue.reorder_requested.connect(asked.append)
    queue.set_items([_item(key="a"), _item(key="b", status="queued"),
                     _item(key="c", status="queued")])

    queue.move_row(2, 1)  # drag the last job above the middle one

    assert asked == [["a", "c", "b"]]


def test_the_rows_follow_the_move_at_once(queue):
    # ComfyUI is told to reorder and the next poll confirms it, but the row has to
    # land where it was dropped now — a row that springs back reads as a failure.
    queue.set_items([_item(key="a"), _item(key="b", status="queued"),
                     _item(key="c", status="queued")])

    queue.move_row(2, 1)

    assert [row.key for row in queue.rows()] == ["a", "c", "b"]


def test_a_move_that_changes_nothing_asks_for_nothing(queue):
    asked = []
    queue.reorder_requested.connect(asked.append)
    queue.set_items([_item(key="a"), _item(key="b", status="queued")])

    queue.move_row(1, 1)

    assert asked == []


def _mouse(kind, x, y):
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent

    return QMouseEvent(kind, QPointF(x, y), QPointF(x, y), Qt.MouseButton.LeftButton,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


def _press_and_drag(row, monkeypatch):
    """Press the row and travel far enough to start a drag; returns what it carried."""
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QDrag

    from origenerator.gui.generation_queue import QUEUE_ROW_MIME

    carried = []
    monkeypatch.setattr(QDrag, "exec", lambda self, *a: carried.append(
        bytes(self.mimeData().data(QUEUE_ROW_MIME)).decode()))
    row.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 5, 5))
    row.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, 5, 80))
    return carried


def test_a_press_that_travels_starts_a_drag_carrying_the_rows_id(queue, monkeypatch):
    # Without this the drop handler below is unreachable: nothing else in the app
    # ever starts a queue-row drag.
    queue.set_items([_item(key="a"), _item(key="b", status="queued")])

    assert _press_and_drag(queue.rows()[1], monkeypatch) == ["b"]


def test_a_press_that_stays_put_is_a_click_not_a_drag(queue, monkeypatch):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QDrag

    dragged = []
    monkeypatch.setattr(QDrag, "exec", lambda self, *a: dragged.append(True))
    queue.set_items([_item(key="a")])
    row = queue.rows()[0]

    row.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 5, 5))
    row.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, 6, 6))  # a hand's wobble

    assert dragged == []


def test_a_row_that_was_dragged_does_not_also_open_a_tab(queue, monkeypatch):
    # The release that ends a drag must not read as a click, or every reorder
    # would yank the generate pane to the job that was moved.
    from PyQt6.QtCore import QEvent

    opened = []
    queue.set_items([_item(key="a", open_config=lambda: opened.append(True))])
    row = queue.rows()[0]
    _press_and_drag(row, monkeypatch)

    row.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, 5, 80))

    assert opened == []


def _drop(queue, key, at_row, *, on_top_half=True):
    """Drop the row carrying ``key`` over the row at index ``at_row``."""
    from PyQt6.QtCore import QMimeData, QPointF, Qt
    from PyQt6.QtGui import QDropEvent
    from PyQt6.QtWidgets import QApplication

    from origenerator.gui.generation_queue import QUEUE_ROW_MIME

    QApplication.processEvents()  # the rows must be laid out to be dropped between
    row = queue.rows()[at_row]
    quarter = row.height() // 4
    inside = row.rect().center()
    inside.setY(inside.y() + (-quarter if on_top_half else quarter))
    mime = QMimeData()
    mime.setData(QUEUE_ROW_MIME, key.encode())
    queue.dropEvent(QDropEvent(
        QPointF(row.mapTo(queue, inside)), Qt.DropAction.MoveAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    ))


def test_dropping_a_row_above_another_moves_it_there(queue):
    asked = []
    queue.reorder_requested.connect(asked.append)
    queue.set_items([_item(key="a"), _item(key="b", status="queued"),
                     _item(key="c", status="queued")])

    _drop(queue, "c", at_row=1)  # let the last job go over the middle one

    assert [row.key for row in queue.rows()] == ["a", "c", "b"]
    assert asked == [["a", "c", "b"]]


def test_dropping_a_row_onto_the_bottom_half_puts_it_after(queue):
    # The half of a row a drop lands on is what says above-or-below, so the same
    # gesture an inch lower means something different.
    queue.set_items([_item(key="a"), _item(key="b", status="queued"),
                     _item(key="c", status="queued")])

    _drop(queue, "a", at_row=1, on_top_half=False)

    assert [row.key for row in queue.rows()] == ["b", "a", "c"]


def test_a_drop_carrying_something_else_is_ignored(queue):
    # Gallery thumbnails are dragged around this app too; one let go over the
    # strip must not be read as a reorder.
    from PyQt6.QtCore import QMimeData, QPointF, Qt
    from PyQt6.QtGui import QDropEvent

    asked = []
    queue.reorder_requested.connect(asked.append)
    queue.set_items([_item(key="a"), _item(key="b", status="queued")])
    mime = QMimeData()
    mime.setData("application/x-origenerator-generation", b"a")

    queue.dropEvent(QDropEvent(
        QPointF(5, 5), Qt.DropAction.MoveAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    ))

    assert asked == []
    assert [row.key for row in queue.rows()] == ["a", "b"]
