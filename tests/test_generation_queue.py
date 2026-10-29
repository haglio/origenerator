from __future__ import annotations

import time

import pytest
from PIL import Image
from PyQt6 import sip
from PyQt6.QtCore import QBuffer, QCoreApplication, QEvent, QMimeData, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QDrag, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QMouseEvent, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from shared_ui.colors import BLUE, BORDER_SUBTLE

from origenerator.gui.combination import Combination
from origenerator.gui.generation_queue import (
    _STRIP_HEIGHT,
    QUEUE_ROW_MIME,
    GenerationQueue,
    QueueRow,
)
from origenerator.gui.inflight import InFlightItem, RunReading
from origenerator.gui.stylesheet import build_stylesheet
from tests.marked_words import words


@pytest.fixture
def queue(qtbot):
    q = GenerationQueue()
    qtbot.addWidget(q)
    q.resize(800, 60)
    q.show()
    return q


@pytest.fixture
def dressed(qtbot):
    # The app's own style sheet grounds the column the rows sit in, so anything
    # painted beneath that column is painted out of sight.
    q = GenerationQueue()
    q.setStyleSheet(build_stylesheet())
    qtbot.addWidget(q)
    q.resize(1100, 60)  # room for a whole row beside Shield All and Cancel All
    with qtbot.waitExposed(q):
        q.show()
    return q


_EITHER_WAY = object()  # an arrow left to follow ``movable``


def _item(key="j1", caption="Alpha Workflow › a kite", status="running", frame=None,
          progress=None, reveal=None, cancel=None, foreign_ahead=None, starts_at=None,
          started_at=None, typical_seconds=None, auto_generating=False,
          job_kind="", requested=False, source_image=None, folder_thumbnails=(),
          act="", source_video_thumbnail=None, prompt_edited=False,
          starting=False, movable=None, shield=None, shielded=False,
          move_up=_EITHER_WAY, move_down=_EITHER_WAY):
    # The job being made holds its place unless a test says it can be moved.
    move = (lambda: None) if (status != "running" if movable is None else movable) else None
    return InFlightItem(key=key, caption=caption,
                        move_up=move if move_up is _EITHER_WAY else move_up,
                        move_down=move if move_down is _EITHER_WAY else move_down,
                        reading=RunReading(status=status, frame=frame, progress=progress,
                                           started_at=started_at,
                                           typical_seconds=typical_seconds),
                        reveal=reveal or (lambda: None), cancel=cancel,
                        foreign_ahead=foreign_ahead, starts_at=starts_at,
                        auto_generating=auto_generating,
                        job_kind=job_kind, requested=requested,
                        source_image=source_image, folder_thumbnails=folder_thumbnails,
                        act=act, source_video_thumbnail=source_video_thumbnail,
                        prompt_edited=prompt_edited, starting=starting,
                        shield=shield, shielded=shielded)


def _image(path, color=(0, 0, 255)):
    """A file standing in for a finished render, for the row's thumbnail block."""
    Image.new("RGB", (60, 40), color).save(path)
    return str(path)


def _png_bytes(side=200):
    """A plain square PNG, standing in for a live frame off ComfyUI."""
    pixmap = QPixmap(side, side)
    pixmap.fill()
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    return bytes(buffer.data())


def _four(queue):
    queue.set_items([_item(key="a"), _item(key="b", status="queued"),
                     _item(key="c", status="queued"), _item(key="d", status="queued")])


def _settled(queue):
    """The strip as it stands put on screen whole, so that what changes after
    this shows only where it is repainted."""
    QApplication.processEvents()
    queue.repaint()


def _on_screen(queue):
    """What the strip's window shows, including whatever was never repainted."""
    return QApplication.primaryScreen().grabWindow(queue.winId()).toImage()


def _drawn(image, points, color) -> bool:
    """Whether every pixel along a run of straight lines wears ``color``."""
    for start, end in zip(points, points[1:]):
        for x in range(min(start.x(), end.x()), max(start.x(), end.x()) + 1):
            for y in range(min(start.y(), end.y()), max(start.y(), end.y()) + 1):
                if image.pixelColor(x, y).name() != color.name():
                    return False
    return True


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

    queue.set_items([])
    QApplication.processEvents()

    assert queue._hint.isVisible()
    assert queue._hint.text() == "(queued jobs show up here)"
    assert queue._hint.objectName() == "estimateLabel"  # the app's muted text


