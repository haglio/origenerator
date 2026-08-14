import pytest

from origenerator.gui.generation_queue import GenerationQueue
from origenerator.gui.inflight import InFlightItem


@pytest.fixture
def queue(qtbot):
    q = GenerationQueue()
    qtbot.addWidget(q)
    q.resize(700, 80)
    q.show()
    return q


def _item(key="j1", caption="Alpha Workflow › a kite", status="running", frame=None,
          progress=None, reveal=None, cancel=None, foreign_ahead=None, open_config=None):
    return InFlightItem(key=key, caption=caption, status=status, frame=frame,
                        reveal=reveal or (lambda: None), progress=progress, cancel=cancel,
                        foreign_ahead=foreign_ahead, open_config=open_config)


# --- the shape of the strip ---------------------------------------------------

def test_keeps_its_slot_when_idle(queue):
    # The strip's space is reserved even when nothing runs, so a job appearing
    # doesn't shove the panes up. It stays laid out but blank.
    queue.set_items([])
    assert queue.isVisible()
    assert queue.running_row().key is None
    assert queue.queued_rows() == []


def test_a_queue_of_any_length_is_one_progress_row_tall(queue):
    # Only one thing renders at a time, so only one thing needs a progress bar;
    # the rest are a compact list beside it and cost the panes above nothing.
    queue.set_items([])
    idle = queue.sizeHint().height()
    queue.set_items([_item(key=f"j{i}", status="queued") for i in range(12)])
    assert queue.sizeHint().height() == idle
    assert len(queue.queued_rows()) == 11  # all of them, a scroll away


def test_the_job_being_made_takes_the_progress_row(queue):
    queue.set_items([
        _item(key="a", caption="the one rendering"),
        _item(key="b", caption="next", status="queued"),
        _item(key="c", caption="last", status="queued"),
    ])
    assert queue.running_row().key == "a"
    assert queue.running_row().caption() == "the one rendering"
    assert [row.key for row in queue.queued_rows()] == ["b", "c"]
    assert queue.keys() == ["a", "b", "c"]


def test_the_line_moves_up_when_the_leader_finishes(queue):
    queue.set_items([_item(key="a"), _item(key="b", status="queued")])
    queue.set_items([_item(key="b", status="running")])
    assert queue.running_row().key == "b"
    assert queue.queued_rows() == []


def test_a_live_frame_updates_the_rows_without_rebuilding_them(queue):
    # Entries carry a drag the user may be mid-gesture on, and rebuilding the list
    # every second and a half would yank it out from under them.
    queue.set_items([_item(key="a"), _item(key="b", status="queued")])
    waiting = queue.queued_rows()[0]

    queue.set_items([_item(key="a", caption="renamed", progress=(3, 10)),
                     _item(key="b", caption="also renamed", status="queued")])

    assert queue.queued_rows()[0] is waiting
    assert waiting.caption() == "also renamed"
    assert queue.running_row().caption() == "renamed"


def test_progress_reflects_the_running_step_count(queue):
    queue.set_items([_item(status="running", progress=(5, 20))])
    assert queue.running_row()._progress.maximum() == 20
    assert queue.running_row()._progress.value() == 5


def test_progress_is_indeterminate_without_step_counts(queue):
    # A queued job at the head, or a running one before its first progress tick,
    # shows a moving (indeterminate) bar rather than a stuck 0%.
    queue.set_items([_item(status="queued", progress=None)])
    assert queue.running_row()._progress.maximum() == 0


# --- cancel, spelled the way the Generate tab spells it -----------------------

def test_the_progress_row_and_every_waiting_entry_carry_a_cancel(queue):
    # The word, not a ✕: a config tab's Cancel and these stop the same job, so
    # they read the same.
    queue.set_items([_item(key="a", cancel=lambda: None),
                     _item(key="b", status="queued", cancel=lambda: None)])
    assert queue.running_row()._cancel.text() == "Cancel"
    assert [row._cancel.text() for row in queue.queued_rows()] == ["Cancel"]


