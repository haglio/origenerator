import time

import pytest

from origenerator.gui.generation_queue import GenerationQueue, QueueRow
from origenerator.gui.inflight import InFlightItem


@pytest.fixture
def queue(qtbot):
    q = GenerationQueue()
    qtbot.addWidget(q)
    q.resize(800, 60)
    q.show()
    return q


def _item(key="j1", caption="Alpha Workflow › a kite", status="running", frame=None,
          progress=None, reveal=None, cancel=None, foreign_ahead=None, held=False,
          started_at=None, typical_seconds=None, auto_generating=False):
    return InFlightItem(key=key, caption=caption, status=status, frame=frame,
                        reveal=reveal or (lambda: None), progress=progress, cancel=cancel,
                        foreign_ahead=foreign_ahead, held=held, started_at=started_at,
                        typical_seconds=typical_seconds, auto_generating=auto_generating)


def _png_bytes(side=200):
    """A plain square PNG, standing in for a live frame off ComfyUI."""
    from PyQt6.QtCore import QBuffer
    from PyQt6.QtGui import QPixmap

    pixmap = QPixmap(side, side)
    pixmap.fill()
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    return bytes(buffer.data())


def _four(queue):
    queue.set_items([_item(key="a"), _item(key="b", status="queued"),
                     _item(key="c", status="queued"), _item(key="d", status="queued")])


# --- the shape of the strip ---------------------------------------------------

def test_keeps_its_slot_when_idle(queue):
    # The strip's space is reserved even when nothing runs, so a job appearing
    # doesn't shove the panes up. It stays laid out but blank.
    queue.set_items([])
    assert queue.isVisible()
    assert queue.running_preview().key is None
    assert queue.rows() == []


def test_an_empty_line_says_what_it_is_for(queue):
    # The strip keeps its slot with nothing queued, so this side of it is blank
    # most of the time — and a blank half of a laid-out strip reads as something
    # that failed to draw. Dim letters, so it is a note about the space rather
    # than a row sitting in it.
    from PyQt6.QtWidgets import QApplication

    queue.set_items([])
    QApplication.processEvents()

    assert queue._hint.isVisible()
    assert queue._hint.text() == "(queued jobs show up here)"
    assert queue._hint.objectName() == "estimateLabel"  # the app's muted text