def test_the_hint_sits_in_the_middle_of_the_whole_strip(queue):
    # The space it explains is the strip, not the part of it left over beside a
    # live half with nothing in it: centered in that sliver, it reads as pushed
    # off to the right.

    queue.set_items([])
    QApplication.processEvents()
    center = queue._hint.mapTo(queue, queue._hint.rect().center())

    assert abs(center.x() - queue.width() // 2) <= 4
    assert abs(center.y() - queue.height() // 2) <= 4


def test_the_live_half_stands_down_when_it_has_nothing_in_it(queue):
    # With no frame, no bar and nothing to report it is an empty third of the
    # strip, and the only thing it does there is push the hint off center.

    queue.set_items([])
    QApplication.processEvents()

    assert not queue._running.isVisible()


def test_the_live_half_keeps_its_place_to_report_another_apps_backlog(queue):
    # There it has something to say, and the hint centers in what is left.

    queue.set_items([], foreign_queued=2)
    QApplication.processEvents()

    hint_left = queue._hint.mapTo(queue, queue._hint.rect().topLeft()).x()

    assert queue._running.isVisible()
    assert queue._hint.isVisible()
    assert hint_left > queue._running.geometry().right()


def test_the_live_half_comes_back_with_the_first_job(queue):
    queue.set_items([])
    queue.set_items([_item(key="a")])
    QApplication.processEvents()

    assert queue._running.isVisible()


def test_the_first_job_takes_the_space_back_from_the_hint(queue):
    queue.set_items([])
    queue.set_items([_item(key="a")])
    QApplication.processEvents()

    assert not queue._hint.isVisible()
    assert queue.keys() == ["a"]  # and it was never a row of the line itself


def test_the_hint_comes_back_when_the_queue_drains(queue):
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

    queue.set_items([_item(status="running", progress=(10, 20),
                           started_at=time.time() - 90.5, typical_seconds=725.0)])
    QApplication.processEvents()
    preview = queue._running

    assert preview._progress.caption() == "50% · 1:30 elapsed · ~6:02 left"
    assert preview._progress.isTextVisible()
    assert not preview._caption.isVisible()  # the plain line stands down for the bar


def test_the_thumbnail_fills_the_strip_from_its_top_edge_into_its_lower_left_corner(queue):
    # The live frame is what the left half is for, so it takes the biggest square
    # the strip has room for, right into its corner. The splitter handle above
    # the strip is its top border, so no line of the strip's own sits over it.

    queue.set_items([_item(status="running")])
    QApplication.processEvents()
    frame = queue._running._frame
    top_left = frame.mapTo(queue, frame.rect().topLeft())

    assert frame.width() == frame.height() == queue.height()
    assert (top_left.x(), top_left.y()) == (0, 0)


def test_a_strip_dragged_open_gives_the_room_to_the_line(queue):
    # It is opened to read the queue, not to be shown one enormous frame: the
    # thumbnail stops at the strip's own opening height and the rows take the rest.


    queue.set_items([_item(status="running")])
    queue.resize(800, 400)
    QApplication.processEvents()

    assert queue._running._frame.height() == _STRIP_HEIGHT
    assert queue._scroll.height() > _STRIP_HEIGHT


def test_the_strip_can_be_dragged_taller_but_not_shorter_than_a_bar(queue):
    assert queue.minimumHeight() == _STRIP_HEIGHT
    assert queue.maximumHeight() > _STRIP_HEIGHT  # not pinned to its opening height


def test_the_live_frame_is_drawn_at_the_size_of_that_square(queue):
    # Sizing the label alone would leave the thumbnail its old size in the middle
    # of a bigger blank square.

    queue.set_items([_item(status="running", frame=_png_bytes())])
    QApplication.processEvents()
    frame = queue._running._frame

    assert frame.pixmap().height() == frame.height()


def test_the_corner_stands_the_start_frame_until_a_live_one_arrives(queue, tmp_path):
    # The complaint this answers: a WAN run spends over a minute loading models
    # before ComfyUI streams a preview, and this corner was blank for all of it.
    # It shows what the config tab shows for the same job — the frame being
    # animated — until there is a frame of the run itself.

    frame = _image(tmp_path / "frame.png")
    queue.set_items([_item(job_kind="Video", source_image=frame)])
    QApplication.processEvents()
    corner = queue._running._frame

    assert corner.pixmap() is not None and not corner.pixmap().isNull()
    assert corner.width() == corner.height()   # one thumbnail, one square


def test_the_corner_stands_the_source_video_beside_the_frame_where_there_is_one(queue, tmp_path):
    # A combine's job is an image and a past clip's settings, and that is what
    # the config tab shows above the form. The corner says the same thing, the
    # clip drawn gray beside the frame — so it needs the room for two.

    frame = _image(tmp_path / "frame.png")
    video = _image(tmp_path / "source.png", color=(255, 0, 0))
    queue.set_items([_item(job_kind="Video", source_image=frame, source_video_thumbnail=video)])
    QApplication.processEvents()
    corner = queue._running._frame

    assert corner.width() > corner.height()


def test_a_live_frame_takes_the_corner_back_from_the_start_frame(queue, tmp_path):
    # Once the run has a thumbnail of its own, that is what the corner is for.

    frame = _image(tmp_path / "frame.png")
    queue.set_items([_item(job_kind="Video", source_image=frame, frame=_png_bytes())])
    QApplication.processEvents()
    corner = queue._running._frame

    assert corner.pixmap().height() == corner.height()
    assert corner.width() == corner.height()


def test_a_run_made_from_nothing_leaves_the_corner_empty(queue):
    # An image drawn from a prompt has no thumbnail to its name yet, and a stand-in
    # for one would be a thumbnail of something that has nothing to do with it.

    queue.set_items([_item(job_kind="Image")])
    QApplication.processEvents()

    assert queue._running._frame.pixmap().isNull()


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
                           job_kind="Video")])

    assert queue.rows()[1] is row
    assert row._lead.text() == "~10 min · Video"


# --- the rule between the job being made and the jobs behind it ---------------

def test_a_rule_runs_up_beside_the_live_half_and_along_the_foot_of_its_row(queue):
    # The job being made is shown twice, as the whole left half and as the top
    # row of the line. The rule says the two are one: up the gap between the
    # halves from the strip's foot to the foot of that row, then along the
    # row's foot to its end, walling off only the jobs waiting behind it.
    _four(queue)
    QApplication.processEvents()
    head = queue.rows()[0]
    foot = head.mapTo(queue, head.rect().bottomRight())

    up, corner, along = queue.head_rule()

    assert queue._running.geometry().right() < up.x() == corner.x() < queue._scroll.x()
    assert up.y() == queue.height() - 1
    assert (corner.y(), along.y(), along.x()) == (foot.y(), foot.y(), foot.x())


def test_the_rule_stands_midway_between_the_bar_and_the_arrows_leading_the_rows(queue):
    # Give or take the one pixel a gap of even width cannot split.
    queue.set_items([_item(key="a", cancel=lambda: None),
                     _item(key="b", status="queued", cancel=lambda: None)])
    QApplication.processEvents()
    rule = queue.head_rule()[0].x()
    bar_ends = queue._running.geometry().right()
    up = queue.rows()[1]._up
    up_starts = up.mapTo(queue, up.rect().topLeft()).x()

    assert abs((rule - bar_ends) - (up_starts - rule)) <= 1


def test_no_rule_stands_beside_another_apps_backlog_with_nothing_of_ours_in_it(queue):
    # The left half is up to say what another app is doing, but with no job of
    # ours in the line there is no row of it to join to that half.
    queue.set_items([], foreign_queued=2)

    assert queue.head_rule() == []


def test_a_line_scrolled_past_its_head_runs_the_rule_straight_up_the_strip(queue):
    # The left half then stands beside nothing but jobs waiting behind it, so
    # the rule keeps it apart from every one of them.
    queue.set_items([_item(key=f"j{i}", status="queued") for i in range(6)])
    QApplication.processEvents()
    bar = queue._scroll.verticalScrollBar()
    bar.setValue(bar.maximum())

    up, top = queue.head_rule()

    assert up.x() == top.x()
    assert (up.y(), top.y()) == (queue.height() - 1, 0)