def test_cancel_stops_the_job_on_its_own_row(queue):
    stopped = []
    queue.set_items([
        _item(key="a", cancel=lambda: stopped.append("a")),
        _item(key="b", status="queued", cancel=lambda: stopped.append("b")),
        _item(key="c", status="queued", cancel=lambda: stopped.append("c")),
    ])

    queue.queued_rows()[1]._cancel.click()
    queue.running_row()._cancel.click()

    assert stopped == ["c", "a"]


def test_cancel_is_hidden_on_a_job_that_cannot_be_stopped_from_here(queue):
    queue.set_items([_item(key="a", cancel=None), _item(key="b", status="queued")])
    assert not queue.running_row()._cancel.isVisible()
    assert not queue.queued_rows()[0]._cancel.isVisible()


# --- clicking opens the job's tab ---------------------------------------------

def test_clicking_a_waiting_entry_opens_that_jobs_config_tab(queue, qtbot):
    from PyQt6.QtCore import Qt

    opened = []
    queue.set_items([
        _item(key="a", open_config=lambda: opened.append("a")),
        _item(key="b", status="queued", open_config=lambda: opened.append("b")),
    ])
    qtbot.mouseClick(queue.queued_rows()[0], Qt.MouseButton.LeftButton)
    assert opened == ["b"]


def test_clicking_the_progress_row_opens_its_tab_too(queue, qtbot):
    from PyQt6.QtCore import Qt

    opened = []
    queue.set_items([_item(key="a", open_config=lambda: opened.append("a"))])
    qtbot.mouseClick(queue.running_row(), Qt.MouseButton.LeftButton)
    assert opened == ["a"]


def test_clicking_cancel_does_not_also_open_a_tab(queue):
    opened, stopped = [], []
    queue.set_items([_item(key="a"),
                     _item(key="b", status="queued",
                           open_config=lambda: opened.append(True),
                           cancel=lambda: stopped.append(True))])
    queue.queued_rows()[0]._cancel.click()
    assert stopped == [True]
    assert opened == []


def test_a_job_with_no_tab_to_open_is_still_clickable(queue, qtbot):
    from PyQt6.QtCore import Qt

    queue.set_items([_item(open_config=None)])
    qtbot.mouseClick(queue.running_row(), Qt.MouseButton.LeftButton)  # no crash


# --- waiting on another app ---------------------------------------------------

def test_the_progress_row_says_how_many_jobs_another_app_has_ahead(queue):
    queue.set_items([_item(status="queued", foreign_ahead=3)])
    assert queue.running_row()._wait.text() == "Waiting behind 3 jobs from another app"


def test_one_job_ahead_reads_in_the_singular(queue):
    queue.set_items([_item(status="queued", foreign_ahead=1)])
    assert queue.running_row()._wait.text() == "Waiting behind 1 job from another app"


def test_the_users_own_queue_needs_no_explaining(queue):
    # His own jobs are the list beside the bar, so there is nothing left for a
    # wait note to tell him — the line itself is the answer.
    queue.set_items([_item(key="a", foreign_ahead=0),
                     _item(key="b", status="queued", foreign_ahead=0)])
    assert queue.running_row()._wait.text() == ""
    assert queue.queued_rows()[0].caption() == "Alpha Workflow › a kite"


# --- dragging a waiting entry up or down the line -----------------------------

def _mouse(kind, x, y):
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent

    return QMouseEvent(kind, QPointF(x, y), QPointF(x, y), Qt.MouseButton.LeftButton,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


def _press_and_drag(row, monkeypatch):
    """Press the entry and travel far enough to start a drag; returns what it carried."""
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QDrag

    from origenerator.gui.generation_queue import QUEUE_ROW_MIME

    carried = []
    monkeypatch.setattr(QDrag, "exec", lambda self, *a: carried.append(
        bytes(self.mimeData().data(QUEUE_ROW_MIME)).decode()))
    row.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 5, 5))
    row.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, 5, 80))
    return carried


def test_a_press_that_travels_starts_a_drag_carrying_the_entrys_id(queue, monkeypatch):
    # Without this the drop handler below is unreachable: nothing else in the app
    # ever starts a queue-row drag.
    queue.set_items([_item(key="a"), _item(key="b", status="queued"),
                     _item(key="c", status="queued")])

    assert _press_and_drag(queue.queued_rows()[1], monkeypatch) == ["c"]