def test_the_hint_sits_in_the_middle_of_the_space_it_explains(queue):
    from PyQt6.QtWidgets import QApplication

    queue.set_items([])
    QApplication.processEvents()
    hint, viewport = queue._hint, queue._scroll.viewport()
    center = hint.mapTo(viewport, hint.rect().center())

    assert abs(center.x() - viewport.width() // 2) <= 1
    assert abs(center.y() - viewport.height() // 2) <= 1


def test_the_first_job_takes_the_space_back_from_the_hint(queue):
    from PyQt6.QtWidgets import QApplication

    queue.set_items([])
    queue.set_items([_item(key="a")])
    QApplication.processEvents()

    assert not queue._hint.isVisible()
    assert queue.keys() == ["a"]  # and it was never a row of the line itself


def test_the_hint_comes_back_when_the_queue_drains(queue):
    from PyQt6.QtWidgets import QApplication

    queue.set_items([_item(key="a")])
    queue.set_items([])
    QApplication.processEvents()

    assert queue._hint.isVisible()
    assert queue.rows() == []


def test_a_queue_of_any_length_is_one_progress_bar_tall(queue):
    queue.set_items([])
    idle = queue.sizeHint().height()
    queue.set_items([_item(key=f"j{i}", status="queued") for i in range(12)])
    assert queue.sizeHint().height() == idle
    assert len(queue.rows()) == 12  # all of them, the rest a scroll away


def test_the_clock_reads_above_the_bar_it_measures(queue):
    # Stacked, not side by side: the numbers sit over the bar they explain, and
    # neither is made to give up width to the other.
    from PyQt6.QtWidgets import QApplication

    queue.set_items([_item(status="running", progress=(10, 20),
                           started_at=time.time() - 90.5, typical_seconds=725.0)])
    QApplication.processEvents()
    preview = queue.running_preview()

    assert preview._caption.geometry().bottom() <= preview._progress.geometry().top()
    assert preview._caption.x() == preview._progress.x()  # and they line up


def test_the_thumbnail_fills_the_strips_bottom_left_corner(queue):
    # The live frame is what the left half is for, so it takes the biggest square
    # the strip has room for — its height under the top rule — right into its
    # corner.
    from PyQt6.QtWidgets import QApplication

    queue.set_items([_item(status="running")])
    QApplication.processEvents()
    frame = queue.running_preview()._frame
    corner = frame.mapTo(queue, frame.rect().bottomLeft())

    assert frame.width() == frame.height() == queue.height() - 1
    assert (corner.x(), corner.y()) == (0, queue.height() - 1)


def test_a_strip_dragged_open_gives_the_room_to_the_line(queue):
    # It is opened to read the queue, not to be shown one enormous frame: the
    # thumbnail stops at the strip's own opening height and the rows take the rest.
    from PyQt6.QtWidgets import QApplication

    from origenerator.gui.generation_queue import _STRIP_HEIGHT

    queue.set_items([_item(status="running")])
    queue.resize(800, 400)
    QApplication.processEvents()

    assert queue.running_preview()._frame.height() == _STRIP_HEIGHT
    assert queue._scroll.height() > _STRIP_HEIGHT


def test_the_strip_can_be_dragged_taller_but_not_shorter_than_a_bar(queue):
    from origenerator.gui.generation_queue import _STRIP_HEIGHT

    assert queue.minimumHeight() == _STRIP_HEIGHT
    assert queue.maximumHeight() > _STRIP_HEIGHT  # not pinned to its opening height


def test_the_strip_carries_its_own_top_rule(queue):
    # A stylesheet border under a child's own background disappears into the flat
    # color the app paints everything; this one is a widget of its own.
    from PyQt6.QtWidgets import QFrame

    rules = [w for w in queue.findChildren(QFrame)
             if w.height() == 1 and w.parent() is queue]
    assert len(rules) == 1
    assert rules[0].y() == 0


def test_the_live_frame_is_drawn_at_the_size_of_that_square(queue):
    # Sizing the label alone would leave the picture its old size in the middle
    # of a bigger blank square.
    from PyQt6.QtWidgets import QApplication

    queue.set_items([_item(status="running", frame=_png_bytes())])
    QApplication.processEvents()
    frame = queue.running_preview()._frame

    assert frame.pixmap().height() == frame.height()


def test_the_left_half_follows_the_job_being_made(queue):
    queue.set_items([
        _item(key="a", caption="the one rendering", progress=(5, 20)),
        _item(key="b", caption="next", status="queued"),
    ])
    assert queue.running_preview().key == "a"
    assert queue.running_preview()._progress.maximum() == 20
    assert queue.running_preview()._progress.value() == 5


def test_progress_is_indeterminate_without_step_counts(queue):
    # A queued job at the head, or a running one before its first progress tick,
    # shows a moving (indeterminate) bar rather than a stuck 0%.
    queue.set_items([_item(status="queued", progress=None)])
    assert queue.running_preview()._progress.maximum() == 0


def test_the_whole_queue_is_listed_the_job_being_made_first(queue):
    # Not the queue-except-its-head: every in-flight job has a row, so there is
    # one place that answers "what is queued".
    _four(queue)
    assert queue.keys() == ["a", "b", "c", "d"]


def test_the_line_moves_up_when_the_leader_finishes(queue):
    queue.set_items([_item(key="a"), _item(key="b", status="queued")])
    queue.set_items([_item(key="b", status="running")])
    assert queue.keys() == ["b"]
    assert queue.running_preview().key == "b"


def test_a_live_frame_updates_the_rows_without_rebuilding_them(queue):
    # Rows carry a drag the user may be mid-gesture on, and rebuilding the list
    # every second and a half would yank it out from under them.
    queue.set_items([_item(key="a"), _item(key="b", status="queued")])
    row = queue.rows()[1]

    queue.set_items([_item(key="a", caption="renamed", progress=(3, 10)),
                     _item(key="b", caption="also renamed", status="queued")])

    assert queue.rows()[1] is row
    assert row.caption() == "also renamed"


# --- cancel, spelled the way the Generate tab spells it -----------------------

def test_every_row_carries_a_cancel_including_the_one_being_made(queue):
    # Anything in the queue can be taken out of it, the job at the front included.
    queue.set_items([_item(key="a", cancel=lambda: None),
                     _item(key="b", status="queued", cancel=lambda: None)])
    assert [row._cancel.text() for row in queue.rows()] == ["Cancel", "Cancel"]


def test_cancel_stops_the_job_on_its_own_row(queue):
    stopped = []
    queue.set_items([
        _item(key="a", cancel=lambda: stopped.append("a")),
        _item(key="b", status="queued", cancel=lambda: stopped.append("b")),
        _item(key="c", status="queued", cancel=lambda: stopped.append("c")),
    ])

    queue.rows()[2]._cancel.click()
    queue.rows()[0]._cancel.click()

    assert stopped == ["c", "a"]


def test_cancel_is_hidden_on_a_job_that_cannot_be_stopped_from_here(queue):
    queue.set_items([_item(key="a", cancel=None)])
    assert not queue.rows()[0]._cancel.isVisible()


def test_a_row_from_an_auto_generating_folder_says_next_seed(queue):
    # The press discards that seed and its folder's loop starts another, so the
    # row says what it gets you — one folder looping doesn't re-label the others.
    queue.set_items([_item(key="a", cancel=lambda: None, auto_generating=True),
                     _item(key="b", status="queued", cancel=lambda: None)])
    assert [row._cancel.text() for row in queue.rows()] == ["Next seed", "Cancel"]


def test_a_row_relabels_in_place_when_its_folders_loop_is_switched_off(queue):
    # Auto off with the run still cooking: the same row's press is a plain cancel
    # again, and rows are updated in place rather than rebuilt.
    queue.set_items([_item(key="a", cancel=lambda: None, auto_generating=True)])

    queue.set_items([_item(key="a", cancel=lambda: None)])

    assert queue.rows()[0]._cancel.text() == "Cancel"


# --- clicking a row goes to the job's folder ----------------------------------

def test_clicking_a_row_reveals_that_jobs_folder(queue, qtbot):
    from PyQt6.QtCore import Qt

    revealed = []
    queue.set_items([
        _item(key="a", reveal=lambda: revealed.append("a")),
        _item(key="b", status="queued", reveal=lambda: revealed.append("b")),
    ])
    qtbot.mouseClick(queue.rows()[1], Qt.MouseButton.LeftButton)
    assert revealed == ["b"]


def test_clicking_cancel_does_not_also_reveal_the_folder(queue):
    revealed, stopped = [], []
    queue.set_items([_item(key="a", reveal=lambda: revealed.append(True),
                           cancel=lambda: stopped.append(True))])
    queue.rows()[0]._cancel.click()
    assert stopped == [True]
    assert revealed == []


# --- waiting on another app ---------------------------------------------------

def test_a_row_says_how_many_jobs_another_app_has_ahead(queue):
    queue.set_items([_item(status="queued", foreign_ahead=3)])
    assert queue.rows()[0].caption() == "Waiting behind 3 jobs from another app"


def test_one_job_ahead_reads_in_the_singular(queue):
    queue.set_items([_item(status="queued", foreign_ahead=1)])
    assert queue.rows()[0].caption() == "Waiting behind 1 job from another app"


def test_the_users_own_queue_needs_no_explaining(queue):
    # His own jobs are the rows of this very list, so there is nothing left for a
    # wait note to tell him — the line itself is the answer.
    queue.set_items([_item(key="a", caption="one", foreign_ahead=0),
                     _item(key="b", caption="two", status="queued", foreign_ahead=0)])
    assert [row.caption() for row in queue.rows()] == ["one", "two"]


# --- a queue holding work back for a slideshow --------------------------------

def test_a_held_row_says_what_it_is_waiting_on(queue):
    # A line that stops moving with the GPU idle is a mystery worth ending, and
    # this one ends by closing the show.
    queue.set_items([_item(status="queued", held=True)])
    assert queue.rows()[0].caption() == "Held until the slideshow closes"


def test_the_free_half_says_the_hold_when_nothing_of_ours_runs(queue):
    queue.set_items([_item(key="a", status="queued", held=True),
                     _item(key="b", status="queued", held=True)])

    assert queue.running_preview().key is None  # a held job has no frame to show
    assert _timing(queue) == "2 videos held until the slideshow closes"


def test_the_hold_is_said_before_another_apps_backlog(queue):
    # Both are reasons the machine isn't ours, but only one of them ends by
    # closing something in this window.
    queue.set_items([_item(status="queued", held=True)], foreign_queued=2)
    assert _timing(queue) == "1 video held until the slideshow closes"


def test_a_running_job_still_takes_the_half_while_others_are_held(queue):
    queue.set_items([_item(key="a", status="running", started_at=time.time() - 5.5),
                     _item(key="b", status="queued", held=True)])
    assert queue.running_preview().key == "a"
    assert "elapsed" in _timing(queue)


# --- how long it's been, and how long is left ---------------------------------

def _timing(queue) -> str:
    return queue.running_preview()._caption.text()


def test_shows_the_elapsed_time_and_what_is_left(queue):
    # A 12-minute video job 90 seconds in: the bar now has both numbers above it
    # instead of creeping along with nothing to measure it against. The
    # half-seconds keep both readings a clear half-second off a rollover, so the
    # time the test itself takes can't tip either one.
    queue.set_items([_item(status="running", progress=(10, 20),
                           started_at=time.time() - 90.5, typical_seconds=725.0)])
    assert _timing(queue) == "1:30 elapsed · ~6:02 left"


def test_shows_the_elapsed_time_alone_with_no_estimate(queue):
    # The first run of a workflow has no history behind it, and one step in it's
    # too early to pace off — the elapsed count still stands on its own.
    queue.set_items([_item(status="running", progress=(1, 20),
                           started_at=time.time() - 45.5)])
    assert _timing(queue) == "0:45 elapsed"


def test_no_clock_on_a_job_comfyui_has_not_started(queue):
    queue.set_items([_item(status="queued", started_at=None, typical_seconds=724.0)])
    assert _timing(queue) == ""


def test_the_clock_advances_between_polls(queue):
    # The gallery re-feeds the strip every 1.5s, which would make a seconds count
    # skip; the running half re-reads the clock itself so it moves a second at a
    # time.
    queue.set_items([_item(status="running", started_at=time.time() - 5.5)])
    assert _timing(queue) == "0:05 elapsed"
    queue.running_preview()._item.started_at -= 3  # as if three seconds had gone by
    queue.running_preview()._tick.timeout.emit()
    assert _timing(queue) == "0:08 elapsed"


def test_the_clock_stops_when_the_queue_empties(queue):
    queue.set_items([_item(status="running", started_at=time.time() - 5.5)])
    assert queue.running_preview()._tick.isActive()

    queue.set_items([])

    assert not queue.running_preview()._tick.isActive()
    assert _timing(queue) == ""


def test_another_apps_backlog_takes_the_slot_back_when_ours_empties(queue):
    # The clock and the foreign-queue line share the line above the bar: ours
    # while we have a job, theirs when we don't.
    queue.set_items([_item(status="running", started_at=time.time() - 5.5)])
    assert "elapsed" in _timing(queue)

    queue.set_items([], foreign_queued=2)

    assert _timing(queue) == "2 jobs from another app are queued on ComfyUI"


def test_the_clock_keeps_the_strip_the_same_height(queue):
    # Same reason the idle strip holds its slot: the clock rides in the strip's
    # own height rather than adding a line that would shove the panes above it.
    queue.set_items([])
    idle = queue.sizeHint().height()
    queue.set_items([_item(status="running", progress=(10, 20),
                           started_at=time.time() - 90.5, typical_seconds=725.0)])
    assert queue.sizeHint().height() == idle


# --- dragging a row up or down the line ---------------------------------------

def _mouse(kind, x, y):
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent

    return QMouseEvent(kind, QPointF(x, y), QPointF(x, y), Qt.MouseButton.LeftButton,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


def _press_and_drag(row, monkeypatch, *, watch=None):
    """Press the row and travel far enough to start a drag; returns what it carried."""
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QDrag

    from origenerator.gui.generation_queue import QUEUE_ROW_MIME

    carried = []

    def fake_exec(self, *a):
        if watch is not None:
            watch.append(row.property("dragging"))
        carried.append(bytes(self.mimeData().data(QUEUE_ROW_MIME)).decode())

    monkeypatch.setattr(QDrag, "exec", fake_exec)
    row.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 5, 5))
    row.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, 5, 80))
    return carried