def _rule_on_screen(queue):
    return _drawn(_on_screen(queue), queue.head_rule(), BORDER_SUBTLE)


def test_the_rule_is_drawn_over_the_rows_in_the_apps_own_dress(dressed, qtbot):
    _four(dressed)

    qtbot.waitUntil(lambda: _rule_on_screen(dressed))


def test_the_rule_rides_up_with_the_head_row_as_the_line_scrolls(dressed, qtbot):
    # Nothing is left standing in the gap where the corner was, either.
    _four(dressed)
    _settled(dressed)
    was = dressed.head_rule()[1]

    dressed._scroll.verticalScrollBar().setValue(20)

    qtbot.waitUntil(lambda: _rule_on_screen(dressed))
    where_the_corner_was = QPoint(dressed._scroll.x() - 1, was.y())
    assert _on_screen(dressed).pixelColor(where_the_corner_was).name() != BORDER_SUBTLE.name()


def test_our_first_job_beside_another_apps_backlog_brings_its_rule(dressed, qtbot):
    # The left half is up already, saying what the other app is doing, so
    # nothing on that side moves when our job arrives; the rule comes up anyway.
    dressed.set_items([], foreign_queued=2)
    _settled(dressed)

    dressed.set_items([_item(status="queued", foreign_ahead=2)], foreign_queued=2)

    qtbot.waitUntil(lambda: _rule_on_screen(dressed))


def test_the_rule_keeps_to_the_gap_when_the_live_half_widens(dressed, qtbot, tmp_path):
    # A combine's job stands its frame and its source video side by side in the
    # corner, twice the width of one thumbnail, which pushes the line over.
    dressed.set_items([_item(job_kind="Video")])
    _settled(dressed)
    was = dressed.head_rule()[0]

    dressed.set_items([_item(job_kind="Video", source_image=_image(tmp_path / "frame.png"),
                             source_video_thumbnail=_image(tmp_path / "source.png"))])

    qtbot.waitUntil(lambda: dressed.head_rule()[0].x() > was.x() and _rule_on_screen(dressed))
    assert _on_screen(dressed).pixelColor(was).name() != BORDER_SUBTLE.name()


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


def test_cancel_is_grayed_out_on_a_job_that_cannot_be_stopped_from_here(queue):
    # His answer (2026-10-29): grayed out like the arrows, rather than left off.
    queue.set_items([_item(key="a", cancel=None)])
    QApplication.processEvents()
    cancel = queue.rows()[0]._cancel
    assert (cancel.isVisible(), cancel.isEnabled()) == (True, False)
    assert cancel.cursor().shape() == Qt.CursorShape.ArrowCursor


def test_a_row_from_an_auto_generating_folder_says_cancel_too(queue):
    # His call (2026-10-28): every row's button says Cancel. Auto-Generate in
    # that folder still starts its next seed, as the hover says.
    queue.set_items([_item(key="a", cancel=lambda: None, auto_generating=True),
                     _item(key="b", status="queued", cancel=lambda: None)])
    assert [row._cancel.text() for row in queue.rows()] == ["Cancel", "Cancel"]
    assert queue.rows()[0]._cancel.toolTip() == "Throw away this seed and start the next"


def test_a_rows_cancel_hover_follows_its_folders_auto_generate_in_place(queue):
    # Auto off with the run still in flight: the same row's press is a plain cancel
    # again, and rows are updated in place rather than rebuilt.
    queue.set_items([_item(key="a", cancel=lambda: None, auto_generating=True)])
    row = queue.rows()[0]

    queue.set_items([_item(key="a", cancel=lambda: None)])

    assert queue.rows() == [row]
    assert row._cancel.toolTip() == "Cancel this generation"


# --- the arrows, which move a job one place up or down the line ---------------

def test_every_row_leads_with_an_up_and_a_down_arrow_ahead_of_its_shield(queue):
    queue.set_items([_item(key="a", cancel=lambda: None, shield=lambda _on: None),
                     _item(key="b", status="queued", cancel=lambda: None,
                           shield=lambda _on: None)])
    QApplication.processEvents()

    rows = queue.rows()
    for row in rows:
        up, down, shield = row._up.geometry(), row._down.geometry(), row._shield.geometry()
        assert up.right() < down.left() and down.right() < shield.left()
    assert len({row._up.geometry().x() for row in rows}) == 1


