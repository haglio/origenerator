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
          started_at=None, typical_seconds=None, auto_generating=False,
          job_kind="", requested=False, source_image=None, folder_thumbnails=(),
          recipe_category="", recipe_thumbnail=None, starting=False):
    return InFlightItem(key=key, caption=caption, status=status, frame=frame,
                        reveal=reveal or (lambda: None), progress=progress, cancel=cancel,
                        foreign_ahead=foreign_ahead, held=held, started_at=started_at,
                        typical_seconds=typical_seconds, auto_generating=auto_generating,
                        job_kind=job_kind, requested=requested,
                        source_image=source_image, folder_thumbnails=folder_thumbnails,
                        recipe_category=recipe_category, recipe_thumbnail=recipe_thumbnail,
                        starting=starting)


def _picture(path, color=(0, 0, 255)):
    """A file standing in for a finished render, for the row's picture block."""
    from PIL import Image

    Image.new("RGB", (60, 40), color).save(path)
    return str(path)


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
    assert queue._running.key is None
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


def test_the_hint_sits_in_the_middle_of_the_whole_strip(queue):
    # The space it explains is the strip, not the part of it left over beside a
    # live half with nothing in it: centered in that sliver, it reads as pushed
    # off to the right.
    from PyQt6.QtWidgets import QApplication

    queue.set_items([])
    QApplication.processEvents()
    center = queue._hint.mapTo(queue, queue._hint.rect().center())

    assert abs(center.x() - queue.width() // 2) <= 4
    assert abs(center.y() - queue.height() // 2) <= 4


def test_the_live_half_stands_down_when_it_has_nothing_in_it(queue):
    # With no frame, no bar and nothing to report it is an empty third of the
    # strip, and the only thing it does there is push the hint off center.
    from PyQt6.QtWidgets import QApplication

    queue.set_items([])
    QApplication.processEvents()

    assert not queue._running.isVisible()


def test_the_live_half_keeps_its_place_to_report_another_apps_backlog(queue):
    # There it has something to say, and the hint centers in what is left.
    from PyQt6.QtWidgets import QApplication

    queue.set_items([], foreign_queued=2)
    QApplication.processEvents()

    hint_left = queue._hint.mapTo(queue, queue._hint.rect().topLeft()).x()

    assert queue._running.isVisible()
    assert queue._hint.isVisible()
    assert hint_left > queue._running.geometry().right()


def test_the_live_half_comes_back_with_the_first_job(queue):
    from PyQt6.QtWidgets import QApplication

    queue.set_items([])
    queue.set_items([_item(key="a")])
    QApplication.processEvents()

    assert queue._running.isVisible()


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


def test_the_clock_is_written_across_the_bar_it_measures(queue):
    # One object, not a line of text with a separate stripe under it: the numbers
    # are read off the face of the bar they measure, the way an in-flight card's
    # are.
    from PyQt6.QtWidgets import QApplication

    queue.set_items([_item(status="running", progress=(10, 20),
                           started_at=time.time() - 90.5, typical_seconds=725.0)])
    QApplication.processEvents()
    preview = queue._running

    assert preview._progress.caption() == "50% · 1:30 elapsed · ~6:02 left"
    assert preview._progress.isTextVisible()
    assert preview._caption.isHidden()  # the plain line stands down for the bar


def test_the_thumbnail_fills_the_strips_bottom_left_corner(queue):
    # The live frame is what the left half is for, so it takes the biggest square
    # the strip has room for — its height under the top rule — right into its
    # corner.
    from PyQt6.QtWidgets import QApplication

    queue.set_items([_item(status="running")])
    QApplication.processEvents()
    frame = queue._running._frame
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

    assert queue._running._frame.height() == _STRIP_HEIGHT
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
    frame = queue._running._frame

    assert frame.pixmap().height() == frame.height()


def test_the_left_half_follows_the_job_being_made(queue):
    queue.set_items([
        _item(key="a", caption="the one rendering", progress=(5, 20)),
        _item(key="b", caption="next", status="queued"),
    ])
    assert queue._running.key == "a"
    assert queue._running._progress.maximum() == 20
    assert queue._running._progress.value() == 5


def test_progress_is_indeterminate_without_step_counts(queue):
    # A queued job at the head, or a running one before its first progress tick,
    # shows a moving (indeterminate) bar rather than a stuck 0%.
    queue.set_items([_item(status="queued", progress=None)])
    assert queue._running._progress.maximum() == 0


def test_the_whole_queue_is_listed_the_job_being_made_first(queue):
    # Not the queue-except-its-head: every in-flight job has a row, so there is
    # one place that answers "what is queued".
    _four(queue)
    assert queue.keys() == ["a", "b", "c", "d"]


def test_the_line_moves_up_when_the_leader_finishes(queue):
    queue.set_items([_item(key="a"), _item(key="b", status="queued")])
    queue.set_items([_item(key="b", status="running")])
    assert queue.keys() == ["b"]
    assert queue._running.key == "b"


def test_a_live_frame_updates_the_rows_without_rebuilding_them(queue):
    # Rows carry a drag the user may be mid-gesture on, and rebuilding the list
    # every second and a half would yank it out from under them.
    queue.set_items([_item(key="a"), _item(key="b", status="queued")])
    row = queue.rows()[1]

    queue.set_items([_item(key="a", typical_seconds=30.0, progress=(3, 10)),
                     _item(key="b", status="queued", typical_seconds=600.0,
                           job_kind="I2V")])

    assert queue.rows()[1] is row
    assert row.lead() == "~10 min · I2V"


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

def test_the_left_half_says_what_the_bar_is_sweeping_behind(queue):
    # A job ComfyUI hasn't started leaves the bar's reading slot empty and the bar
    # sweeping, which is precisely when a sweeping bar is owed a reason.
    queue.set_items([_item(status="queued", foreign_ahead=3)])
    assert _timing(queue) == "Waiting behind 3 jobs from another app"


def test_one_job_ahead_reads_in_the_singular(queue):
    queue.set_items([_item(status="queued", foreign_ahead=1)])
    assert _timing(queue) == "Waiting behind 1 job from another app"


def test_the_row_does_not_repeat_the_wait(queue):
    # A row is about its own job. The shared server being busy is the whole
    # line's business, and belongs to the half that carries the bar it is holding
    # up — repeated down every row it says nothing about any of them.
    queue.set_items([_item(status="queued", foreign_ahead=3)])
    assert queue.rows()[0].note() == ""


def test_the_wait_is_written_under_the_bar_it_explains(queue):
    # Under the sweeping bar, not in place of it: the bar is the thing being
    # explained, and it goes on sweeping while the explanation sits beneath it.
    from PyQt6.QtWidgets import QApplication

    queue.set_items([_item(status="queued", foreign_ahead=3)])
    QApplication.processEvents()
    half = queue._running

    assert half._progress.isVisible() and half._progress.maximum() == 0  # sweeping
    assert half._caption.isVisible()
    assert half._caption.y() > half._progress.y()


def test_a_job_of_ours_being_made_keeps_the_slot_for_its_bar(queue):
    # Nothing is holding this one up, so there is nothing to explain and the line
    # under the bar stands down rather than sitting there empty.
    queue.set_items([_item(status="running", started_at=time.time() - 5.5)])
    assert not queue._running._caption.isVisible()


def test_the_users_own_queue_needs_no_explaining(queue):
    # His own jobs are the rows of this very list, so there is nothing left for a
    # wait note to tell him — the line itself is the answer, and neither half
    # says more than it always says.
    queue.set_items([_item(key="a", foreign_ahead=0),
                     _item(key="b", status="queued", foreign_ahead=0)])
    assert [row.note() for row in queue.rows()] == ["", ""]
    assert _timing(queue) == ""


# --- a queue holding work back for a slideshow --------------------------------

def test_a_held_row_says_what_it_is_waiting_on(queue):
    # A line that stops moving with the GPU idle is a mystery worth ending, and
    # this one ends by closing the show.
    queue.set_items([_item(status="queued", held=True)])
    assert queue.rows()[0].note() == "Held until the slideshow closes"


def test_the_free_half_says_the_hold_when_nothing_of_ours_runs(queue):
    queue.set_items([_item(key="a", status="queued", held=True),
                     _item(key="b", status="queued", held=True)])

    assert queue._running.key is None  # a held job has no frame to show
    assert _timing(queue) == "2 videos held until the slideshow closes"


def test_the_hold_is_said_before_another_apps_backlog(queue):
    # Both are reasons the machine isn't ours, but only one of them ends by
    # closing something in this window.
    queue.set_items([_item(status="queued", held=True)], foreign_queued=2)
    assert _timing(queue) == "1 video held until the slideshow closes"


def test_a_running_job_still_takes_the_half_while_others_are_held(queue):
    queue.set_items([_item(key="a", status="running", started_at=time.time() - 5.5),
                     _item(key="b", status="queued", held=True)])
    assert queue._running.key == "a"
    assert "elapsed" in _timing(queue)


# --- how long it's been, and how long is left ---------------------------------

def _timing(queue) -> str:
    return queue._running.status_text()


def test_shows_how_far_along_it_is_the_elapsed_time_and_what_is_left(queue):
    # A 12-minute video job 90 seconds in: the bar carries all three readings
    # instead of creeping along with nothing to measure it against, and the
    # percentage is written out rather than left to be eyeballed off the fill. The
    # half-seconds keep both clocks a clear half-second off a rollover, so the
    # time the test itself takes can't tip either one.
    queue.set_items([_item(status="running", progress=(10, 20),
                           started_at=time.time() - 90.5, typical_seconds=725.0)])
    assert _timing(queue) == "50% · 1:30 elapsed · ~6:02 left"


def test_shows_the_elapsed_time_alone_with_no_estimate(queue):
    # The first run of a workflow has no history behind it, and one step in it's
    # too early to pace off — the elapsed count still stands on its own.
    queue.set_items([_item(status="running", progress=(1, 20),
                           started_at=time.time() - 45.5)])
    assert _timing(queue) == "5% · 0:45 elapsed"


def test_no_clock_on_a_job_comfyui_has_not_started(queue):
    queue.set_items([_item(status="queued", started_at=None, typical_seconds=724.0)])
    assert _timing(queue) == ""


def test_the_clock_advances_between_polls(queue):
    # The gallery re-feeds the strip every 1.5s, which would make a seconds count
    # skip; the running half re-reads the clock itself so it moves a second at a
    # time.
    queue.set_items([_item(status="running", started_at=time.time() - 5.5)])
    assert _timing(queue) == "0:05 elapsed"
    queue._running._item.started_at -= 3  # as if three seconds had gone by
    queue._running._tick.timeout.emit()
    assert _timing(queue) == "0:08 elapsed"


def test_the_clock_stops_when_the_queue_empties(queue):
    queue.set_items([_item(status="running", started_at=time.time() - 5.5)])
    assert queue._running._tick.isActive()

    queue.set_items([])

    assert not queue._running._tick.isActive()
    assert _timing(queue) == ""


def test_another_apps_backlog_takes_the_slot_back_when_ours_empties(queue):
    # The bar and the foreign-queue line share the slot beside the frame: our
    # job's bar while we have one, their plain line when we don't — there is no
    # run of ours there for a bar to be measuring.
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


# --- what a row leads with: the price, the kind, and who asked ----------------

def test_a_row_leads_with_what_the_job_costs_and_what_it_is(queue):
    # A line of waiting work is read to find out how long the wait is, so the
    # price comes before the recipe — which is the same for every row of a folder
    # being re-rolled and so tells you nothing about the wait.
    queue.set_items([_item(typical_seconds=126.0, job_kind="I2V")])
    assert queue.rows()[0].lead() == "~2 min · I2V"


def test_a_row_says_when_nobody_typed_its_prompt(queue):
    # The two kinds of job that pile up without being noticed: an auto-generate
    # loop makes one every few seconds, and a spoken request never touched a form.
    queue.set_items([_item(typical_seconds=30.0, job_kind="Image",
                           auto_generating=True, requested=True)])
    assert queue.rows()[0].lead() == "~30 sec · Image · Auto · Request"


def test_a_hand_launched_job_says_neither(queue):
    queue.set_items([_item(typical_seconds=30.0, job_kind="Image")])
    assert queue.rows()[0].lead() == "~30 sec · Image"


def test_a_row_names_the_act_it_was_asked_for(queue):
    # "I2V" says a video is being made from a frame; the act says which video —
    # the whole of what the user chose in Combine, and the one thing separating
    # two runs on the same picture.
    queue.set_items([_item(typical_seconds=126.0, job_kind="I2V",
                           recipe_category="dancing")])
    assert queue.rows()[0].lead() == "~2 min · I2V · dancing"


def test_a_run_nobody_picked_an_act_for_names_none(queue):
    # A dropped video is the recipe itself: there was no dropdown choice to show,
    # and inventing one from its prompt would be a guess the row states as fact.
    queue.set_items([_item(typical_seconds=126.0, job_kind="I2V")])
    assert queue.rows()[0].lead() == "~2 min · I2V"


def test_the_hover_spells_out_where_the_act_came_from(queue):
    queue.set_items([_item(typical_seconds=126.0, job_kind="I2V",
                           recipe_category="dancing")])
    assert "“dancing” act" in queue.rows()[0]._lead.toolTip()


def test_a_workflow_nobody_has_timed_admits_it(queue):
    queue.set_items([_item(typical_seconds=None, job_kind="Image")])
    assert queue.rows()[0].lead() == "~? · Image"


def test_an_unregistered_workflow_leads_with_the_price_alone(queue):
    # An old import this build has no template for: it claims no kind rather than
    # guess one, and the row still says what it will cost.
    queue.set_items([_item(typical_seconds=30.0, job_kind="")])
    assert queue.rows()[0].lead() == "~30 sec"


def test_the_lead_outlives_a_row_that_is_explaining_a_wait(queue):
    # A held video still costs what it costs and is still the kind of thing it
    # is; why it is held goes in the note beside that, not over the top of it.
    queue.set_items([_item(key="a"),
                     _item(key="b", status="queued", held=True,
                           typical_seconds=600.0, job_kind="I2V")])
    row = queue.rows()[1]
    assert row.lead() == "~10 min · I2V"
    assert row.note() == "Held until the slideshow closes"


def test_the_hover_carries_the_name_the_row_no_longer_spends_width_on(queue):
    # The recipe is worth an answer, just not the row: every row of a folder
    # being re-rolled carries the same one. "I2V" and a bare "~?" are shorthand
    # a row has the width for and a first reader has no way to expand, so they
    # are spelled out in the same place.
    queue.set_items([_item(caption="Alpha Workflow › a kite", typical_seconds=None,
                           job_kind="I2V", requested=True)])
    tip = queue.rows()[0]._lead.toolTip()
    assert tip.startswith("Alpha Workflow › a kite")
    assert "No timing data" in tip
    assert "start frame" in tip
    assert "Queued by a request" in tip


# --- the picture a queued job can be recognized by ----------------------------

def test_an_image_to_video_row_shows_the_frame_it_animates(queue, tmp_path):
    # Two i2v rows off one recipe carry the same caption; the frame is the whole
    # of what tells them apart.
    frame = _picture(tmp_path / "frame.png")
    queue.set_items([_item(job_kind="I2V", source_image=frame,
                           folder_thumbnails=(_picture(tmp_path / "other.png"),))])
    assert queue.rows()[0]._thumbs._showing == ("source", frame, None)


def test_a_row_with_no_frame_shows_what_its_folder_holds(queue, tmp_path):
    # A job whose output doesn't exist yet is placed by the folder it will land
    # in — what the same settings made last time.
    mates = tuple(_picture(tmp_path / f"{i}.png") for i in range(3))
    queue.set_items([_item(job_kind="Image", folder_thumbnails=mates)])
    assert queue.rows()[0]._thumbs._showing == ("folder", mates)


def test_a_frame_that_has_not_rendered_yet_falls_back_to_the_folder(queue, tmp_path):
    # A video queued behind the image it animates names a start frame that isn't
    # on disk. Better its folder than a blank square where a picture was promised.
    mates = (_picture(tmp_path / "mate.png"),)
    queue.set_items([_item(job_kind="I2V", source_image=str(tmp_path / "not-yet.png"),
                           folder_thumbnails=mates)])
    assert queue.rows()[0]._thumbs._showing == ("folder", mates)


def test_a_combine_row_shows_the_frame_and_the_recipe_it_follows(queue, tmp_path):
    # Not the recipe video alone: that reads as a job that IS that clip. The
    # frame being animated leads, and the video whose settings are being reused
    # sits beside it (drawn gray, see queue_thumbs).
    frame = _picture(tmp_path / "frame.png")
    recipe = _picture(tmp_path / "recipe.png", color=(255, 0, 0))
    queue.set_items([_item(job_kind="I2V", source_image=frame, recipe_thumbnail=recipe,
                           folder_thumbnails=(_picture(tmp_path / "other.png"),))])
    assert queue.rows()[0]._thumbs._showing == ("source", frame, recipe)


def test_a_combine_row_keeps_its_recipe_while_the_frame_is_still_rendering(queue, tmp_path):
    # A chained run draws its frame first, so the video behind it names one that
    # isn't on disk yet. The recipe is about this run either way — better it than
    # the folder, which says only where the result will land.
    recipe = _picture(tmp_path / "recipe.png", color=(255, 0, 0))
    queue.set_items([_item(job_kind="I2V", source_image=str(tmp_path / "not-yet.png"),
                           recipe_thumbnail=recipe,
                           folder_thumbnails=(_picture(tmp_path / "mate.png"),))])
    assert queue.rows()[0]._thumbs._showing == ("source", None, recipe)


def test_a_row_that_is_not_a_job_yet_says_so(queue):
    # The press of Generate has an answer on screen before the work that turns it
    # into a job is done — otherwise the button reads as one that did nothing.
    queue.set_items([_item(status="queued", job_kind="I2V", recipe_category="dancing",
                           cancel=None, starting=True)])
    row = queue.rows()[0]

    assert row.note() == "Starting…"
    assert row.lead() == "~? · I2V · dancing"   # what is known of it already
    assert row._cancel.isHidden()               # nothing on the server to stop yet
    assert "Not sent to ComfyUI yet" in row._lead.toolTip()


def test_a_started_job_stops_saying_it_is_starting(queue):
    queue.set_items([_item(status="queued", job_kind="I2V")])
    assert queue.rows()[0].note() == ""


def test_a_wait_note_too_long_for_the_row_is_elided_not_clipped(queue):
    # Clipped, the last word is cut mid-letter and reads as a rendering fault;
    # elided, the row says outright that there is more, and the hover has it.
    from PyQt6.QtWidgets import QApplication

    queue.resize(300, 60)  # the strip squeezed narrow, as a tiled window does
    queue.set_items([_item(status="queued", held=True)])
    QApplication.processEvents()
    row = queue.rows()[0]

    assert row._note.text().endswith("…")
    assert row.note() == "Held until the slideshow closes"
    assert row._note.toolTip() == row.note()


def test_the_picture_sits_at_the_near_edge_of_the_line(queue, tmp_path):
    # Straight after the button rather than out past the text: there the blocks
    # stack into a column at the edge the eye starts from, and a row whose text
    # runs long can never carry one off the far end.
    from PyQt6.QtWidgets import QApplication

    queue.set_items([_item(job_kind="Image", status="queued", held=True,
                           folder_thumbnails=(_picture(tmp_path / "m.png"),))])
    QApplication.processEvents()
    row = queue.rows()[0]

    assert row._cancel.x() < row._thumbs.x() < row._lead.x() < row._note.x()


def test_a_job_with_nothing_to_show_carries_no_block(queue):
    # The first run of a brand-new recipe: no frame, and an empty folder. An empty
    # grid would read as a picture that failed to load.
    queue.set_items([_item(job_kind="Image")])
    assert queue.rows()[0]._thumbs.isHidden()


def test_rows_are_the_height_that_shows_about_two_at_a_time(queue):
    _four(queue)
    assert all(row.height() == QueueRow.HEIGHT for row in queue.rows())


def test_cancel_leads_each_row_so_nothing_can_bury_it(queue):
    # A button behind a line that can elide was pushed out of sight at the
    # right-hand end, which read as no way to cancel a queued item.
    from PyQt6.QtWidgets import QApplication

    _four(queue)
    QApplication.processEvents()
    row = queue.rows()[1]
    assert row._cancel.x() < row._lead.x()


def test_the_bar_leaves_the_strip_to_the_queue(queue):
    # It only has to read as a bar; the line beside it carries the long names.
    from PyQt6.QtWidgets import QApplication

    _four(queue)
    QApplication.processEvents()
    assert queue._scroll.width() > queue._running.width()