def test_a_press_that_travels_starts_a_drag_carrying_the_rows_id(queue, monkeypatch):
    # Without this the drop handler below is unreachable: nothing else in the app
    # ever starts a queue-row drag.
    _four(queue)
    assert _press_and_drag(queue.rows()[2], monkeypatch) == ["c"]


def test_the_dragged_row_lights_up_while_it_is_being_dragged(queue, monkeypatch):
    # Otherwise the gesture is invisible and reads as an accident rather than
    # something the strip offers.
    _four(queue)
    row = queue.rows()[2]
    lit = []

    _press_and_drag(row, monkeypatch, watch=lit)

    assert lit == [True]
    assert row.property("dragging") is False  # and it settles back afterwards


def test_the_job_being_made_cannot_be_picked_up(queue, monkeypatch):
    # Nothing goes in front of what ComfyUI is already rendering, so the head of
    # the line does not move.
    _four(queue)
    assert queue.rows()[0].movable is False
    assert _press_and_drag(queue.rows()[0], monkeypatch) == []


def test_the_head_of_a_queue_with_nothing_running_can_be_moved(queue, monkeypatch):
    # It is only what is being *rendered* that is fixed. A queue held for a
    # slideshow has nothing rendering, and the user may still put it in the order
    # they want it run in.
    queue.set_items([_item(key="a", status="queued", held=True),
                     _item(key="b", status="queued", held=True)])

    assert queue.rows()[0].movable is True
    assert _press_and_drag(queue.rows()[0], monkeypatch) == ["a"]