def test_pressing_an_arrow_moves_its_job_that_way(queue, qtbot):
    asked = []
    queue.set_items([_item(key="a", status="queued", move_up=lambda: asked.append("up"),
                           move_down=lambda: asked.append("down"))])
    row = queue.rows()[0]

    qtbot.mouseClick(row._up, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(row._down, Qt.MouseButton.LeftButton)

    assert asked == ["up", "down"]


def test_an_arrow_its_job_cannot_go_is_grayed_out(queue):
    # The top row's up arrow, say: the arrows stay in their column either way.
    queue.set_items([_item(key="a", status="queued", move_up=None, move_down=lambda: None)])
    QApplication.processEvents()
    row = queue.rows()[0]

    assert (row._up.isVisible(), row._up.isEnabled()) == (True, False)
    assert row._up.cursor().shape() == Qt.CursorShape.ArrowCursor  # no hand: nothing to press
    assert row._down.isEnabled()
    assert row._down.cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_a_press_on_a_grayed_arrow_does_nothing_at_all(queue):
    # Not even the folder the rest of the row opens, nor a drag of the row.
    revealed = []
    queue.set_items([_item(key="a", status="queued", reveal=lambda: revealed.append(True),
                           move_up=None, move_down=lambda: None)])
    QApplication.processEvents()
    up = queue.rows()[0]._up
    on_it = up.mapTo(queue.window(), up.rect().center())

    QTest.mouseClick(queue.window().windowHandle(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, on_it)
    QTest.mouseDClick(queue.window().windowHandle(), Qt.MouseButton.LeftButton,
                      Qt.KeyboardModifier.NoModifier, on_it)

    assert revealed == []
    assert queue.rows()[0]._press_at is None


def test_a_rows_arrows_follow_where_its_job_can_go_in_place(queue):
    queue.set_items([_item(key="a", status="queued", move_up=None, move_down=lambda: None)])
    row = queue.rows()[0]

    queue.set_items([_item(key="a", status="queued", move_up=lambda: None, move_down=None)])

    assert queue.rows() == [row]
    assert (row._up.isEnabled(), row._down.isEnabled()) == (True, False)


def test_a_rows_text_elides_rather_than_widen_the_row_past_a_narrow_strip(queue):
    queue.resize(900, 60)
    queue.set_items([_item(key="a", status="queued", job_kind="Video",
                           act="an act with a name long enough to run past the strip",
                           cancel=lambda: None, shield=lambda _on: None)])
    QApplication.processEvents()
    row = queue.rows()[0]

    assert row.width() <= queue._scroll.viewport().width()
    assert row._lead.display_text(row._lead.width()).endswith("…")
    assert row._lead.text().endswith("past the strip")


# --- the shield, which keeps a run going for the images asked for after it ----

def test_every_rows_shield_sits_just_left_of_its_cancel(queue):
    queue.set_items([_item(key="a", cancel=lambda: None, shield=lambda _on: None),
                     _item(key="b", status="queued", cancel=lambda: None,
                           shield=lambda _on: None, auto_generating=True)])
    QApplication.processEvents()

    rows = queue.rows()
    assert all(row._shield.isVisible() for row in rows)
    assert all(row._shield.geometry().right() < row._cancel.geometry().left()
               for row in rows)
    assert len({row._shield.geometry().x() for row in rows}) == 1


def test_pressing_a_rows_shield_puts_it_on_through_its_job(queue):
    asked = []
    queue.set_items([_item(key="a", cancel=lambda: None, shield=asked.append)])
    shield = queue.rows()[0]._shield

    shield.click()

    assert asked == [True]
    assert shield.isChecked()


def test_a_rows_shield_shows_whether_its_job_is_shielded_and_follows_it_in_place(queue):
    queue.set_items([_item(key="a", cancel=lambda: None, shield=lambda _on: None,
                           shielded=True)])
    row = queue.rows()[0]
    assert row._shield.isChecked()

    queue.set_items([_item(key="a", cancel=lambda: None, shield=lambda _on: None)])

    assert queue.rows() == [row]
    assert not row._shield.isChecked()


def test_the_shield_is_grayed_out_on_a_job_that_cannot_be_shielded_from_here(queue):
    # His answer (2026-10-29), with the Cancel's.
    queue.set_items([_item(key="a")])
    QApplication.processEvents()
    shield = queue.rows()[0]._shield
    assert (shield.isVisible(), shield.isEnabled()) == (True, False)
    assert shield.cursor().shape() == Qt.CursorShape.ArrowCursor


def test_pressing_the_shield_does_not_also_open_the_folder(queue, qtbot):
    revealed = []
    queue.set_items([_item(key="a", reveal=lambda: revealed.append(True),
                           cancel=lambda: None, shield=lambda _on: None)])
    QApplication.processEvents()

    qtbot.mouseClick(queue.rows()[0]._shield, Qt.MouseButton.LeftButton)

    assert revealed == []


# --- Shield All and Cancel All, stacked at the right end of the strip ---------

def _box(queue, widget) -> QRect:
    return QRect(widget.mapTo(queue, QPoint(0, 0)), widget.size())


def test_shield_all_and_cancel_all_stand_stacked_at_the_right_end_of_the_strip(queue):
    # His pick of four mockups (2026-10-28): the fourth.
    queue.set_items([_item(key="a", cancel=lambda: None, shield=lambda _on: None),
                     _item(key="b", status="queued", cancel=lambda: None,
                           shield=lambda _on: None)])
    QApplication.processEvents()

    shield_all, cancel_all = _box(queue, queue._shield_all), _box(queue, queue._cancel_all)
    assert queue._scroll.geometry().right() < shield_all.left() == cancel_all.left()
    assert shield_all.bottom() < cancel_all.top()
    above, below = shield_all.top(), queue.height() - 1 - cancel_all.bottom()
    assert abs(above - below) <= 1


def test_an_empty_job_queue_leaves_shield_all_and_cancel_all_off(queue):
    # His answer (2026-10-29): off, so the empty Job Queue looks as it always did.
    assert not (queue._shield_all.isVisible() or queue._cancel_all.isVisible())

    queue.set_items([_item(key="a", cancel=lambda: None, shield=lambda _on: None)])
    assert queue._shield_all.isVisible() and queue._cancel_all.isVisible()

    queue.set_items([])
    assert not (queue._shield_all.isVisible() or queue._cancel_all.isVisible())


def test_shield_all_wears_the_shield_followed_by_all(queue):
    queue.set_items([_item(key="a", cancel=lambda: None, shield=lambda _on: None)])

    assert queue._shield_all.text() == "All"
    assert not queue._shield_all.icon().isNull()
    assert queue._shield_all.iconSize() == queue.rows()[0]._shield.iconSize()
    assert queue._cancel_all.text() == "Cancel All"


def test_shield_all_puts_the_shield_on_every_job_that_has_none(queue):
    asked = []
    queue.set_items([_item(key="a", shield=lambda on: asked.append(("a", on)), shielded=True),
                     _item(key="b", status="queued", shield=lambda on: asked.append(("b", on))),
                     _item(key="c", status="queued")])  # one this window cannot shield

    queue._shield_all.click()

    assert asked == [("b", True)]
    assert [row._shield.isChecked() for row in queue.rows()] == [True, True, False]


def test_shield_all_is_grayed_out_while_no_job_is_left_for_it_to_shield(queue):
    # His answer (2026-10-29) for a line already shielded, which a line of jobs that
    # take no shield from here reaches too: either way a press would do nothing.
    queue.set_items([_item(key="a", shield=lambda _on: None, shielded=True),
                     _item(key="b", status="queued")])
    assert (queue._shield_all.isVisible(), queue._shield_all.isEnabled()) == (True, False)
    assert queue._shield_all.cursor().shape() == Qt.CursorShape.ArrowCursor

    queue.set_items([_item(key="a", shield=lambda _on: None, shielded=True),
                     _item(key="b", status="queued", shield=lambda _on: None)])
    assert queue._shield_all.isEnabled()
    assert queue._shield_all.cursor().shape() == Qt.CursorShape.PointingHandCursor

    queue._shield_all.click()
    assert not queue._shield_all.isEnabled()


def test_cancel_all_is_grayed_out_while_no_job_in_the_queue_can_be_canceled(queue):
    # His answer (2026-10-29), like Shield All's, for a line of jobs this window has
    # no Cancel for, as when a restart has not taken them back yet.
    queue.set_items([_item(key="a"), _item(key="b", status="queued")])
    assert (queue._cancel_all.isVisible(), queue._cancel_all.isEnabled()) == (True, False)
    assert queue._cancel_all.cursor().shape() == Qt.CursorShape.ArrowCursor

    queue.set_items([_item(key="a"), _item(key="b", status="queued", cancel=lambda: None)])
    assert queue._cancel_all.isEnabled()
    assert queue._cancel_all.cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_cancel_all_is_asked_of_whoever_holds_the_jobs(queue, qtbot):
    # It asks before anything goes, which is the gallery's to do.
    queue.set_items([_item(key="a", cancel=lambda: None)])

    with qtbot.waitSignal(queue.cancel_all_requested, timeout=1000):
        queue._cancel_all.click()


# --- clicking a row goes to the job's folder ----------------------------------

def test_clicking_a_row_reveals_that_jobs_folder(queue, qtbot):
    revealed = []
    queue.set_items([
        _item(key="a", reveal=lambda: revealed.append("a")),
        _item(key="b", status="queued", reveal=lambda: revealed.append("b")),
    ])
    qtbot.mouseClick(queue.rows()[1], Qt.MouseButton.LeftButton)
    assert revealed == ["b"]


def test_double_clicking_a_row_opens_that_folder_too(queue, qtbot):
    """A row opens on the first click, and the gesture people reach for on a
    listing is a double one — which must land on the same folder rather than
    fall between the two presses."""
    revealed = []
    queue.set_items([_item(key="a", status="queued",
                           reveal=lambda: revealed.append("a"))])
    qtbot.mouseDClick(queue.rows()[0], Qt.MouseButton.LeftButton)
    assert revealed and set(revealed) == {"a"}


def test_the_live_frame_opens_the_running_jobs_folder_too(queue, qtbot):
    """The thumbnail of what is being made is a thumbnail of a job, so it goes where
    that job's row goes — the same click, the same folder."""
    revealed = []
    queue.set_items([_item(key="a", reveal=lambda: revealed.append("a"))])
    QApplication.processEvents()

    frame = queue._running._frame
    qtbot.mouseClick(frame, Qt.MouseButton.LeftButton)
    qtbot.mouseDClick(frame, Qt.MouseButton.LeftButton)
    assert revealed and set(revealed) == {"a"}


def test_the_bar_beside_the_live_frame_is_not_a_way_into_a_folder(queue, qtbot):
    """The bar is a reading of the job rather than a thumbnail of it, and the note
    under it is about the shared server — neither is something you click through
    to a folder."""
    revealed = []
    queue.set_items([_item(key="a", reveal=lambda: revealed.append("a"))])
    QApplication.processEvents()

    qtbot.mouseClick(queue._running._progress, Qt.MouseButton.LeftButton)
    assert revealed == []


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
    assert _timing(queue) == "Waiting on 3 jobs from another app"


def test_one_job_ahead_reads_in_the_singular(queue):
    queue.set_items([_item(status="queued", foreign_ahead=1)])
    assert _timing(queue) == "Waiting on 1 job from another app"


def test_the_row_does_not_repeat_the_wait(queue):
    # A row is about its own job. The shared server being busy is the whole
    # line's business, and belongs to the half that carries the bar it is holding
    # up — repeated down every row it says nothing about any of them.
    queue.set_items([_item(status="queued", foreign_ahead=3)])
    assert queue.rows()[0]._note_text == ""


def test_the_wait_is_written_under_the_bar_it_explains(queue):
    # Under the sweeping bar, not in place of it: the bar is the thing being
    # explained, and it goes on sweeping while the explanation sits beneath it.

    queue.set_items([_item(status="queued", foreign_ahead=3)])
    QApplication.processEvents()
    half = queue._running

    assert half._progress.isVisible() and half._progress.maximum() == 0  # sweeping
    assert half._caption.isVisible()
    assert half._caption.mapTo(half, QPoint(0, 0)).y() > half._progress.y()


def test_a_job_of_ours_being_made_keeps_the_slot_for_its_bar(queue):
    # Nothing is holding this one up, so there is nothing to explain and the line
    # under the bar stands down rather than sitting there empty.
    queue.set_items([_item(status="running", started_at=time.time() - 5.5)])
    assert not queue._running._caption.isVisible()


def test_a_video_waiting_out_the_minute_after_an_image_counts_down_under_the_bar(queue):
    # The half-second keeps the count a clear half-second off a rollover.
    queue.set_items([_item(status="queued", starts_at=time.monotonic() + 42.5)])
    assert _timing(queue) == "Starts in 0:43"


def test_the_countdown_advances_between_polls(queue):
    queue.set_items([_item(status="queued", starts_at=time.monotonic() + 42.5)])
    queue._running._item.starts_at -= 3  # as if three seconds had gone by
    queue._running._tick.timeout.emit()
    assert _timing(queue) == "Starts in 0:40"


def test_start_now_is_offered_beside_a_countdown(queue):
    queue.set_items([_item(status="queued", starts_at=time.monotonic() + 42.5)])
    assert not queue._running._start_now.isHidden()


def test_start_now_is_not_offered_where_nothing_counts_down(queue):
    queue.set_items([_item(status="running", started_at=time.time() - 5.5)])
    assert queue._running._start_now.isHidden()
    queue.set_items([_item(key="j2", status="queued")])
    assert queue._running._start_now.isHidden()
    queue.set_items([])
    assert queue._running._start_now.isHidden()


def test_start_now_goes_with_the_countdown_when_it_runs_out_between_polls(queue):
    queue.set_items([_item(status="queued", starts_at=time.monotonic() + 42.5)])
    queue._running._item.starts_at -= 60  # as if the minute had run out
    queue._running._tick.timeout.emit()
    assert queue._running._start_now.isHidden()


def test_pressing_start_now_asks_for_the_waiting_video(queue):
    asked = []
    queue.start_now_requested.connect(lambda: asked.append(True))
    queue.set_items([_item(status="queued", starts_at=time.monotonic() + 42.5)])

    queue._running._start_now.click()

    assert asked == [True]


def test_start_now_sits_under_the_bar_just_right_of_the_countdown(queue):
    # Where the user put it, 2026-10-22.
    queue.set_items([_item(status="queued", starts_at=time.monotonic() + 42.5)],
                    foreign_queued=2)
    QApplication.processEvents()
    bar, caption, start_now = (queue._running._progress, queue._running._caption,
                               queue._running._start_now)

    def place(widget):
        return QRect(widget.mapTo(queue, QPoint(0, 0)), widget.size())

    end_of_the_words = place(caption).left() + caption.fontMetrics().horizontalAdvance(
        caption.text())
    assert place(start_now).top() > place(bar).bottom()
    assert end_of_the_words < place(start_now).left() <= end_of_the_words + 16
    assert caption.height() < 2 * caption.fontMetrics().lineSpacing()  # one line


def test_a_line_too_long_for_the_bar_wraps_at_the_bars_width(queue):
    queue.set_items([_item(status="queued", foreign_ahead=3)])
    queue._running.show_foreign("Waiting on 3 jobs from another app. " * 4)
    QApplication.processEvents()
    bar, caption = queue._running._progress, queue._running._caption

    assert caption.width() <= bar.width()
    assert caption.height() >= 2 * caption.fontMetrics().lineSpacing()


def test_the_users_own_queue_needs_no_explaining(queue):
    # His own jobs are the rows of this very list, so there is nothing left for a
    # wait note to tell him — the line itself is the answer, and neither half
    # says more than it always says.
    queue.set_items([_item(key="a", foreign_ahead=0),
                     _item(key="b", status="queued", foreign_ahead=0)])
    assert [row._note_text for row in queue.rows()] == ["", ""]
    assert _timing(queue) == ""


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
    # The first run of a workflow has no history under it, and one step in it's
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
    queue._running._item.reading.started_at -= 3  # as if three seconds had gone by
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
    return QMouseEvent(kind, QPointF(x, y), QPointF(x, y), Qt.MouseButton.LeftButton,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


def _press_and_drag(row, monkeypatch, *, watch=None):
    """Press the row and travel far enough to start a drag; returns what it carried."""
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


def test_a_press_on_a_row_outlives_a_poll_that_changes_the_line(queue, monkeypatch):
    # A job finishing ahead of it between the press and the drag used to take
    # every row down with it, the pressed one included, so the drag never began.
    carried = []
    monkeypatch.setattr(QDrag, "exec", lambda self, *a: carried.append(
        bytes(self.mimeData().data(QUEUE_ROW_MIME)).decode()))
    queue.resize(800, 200)
    _four(queue)
    QApplication.processEvents()
    pressed_at = queue.rows()[2].rect().center()
    QTest.mousePress(queue.rows()[2], Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, pressed_at)

    queue.set_items([_item(key="b"), _item(key="c", status="queued"),
                     _item(key="d", status="queued")])
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()
    QTest.mouseMove(queue.rows()[1], pressed_at + QPoint(0, 30))
    QTest.mouseRelease(queue, Qt.MouseButton.LeftButton)

    assert carried == ["c"]


def test_a_row_the_line_redraws_away_mid_drag_lets_the_drag_finish(queue, monkeypatch):
    _four(queue)
    row = queue.rows()[2]
    drag_alive = []

    def drag_loop_through_a_redraw(drag, *_):
        queue.set_items([_item(key="a"), _item(key="b", status="queued"),
                         _item(key="d", status="queued")])
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        drag_alive.append(not sip.isdeleted(drag))

    monkeypatch.setattr(QDrag, "exec", drag_loop_through_a_redraw)
    row.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 5, 5))
    row.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, 5, 80))

    assert sip.isdeleted(row)
    assert drag_alive == [True]