def test_a_press_that_stays_put_is_a_click_not_a_drag(queue, monkeypatch):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QDrag

    dragged = []
    monkeypatch.setattr(QDrag, "exec", lambda self, *a: dragged.append(True))
    queue.set_items([_item(key="a"), _item(key="b", status="queued")])

    row = queue.queued_rows()[0]
    row.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 5, 5))
    row.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, 6, 6))  # a hand's wobble

    assert dragged == []


def test_an_entry_that_was_dragged_does_not_also_open_a_tab(queue, monkeypatch):
    # The release that ends a drag must not read as a click, or every reorder
    # would yank the generate pane to the job that was moved.
    from PyQt6.QtCore import QEvent

    opened = []
    queue.set_items([_item(key="a"),
                     _item(key="b", status="queued",
                           open_config=lambda: opened.append(True))])
    row = queue.queued_rows()[0]
    _press_and_drag(row, monkeypatch)

    row.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, 5, 80))

    assert opened == []


def _drop(queue, key, at_row, *, on_top_half=True):
    """Drop the entry carrying ``key`` over the waiting entry at index ``at_row``."""
    from PyQt6.QtCore import QMimeData, QPointF, Qt
    from PyQt6.QtGui import QDropEvent
    from PyQt6.QtWidgets import QApplication

    from origenerator.gui.generation_queue import QUEUE_ROW_MIME

    QApplication.processEvents()  # the entries must be laid out to be dropped between
    row = queue.queued_rows()[at_row]
    quarter = row.height() // 4
    inside = row.rect().center()
    inside.setY(inside.y() + (-quarter if on_top_half else quarter))
    mime = QMimeData()
    mime.setData(QUEUE_ROW_MIME, key.encode())
    queue.dropEvent(QDropEvent(
        QPointF(row.mapTo(queue, inside)), Qt.DropAction.MoveAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    ))


def _three(queue):
    queue.set_items([_item(key="a"), _item(key="b", status="queued"),
                     _item(key="c", status="queued"), _item(key="d", status="queued")])


def test_dropping_an_entry_above_another_moves_it_there(queue):
    asked = []
    queue.reorder_requested.connect(asked.append)
    _three(queue)

    _drop(queue, "d", at_row=0)  # let the last one go over the first waiting entry

    assert [row.key for row in queue.queued_rows()] == ["d", "b", "c"]
    assert asked == [["a", "d", "b", "c"]]  # the one being made stays in front


def test_dropping_an_entry_onto_the_bottom_half_puts_it_after(queue):
    # The half of an entry a drop lands on is what says above-or-below, so the same
    # gesture a few pixels lower means something different.
    _three(queue)

    _drop(queue, "b", at_row=1, on_top_half=False)

    assert [row.key for row in queue.queued_rows()] == ["c", "b", "d"]


def test_a_move_that_changes_nothing_asks_for_nothing(queue):
    asked = []
    queue.reorder_requested.connect(asked.append)
    _three(queue)

    queue.move_queued(1, 1)

    assert asked == []


def test_the_job_being_made_cannot_be_dragged_out_of_the_way(queue):
    # Nothing can go in front of what ComfyUI is already rendering, so the
    # progress row is not part of the line a drop can rearrange.
    asked = []
    queue.reorder_requested.connect(asked.append)
    _three(queue)

    _drop(queue, "a", at_row=0)  # the running job's id, dropped into the line

    assert asked == []
    assert queue.keys() == ["a", "b", "c", "d"]


def test_a_drop_carrying_something_else_is_ignored(queue):
    # Gallery thumbnails are dragged around this app too; one let go over the
    # strip must not be read as a reorder.
    from PyQt6.QtCore import QMimeData, QPointF, Qt
    from PyQt6.QtGui import QDropEvent

    asked = []
    queue.reorder_requested.connect(asked.append)
    _three(queue)
    mime = QMimeData()
    mime.setData("application/x-origenerator-generation", b"b")

    queue.dropEvent(QDropEvent(
        QPointF(5, 5), Qt.DropAction.MoveAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    ))

    assert asked == []
    assert queue.keys() == ["a", "b", "c", "d"]