def test_a_press_that_stays_put_is_a_click_not_a_drag(queue, monkeypatch):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QDrag

    dragged = []
    monkeypatch.setattr(QDrag, "exec", lambda self, *a: dragged.append(True))
    _four(queue)

    row = queue.rows()[1]
    row.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 5, 5))
    row.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, 6, 6))  # a hand's wobble

    assert dragged == []


def test_a_row_that_was_dragged_does_not_also_reveal_its_folder(queue, monkeypatch):
    from PyQt6.QtCore import QEvent

    revealed = []
    queue.set_items([_item(key="a"),
                     _item(key="b", status="queued",
                           reveal=lambda: revealed.append(True))])
    row = queue.rows()[1]
    _press_and_drag(row, monkeypatch)

    row.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, 5, 80))

    assert revealed == []


# A synthetic drag event does not own its QMimeData: let the local go and Python
# frees it under Qt's feet, which crashes the handler reading it mid-suite.
_HELD_MIME = []


def _drag_event(queue, kind, key, at_row, *, on_top_half=True):
    from PyQt6.QtCore import QMimeData, QPointF, Qt
    from PyQt6.QtWidgets import QApplication

    from origenerator.gui.generation_queue import QUEUE_ROW_MIME

    QApplication.processEvents()  # the rows must be laid out to be dropped between
    row = queue.rows()[at_row]
    quarter = row.height() // 4
    inside = row.rect().center()
    inside.setY(inside.y() + (-quarter if on_top_half else quarter))
    mime = QMimeData()
    mime.setData(QUEUE_ROW_MIME, key.encode())
    _HELD_MIME.append(mime)
    # QDropEvent takes a QPointF; QDragMoveEvent still takes a QPoint.
    point = row.mapTo(queue, inside)
    return kind(QPointF(point) if kind.__name__ == "QDropEvent" else point,
                Qt.DropAction.MoveAction, mime,
                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


def _drop(queue, key, at_row, *, on_top_half=True):
    """Drop the row carrying ``key`` over the row at index ``at_row``."""
    from PyQt6.QtGui import QDropEvent

    queue.dropEvent(_drag_event(queue, QDropEvent, key, at_row, on_top_half=on_top_half))


def test_dropping_a_row_above_another_moves_it_there(queue):
    asked = []
    queue.reorder_requested.connect(asked.append)
    _four(queue)

    _drop(queue, "d", at_row=1)  # let the last one go over the first waiting row

    assert queue.keys() == ["a", "d", "b", "c"]
    assert asked == [["a", "d", "b", "c"]]


def test_dropping_a_row_onto_the_bottom_half_puts_it_after(queue):
    # The half of a row a drop lands on is what says above-or-below, so the same
    # gesture a few pixels lower means something different.
    _four(queue)

    _drop(queue, "b", at_row=2, on_top_half=False)

    assert queue.keys() == ["a", "c", "b", "d"]


def test_nothing_can_be_dropped_in_front_of_the_job_being_made(queue):
    _four(queue)

    _drop(queue, "d", at_row=0)  # aimed above the head of the line

    assert queue.keys() == ["a", "d", "b", "c"]  # it lands just behind it instead


def test_a_drag_over_the_strip_marks_where_it_would_land(queue):
    # The insertion mark is the whole reason a drop is predictable.
    from PyQt6.QtGui import QDragMoveEvent

    _four(queue)

    queue.dragMoveEvent(_drag_event(queue, QDragMoveEvent, "d", 2))

    assert queue._drop_at == 2


def test_the_mark_clears_when_the_drag_leaves(queue):
    from PyQt6.QtGui import QDragLeaveEvent, QDragMoveEvent

    _four(queue)
    queue.dragMoveEvent(_drag_event(queue, QDragMoveEvent, "d", 2))

    queue.dragLeaveEvent(QDragLeaveEvent())

    assert queue._drop_at is None


def test_a_move_that_changes_nothing_asks_for_nothing(queue):
    asked = []
    queue.reorder_requested.connect(asked.append)
    _four(queue)

    queue.move_row(2, 2)

    assert asked == []


def test_a_drop_carrying_something_else_is_ignored(queue):
    # Gallery thumbnails are dragged around this app too; one let go over the
    # strip must not be read as a reorder.
    from PyQt6.QtCore import QMimeData, QPointF, Qt
    from PyQt6.QtGui import QDropEvent

    asked = []
    queue.reorder_requested.connect(asked.append)
    _four(queue)
    mime = QMimeData()
    mime.setData("application/x-origenerator-generation", b"b")

    queue.dropEvent(QDropEvent(
        QPointF(5, 5), Qt.DropAction.MoveAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    ))

    assert asked == []
    assert queue.keys() == ["a", "b", "c", "d"]


def test_rows_are_the_height_that_shows_about_two_at_a_time(queue):
    _four(queue)
    assert all(row.height() == QueueRow.HEIGHT for row in queue.rows())


def test_cancel_leads_each_row_so_a_long_name_cannot_bury_it(queue):
    # The names run long and elide; a button behind one of those was pushed out of
    # sight at the right-hand end, which read as no way to cancel a queued item.
    from PyQt6.QtWidgets import QApplication

    _four(queue)
    QApplication.processEvents()
    row = queue.rows()[1]
    assert row._cancel.x() < row._caption.x()


def test_the_bar_leaves_the_strip_to_the_queue(queue):
    # It only has to read as a bar; the line beside it carries the long names.
    from PyQt6.QtWidgets import QApplication

    _four(queue)
    QApplication.processEvents()
    assert queue._scroll.width() > queue.running_preview().width()