def test_a_job_that_holds_its_place_cannot_be_picked_up(queue, monkeypatch):
    # A shielded run being made, or one this window holds no job for: the
    # queue gives its row no move, and the row then has nowhere to go.
    _four(queue)
    assert queue.rows()[0].movable is False
    assert _press_and_drag(queue.rows()[0], monkeypatch) == []


def test_the_job_being_made_can_be_picked_up_where_it_can_move(queue, monkeypatch):
    # Moving it down hands the machine to the job let go ahead of it.
    queue.set_items([_item(key="a", movable=True), _item(key="b", status="queued")])

    assert queue.rows()[0].movable is True
    assert _press_and_drag(queue.rows()[0], monkeypatch) == ["a"]


def test_a_row_takes_up_its_jobs_moves_as_they_change(queue, monkeypatch):
    # A run can come to hold its place, a shield put on it say, without the line
    # changing around it.
    queue.set_items([_item(key="a", movable=True), _item(key="b", status="queued")])

    queue.set_items([_item(key="a"), _item(key="b", status="queued")])

    assert _press_and_drag(queue.rows()[0], monkeypatch) == []


def test_a_press_that_stays_put_is_a_click_not_a_drag(queue, monkeypatch):
    dragged = []
    monkeypatch.setattr(QDrag, "exec", lambda self, *a: dragged.append(True))
    _four(queue)

    row = queue.rows()[1]
    row.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 5, 5))
    row.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, 6, 6))  # a hand's wobble

    assert dragged == []


def test_a_row_that_was_dragged_does_not_also_reveal_its_folder(queue, monkeypatch):
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
    queue.dropEvent(_drag_event(queue, QDropEvent, key, at_row, on_top_half=on_top_half))


def _asked_to_move(queue) -> list:
    asked = []
    queue.move_requested.connect(lambda key, before: asked.append((key, before)))
    return asked


def test_dropping_a_row_above_another_asks_to_move_it_there(queue):
    # The queue moves it and the strip is drawn again from the queue's line: a
    # job that cannot go exactly there lands where the queue's rules put it.
    asked = _asked_to_move(queue)
    _four(queue)

    _drop(queue, "d", at_row=1)  # let the last one go over the first waiting row

    assert asked == [("d", "b")]


def test_dropping_a_row_onto_the_lower_half_puts_it_after(queue):
    # The half of a row a drop lands on is what says above-or-below, so the same
    # gesture a few pixels lower means something different.
    asked = _asked_to_move(queue)
    _four(queue)

    _drop(queue, "b", at_row=2, on_top_half=False)

    assert asked == [("b", "d")]


def test_a_row_let_go_past_the_last_one_asks_for_the_end_of_the_line(queue):
    asked = _asked_to_move(queue)
    _four(queue)

    _drop(queue, "b", at_row=3, on_top_half=False)

    assert asked == [("b", None)]


def test_a_row_let_go_above_the_job_being_made_asks_for_the_top(queue):
    # The job being made is deposed for it, where the queue lets it be.
    asked = _asked_to_move(queue)
    queue.set_items([_item(key="a", movable=True), _item(key="b", status="queued"),
                     _item(key="c", status="queued")])

    _drop(queue, "c", at_row=0)

    assert asked == [("c", "a")]


def test_nothing_can_be_dropped_in_front_of_a_job_that_holds_its_place(queue):
    asked = _asked_to_move(queue)
    _four(queue)

    _drop(queue, "d", at_row=0)  # aimed above the head of the line

    assert asked == [("d", "b")]  # it lands just after it instead


def test_a_drag_over_the_strip_marks_where_it_would_land(queue):
    # The insertion mark is the whole reason a drop is predictable.

    _four(queue)

    queue.dragMoveEvent(_drag_event(queue, QDragMoveEvent, "d", 2))

    assert queue._drop_at == 2


def test_the_mark_is_drawn_over_the_rows_in_the_apps_own_dress(dressed, qtbot):
    # Painted beneath the column the rows sit in, it was never seen at all.
    _four(dressed)
    _settled(dressed)
    row = dressed.rows()[2]
    top = row.mapTo(dressed, row.rect().topLeft())
    mark = [top + QPoint(1, 0), top + QPoint(row.width() - 2, 0)]

    dressed.dragMoveEvent(_drag_event(dressed, QDragMoveEvent, "d", 2))

    qtbot.waitUntil(lambda: _drawn(_on_screen(dressed), mark, BLUE))


def test_what_the_rules_are_drawn_over_still_takes_every_press(queue):
    # A press, a drag and a hover each go to whatever is under the pointer, and
    # the rules lie over the whole strip.
    _four(queue)
    QApplication.processEvents()
    row = queue.rows()[1]
    frame = queue._running._frame

    under = queue.childAt(row.mapTo(queue, row.rect().center()))
    assert under is row or row.isAncestorOf(under)
    assert queue.childAt(frame.mapTo(queue, frame.rect().center())) is frame


def test_the_mark_clears_when_the_drag_leaves(queue):
    _four(queue)
    queue.dragMoveEvent(_drag_event(queue, QDragMoveEvent, "d", 2))

    queue.dragLeaveEvent(QDragLeaveEvent())

    assert queue._drop_at is None


def test_a_row_let_go_where_it_already_was_asks_for_nothing(queue):
    asked = _asked_to_move(queue)
    _four(queue)

    _drop(queue, "c", at_row=2)
    _drop(queue, "c", at_row=3)

    assert asked == []


def test_a_drop_carrying_something_else_is_ignored(queue):
    # Gallery thumbnails are dragged around this app too; one let go over the
    # strip must not be read as a reorder.

    asked = _asked_to_move(queue)
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
    # price comes before the settings — which are the same for every row of a folder
    # being re-rolled and so tells you nothing about the wait.
    queue.set_items([_item(typical_seconds=126.0, job_kind="Video")])
    assert queue.rows()[0]._lead.text() == "~2 min · Video"


def test_a_row_says_when_nobody_typed_its_prompt(queue):
    # The two kinds of job that pile up without being noticed: Auto-Generate
    # makes one every few seconds, and a spoken request never touched a form.
    queue.set_items([_item(typical_seconds=30.0, job_kind="Image",
                           auto_generating=True, requested=True)])
    assert queue.rows()[0]._lead.text() == "~30 sec · Image · Auto · Request"


def test_a_hand_launched_job_says_neither(queue):
    queue.set_items([_item(typical_seconds=30.0, job_kind="Image")])
    assert queue.rows()[0]._lead.text() == "~30 sec · Image"


def test_a_row_names_the_act_it_was_asked_for(queue):
    # The kind says a video is being made; the act says which video —
    # the whole of what the user chose in Combine, and the one thing separating
    # two runs on the same image.
    queue.set_items([_item(typical_seconds=126.0, job_kind="Video",
                           act="dancing")])
    assert queue.rows()[0]._lead.text() == "~2 min · Video · dancing"


def test_a_run_nobody_picked_an_act_for_names_none(queue):
    # A dropped video is the settings' own source: there was no dropdown choice to show,
    # and inventing one from its prompt would be a guess the row states as fact.
    queue.set_items([_item(typical_seconds=126.0, job_kind="Video")])
    assert queue.rows()[0]._lead.text() == "~2 min · Video"


def test_the_hover_spells_out_where_the_act_came_from(queue):
    queue.set_items([_item(typical_seconds=126.0, job_kind="Video",
                           act="dancing")])
    assert "“dancing” act" in queue.rows()[0]._lead.toolTip()


def test_a_workflow_nobody_has_timed_admits_it(queue):
    queue.set_items([_item(typical_seconds=None, job_kind="Image")])
    assert queue.rows()[0]._lead.text() == "~? · Image"


def test_an_unregistered_workflow_leads_with_the_price_alone(queue):
    # An old import this build has no template for: it claims no kind rather than
    # guess one, and the row still says what it will cost.
    queue.set_items([_item(typical_seconds=30.0, job_kind="")])
    assert queue.rows()[0]._lead.text() == "~30 sec"


def test_the_hover_carries_the_name_the_row_no_longer_spends_width_on(queue):
    # The settings are worth an answer, just not the row: every row of a folder
    # being re-rolled carries the same one. A bare "~?" is shorthand a row has the
    # width for and a first reader has no way to expand, so it is spelled out in
    # the same place, beside what the video is made from.
    queue.set_items([_item(caption="Alpha Workflow › a kite", typical_seconds=None,
                           job_kind="Video", requested=True)])
    tip = queue.rows()[0]._lead.toolTip()
    assert tip.startswith("Alpha Workflow › a kite")
    assert "No timing data" in tip
    assert "start image" in tip
    assert "Queued by a request" in tip


# --- the thumbnail a queued job can be recognized by ----------------------------

def test_an_image_to_video_row_shows_the_frame_it_animates(queue, tmp_path):
    # Two i2v rows off one folder's settings carry the same caption; the frame is the whole
    # of what tells them apart.
    frame = _image(tmp_path / "frame.png")
    queue.set_items([_item(job_kind="Video", source_image=frame,
                           folder_thumbnails=(_image(tmp_path / "other.png"),))])
    assert queue.rows()[0]._thumbs._showing == ("source", Combination(frame))


def test_a_row_with_no_frame_shows_what_its_folder_holds(queue, tmp_path):
    # A job whose output doesn't exist yet is placed by the folder it will land
    # in — what the same settings made last time.
    mates = tuple(_image(tmp_path / f"{i}.png") for i in range(3))
    queue.set_items([_item(job_kind="Image", folder_thumbnails=mates)])
    assert queue.rows()[0]._thumbs._showing == ("folder", mates)


def test_a_frame_that_has_not_rendered_yet_falls_back_to_the_folder(queue, tmp_path):
    # A video queued after the image it animates names a start frame that isn't
    # on disk. Better its folder than a blank square where a thumbnail was promised.
    mates = (_image(tmp_path / "mate.png"),)
    queue.set_items([_item(job_kind="Video", source_image=str(tmp_path / "not-yet.png"),
                           folder_thumbnails=mates)])
    assert queue.rows()[0]._thumbs._showing == ("folder", mates)


def test_a_combine_row_shows_the_frame_and_the_source_video_it_follows(queue, tmp_path):
    # Not the source video alone: that reads as a job that IS that clip. The
    # frame being animated leads, and the video whose settings are being reused
    # sits beside it (drawn gray, see queue_thumbs).
    frame = _image(tmp_path / "frame.png")
    video = _image(tmp_path / "source.png", color=(255, 0, 0))
    queue.set_items([_item(job_kind="Video", source_image=frame, source_video_thumbnail=video,
                           folder_thumbnails=(_image(tmp_path / "other.png"),))])
    assert queue.rows()[0]._thumbs._showing == ("source", Combination(frame, video))


def test_a_combine_row_keeps_its_source_video_while_the_frame_is_still_rendering(queue, tmp_path):
    # A chained run draws its frame first, so the video after it names one that
    # isn't on disk yet. The source video is about this run either way — better it than
    # the folder, which says only where the result will land.
    video = _image(tmp_path / "source.png", color=(255, 0, 0))
    queue.set_items([_item(job_kind="Video", source_image=str(tmp_path / "not-yet.png"),
                           source_video_thumbnail=video,
                           folder_thumbnails=(_image(tmp_path / "mate.png"),))])
    assert queue.rows()[0]._thumbs._showing == ("source", Combination(None, video))


def test_a_combine_row_whose_prompt_was_edited_draws_its_source_video_in_parentheses(queue,
                                                                                     tmp_path):
    frame = _image(tmp_path / "frame.png")
    video = _image(tmp_path / "source.png", color=(255, 0, 0))
    queue.set_items([_item(job_kind="I2V", source_image=frame, source_video_thumbnail=video,
                           prompt_edited=True)])
    assert queue.rows()[0]._thumbs._showing == ("source", Combination(frame, video, True))


def test_a_row_that_is_not_a_job_yet_says_so(queue):
    # The press of Generate has an answer on screen before the work that turns it
    # into a job is done — otherwise the button reads as one that did nothing.
    queue.set_items([_item(status="queued", job_kind="Video", act="dancing",
                           cancel=None, starting=True)])
    row = queue.rows()[0]

    assert row._note_text == "Starting…"
    assert row._lead.text() == "~? · Video · dancing"   # what is known of it already
    assert not row._cancel.isEnabled()          # nothing on the server to stop yet
    assert "Not sent to ComfyUI yet" in row._lead.toolTip()


def test_a_started_job_stops_saying_it_is_starting(queue):
    queue.set_items([_item(status="queued", job_kind="Video")])
    assert queue.rows()[0]._note_text == ""


def test_a_wait_note_too_long_for_the_row_is_elided_not_clipped(queue):
    # Clipped, the last word is cut mid-letter and reads as a rendering fault;
    # elided, the row says outright that there is more, and the hover has it.

    queue.set_items([_item(status="queued", starting=True)])
    QApplication.processEvents()
    row = queue.rows()[0]
    room = row._note.fontMetrics().horizontalAdvance("Starting…") // 2

    row.resize(row.width() - row._note.width() + room, row.height())

    assert words(row._note).endswith("…")
    assert words(row._note) != "Starting…"
    assert row._note.toolTip() == "Starting…"


def test_the_thumbnail_sits_at_the_near_edge_of_the_line(queue, tmp_path):
    # Straight after the button rather than out past the text: there the blocks
    # stack into a column at the edge the eye starts from, and a row whose text
    # runs long can never carry one off the far end.

    queue.set_items([_item(job_kind="Image", status="queued", starting=True,
                           folder_thumbnails=(_image(tmp_path / "m.png"),))])
    QApplication.processEvents()
    row = queue.rows()[0]

    assert row._cancel.x() < row._thumbs.x() < row._lead.x() < row._note.x()


def test_a_job_with_nothing_to_show_carries_no_block(queue):
    # The first run of brand-new settings: no frame, and an empty folder. An empty
    # grid would read as a thumbnail that failed to load.
    queue.set_items([_item(job_kind="Image")])
    assert queue.rows()[0]._thumbs.isHidden()


def test_rows_are_the_height_that_shows_about_two_at_a_time(queue):
    _four(queue)
    assert all(row.height() == QueueRow.HEIGHT for row in queue.rows())


def test_cancel_leads_each_row_so_nothing_can_bury_it(queue):
    # A button after a line that can elide was pushed out of sight at the
    # right-hand end, which read as no way to cancel a queued item.

    _four(queue)
    QApplication.processEvents()
    row = queue.rows()[1]
    assert row._cancel.x() < row._lead.x()


def test_the_bar_leaves_the_strip_to_the_queue(queue):
    # It only has to read as a bar; the line beside it carries the long names.

    _four(queue)
    QApplication.processEvents()
    assert queue._scroll.width() + queue._for_all.width() > queue._running.width()
