from __future__ import annotations

import time
from itertools import pairwise

import pytest
from PIL import Image
from PyQt6 import sip
from PyQt6.QtCore import QBuffer, QCoreApplication, QEvent, QMimeData, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QDrag, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QMouseEvent, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from shared_ui.colors import BLUE, BORDER_SUBTLE

from origenerator.gui.combination import Combination
from origenerator.gui.inflight import EMPTY_QUEUE_TEXT, InFlightItem, RunReading
from origenerator.gui.job_queue_view import (
    _ROW_HEIGHT,
    QUEUE_ROW_MIME,
    JobQueueView,
    QueueRow,
)
from origenerator.gui.stylesheet import build_stylesheet
from tests.marked_words import words


@pytest.fixture
def queue(qtbot):
    q = JobQueueView()
    qtbot.addWidget(q)
    q.resize(800, 60)
    q.show()
    return q


ROOM_BESIDE_SHIELD_ALL_AND_CANCEL_ALL = 1100


@pytest.fixture
def dressed(qtbot):
    q = JobQueueView()
    q.setStyleSheet(build_stylesheet())
    qtbot.addWidget(q)
    q.resize(ROOM_BESIDE_SHIELD_ALL_AND_CANCEL_ALL, 60)
    with qtbot.waitExposed(q):
        q.show()
    return q


_EITHER_WAY = object()


def _item(key="j1", caption="Alpha Workflow \u203a a kite", **given):
    status = given.pop("status", "running")
    reading = RunReading(status=status, **{field: given.pop(field)
                                           for field in ("frame", "progress", "started_at",
                                                         "typical_seconds")
                                           if field in given})
    movable = given.pop("movable", None)
    move = (lambda: None) if (status != "running" if movable is None else movable) else None
    move_up = given.pop("move_up", _EITHER_WAY)
    move_down = given.pop("move_down", _EITHER_WAY)
    return InFlightItem(key=key, caption=caption, reading=reading,
                        reveal=given.pop("reveal", None) or (lambda: None),
                        move_up=move if move_up is _EITHER_WAY else move_up,
                        move_down=move if move_down is _EITHER_WAY else move_down,
                        **given)


def _image(path, color=(0, 0, 255)):
    Image.new("RGB", (60, 40), color).save(path)
    return str(path)


def _png_bytes(side=200):
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
    QApplication.processEvents()
    queue.repaint()


def _on_screen(queue):
    return QApplication.primaryScreen().grabWindow(queue.winId()).toImage()


def _drawn(image, points, color) -> bool:
    for start, end in pairwise(points):
        for x in range(min(start.x(), end.x()), max(start.x(), end.x()) + 1):
            for y in range(min(start.y(), end.y()), max(start.y(), end.y()) + 1):
                if image.pixelColor(x, y).name() != color.name():
                    return False
    return True


def test_keeps_its_slot_when_idle(queue):
    queue.set_items([])
    assert queue.isVisible(), (
        "it holds its room with nothing queued, so the panes above it never move on their own")
    assert queue._running.key is None
    assert queue.rows() == []


def test_an_empty_line_says_what_it_is_for(queue):
    queue.set_items([])
    QApplication.processEvents()

    assert queue._hint.isVisible(), (
        "a blank half of a laid-out Job Queue reads as something that failed to draw")
    assert queue._hint.text() == EMPTY_QUEUE_TEXT
    assert queue._hint.objectName() == "estimateLabel", (
        "in the muted style, it reads as a note about the space, not as a row in it")


def test_the_hint_sits_in_the_middle_of_the_whole_strip(queue):
    queue.set_items([])
    QApplication.processEvents()
    center = queue._hint.mapTo(queue, queue._hint.rect().center())

    assert abs(center.x() - queue.width() // 2) <= 4
    assert abs(center.y() - queue.height() // 2) <= 4


def test_the_live_half_stands_down_when_it_has_nothing_in_it(queue):
    queue.set_items([])
    QApplication.processEvents()

    assert not queue._running.isVisible()


def test_the_live_half_keeps_its_place_to_report_another_apps_backlog(queue):
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
    assert queue.keys() == ["a"]


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
    assert len(queue.rows()) == 12


def test_the_clock_is_written_across_the_bar_it_measures(queue):
    queue.set_items([_item(status="running", progress=(10, 20),
                           started_at=time.time() - 90.5, typical_seconds=725.0)])
    QApplication.processEvents()
    preview = queue._running

    assert preview._progress.caption() == "50% · 1:30 elapsed · ~6:02 left"
    assert preview._progress.isTextVisible()
    assert not preview._caption.isVisible()


def test_the_thumbnail_fills_the_strip_from_its_top_edge_into_its_lower_left_corner(queue):
    queue.set_items([_item(status="running")])
    QApplication.processEvents()
    frame = queue._running._frame
    top_left = frame.mapTo(queue, frame.rect().topLeft())

    assert frame.width() == frame.height() == queue.height(), (
        "the Job Queue draws no top border of its own: the splitter handle above it is that border")
    assert (top_left.x(), top_left.y()) == (0, 0)


def test_a_strip_dragged_open_gives_the_room_to_the_line(queue):

    queue.set_items([_item(status="running")])
    queue.resize(800, 400)
    QApplication.processEvents()

    assert queue._running._frame.height() == _ROW_HEIGHT
    assert queue._scroll.height() > _ROW_HEIGHT


def test_the_strip_can_be_dragged_taller_but_not_shorter_than_a_bar(queue):
    assert queue.minimumHeight() == _ROW_HEIGHT
    assert queue.maximumHeight() > _ROW_HEIGHT


def test_the_live_frame_is_drawn_at_the_size_of_that_square(queue):
    queue.set_items([_item(status="running", frame=_png_bytes())])
    QApplication.processEvents()
    frame = queue._running._frame

    assert frame.pixmap().height() == frame.height()


def test_the_corner_stands_the_start_frame_until_a_live_one_arrives(queue, tmp_path):
    frame = _image(tmp_path / "frame.png")
    queue.set_items([_item(job_kind="Video", source_image=frame)])
    QApplication.processEvents()
    corner = queue._running._frame

    assert corner.pixmap() is not None
    assert not corner.pixmap().isNull()
    assert corner.width() == corner.height()


def test_the_corner_stands_the_source_video_beside_the_frame_where_there_is_one(queue, tmp_path):
    frame = _image(tmp_path / "frame.png")
    video = _image(tmp_path / "source.png", color=(255, 0, 0))
    queue.set_items([_item(job_kind="Video", source_image=frame, source_video_thumbnail=video)])
    QApplication.processEvents()
    corner = queue._running._frame

    assert corner.width() > corner.height()


def test_a_live_frame_takes_the_corner_back_from_the_start_frame(queue, tmp_path):
    frame = _image(tmp_path / "frame.png")
    queue.set_items([_item(job_kind="Video", source_image=frame, frame=_png_bytes())])
    QApplication.processEvents()
    corner = queue._running._frame

    assert corner.pixmap().height() == corner.height()
    assert corner.width() == corner.height()


def test_a_run_made_from_nothing_leaves_the_corner_empty(queue):
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
    queue.set_items([_item(status="queued", progress=None)])
    assert queue._running._progress.maximum() == 0


def test_the_whole_queue_is_listed_the_job_being_made_first(queue):
    _four(queue)
    assert queue.keys() == ["a", "b", "c", "d"], (
        "the job being made has a row too, so the rows alone answer what is queued")


def test_the_line_moves_up_when_the_leader_finishes(queue):
    queue.set_items([_item(key="a"), _item(key="b", status="queued")])
    queue.set_items([_item(key="b", status="running")])
    assert queue.keys() == ["b"]
    assert queue._running.key == "b"


def test_a_live_frame_updates_the_rows_without_rebuilding_them(queue):
    queue.set_items([_item(key="a"), _item(key="b", status="queued")])
    row = queue.rows()[1]

    queue.set_items([_item(key="a", typical_seconds=30.0, progress=(3, 10)),
                     _item(key="b", status="queued", typical_seconds=600.0,
                           job_kind="Video")])

    assert queue.rows()[1] is row
    assert row._lead.text() == "~10 min · Video"


def test_a_rule_runs_up_beside_the_live_half_and_along_the_foot_of_its_row(queue):
    _four(queue)
    QApplication.processEvents()
    head = queue.rows()[0]
    foot = head.mapTo(queue, head.rect().bottomRight())

    up, corner, along = queue.head_rule()

    assert queue._running.geometry().right() < up.x() == corner.x() < queue._scroll.x()
    assert up.y() == queue.height() - 1
    assert (corner.y(), along.y(), along.x()) == (foot.y(), foot.y(), foot.x())


def test_the_rule_stands_midway_between_the_bar_and_the_arrows_leading_the_rows(queue):
    queue.set_items([_item(key="a", cancel=lambda: None),
                     _item(key="b", status="queued", cancel=lambda: None)])
    QApplication.processEvents()
    rule = queue.head_rule()[0].x()
    bar_ends = queue._running.geometry().right()
    up = queue.rows()[1]._up
    up_starts = up.mapTo(queue, up.rect().topLeft()).x()

    assert abs((rule - bar_ends) - (up_starts - rule)) <= 1


def test_no_rule_stands_beside_another_apps_backlog_with_nothing_of_ours_in_it(queue):
    queue.set_items([], foreign_queued=2)

    assert queue.head_rule() == []


def test_a_line_scrolled_past_its_head_runs_the_rule_straight_up_the_strip(queue):
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
    _four(dressed)
    _settled(dressed)
    was = dressed.head_rule()[1]

    dressed._scroll.verticalScrollBar().setValue(20)

    qtbot.waitUntil(lambda: _rule_on_screen(dressed))
    where_the_corner_was = QPoint(dressed._scroll.x() - 1, was.y())
    assert _on_screen(dressed).pixelColor(where_the_corner_was).name() != BORDER_SUBTLE.name()


def test_our_first_job_beside_another_apps_backlog_brings_its_rule(dressed, qtbot):
    dressed.set_items([], foreign_queued=2)
    _settled(dressed)

    dressed.set_items([_item(status="queued", foreign_ahead=2)], foreign_queued=2)

    qtbot.waitUntil(lambda: _rule_on_screen(dressed))


def test_the_rule_keeps_to_the_gap_when_the_live_half_widens(dressed, qtbot, tmp_path):
    dressed.set_items([_item(job_kind="Video")])
    _settled(dressed)
    was = dressed.head_rule()[0]

    dressed.set_items([_item(job_kind="Video", source_image=_image(tmp_path / "frame.png"),
                             source_video_thumbnail=_image(tmp_path / "source.png"))])

    qtbot.waitUntil(lambda: dressed.head_rule()[0].x() > was.x() and _rule_on_screen(dressed))
    assert _on_screen(dressed).pixelColor(was).name() != BORDER_SUBTLE.name()


def test_every_row_carries_a_cancel_including_the_one_being_made(queue):
    queue.set_items([_item(key="a", cancel=lambda: None),
                     _item(key="b", status="queued", cancel=lambda: None)])
    assert [row._cancel.text() for row in queue.rows()] == ["Cancel", "Cancel"], (
        "the user's call: every row's button says Cancel")


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
    queue.set_items([_item(key="a", cancel=None)])
    QApplication.processEvents()
    cancel = queue.rows()[0]._cancel
    assert (cancel.isVisible(), cancel.isEnabled()) == (True, False), (
        "the user's answer: grayed out like the arrows, rather than left off")
    assert cancel.cursor().shape() == Qt.CursorShape.ArrowCursor


def test_a_row_from_an_populating_folder_says_cancel_too(queue):
    queue.set_items([_item(key="a", cancel=lambda: None, populating=True),
                     _item(key="b", status="queued", cancel=lambda: None)])
    assert [row._cancel.text() for row in queue.rows()] == ["Cancel", "Cancel"], (
        "the user's call: every row's button says Cancel")
    assert queue.rows()[0]._cancel.toolTip() == "Throw away this seed and start the next"


def test_a_rows_cancel_hover_follows_its_folders_populate_in_place(queue):
    queue.set_items([_item(key="a", cancel=lambda: None, populating=True)])
    row = queue.rows()[0]

    queue.set_items([_item(key="a", cancel=lambda: None)])

    assert queue.rows() == [row]
    assert row._cancel.toolTip() == "Cancel this generation"


def test_every_row_leads_with_an_up_and_a_down_arrow_ahead_of_its_shield(queue):
    queue.set_items([_item(key="a", cancel=lambda: None, shield=lambda _on: None),
                     _item(key="b", status="queued", cancel=lambda: None,
                           shield=lambda _on: None)])
    QApplication.processEvents()

    rows = queue.rows()
    for row in rows:
        up, down, shield = row._up.geometry(), row._down.geometry(), row._shield.geometry()
        assert up.right() < down.left()
        assert down.right() < shield.left()
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
    queue.set_items([_item(key="a", status="queued", move_up=None, move_down=lambda: None)])
    QApplication.processEvents()
    row = queue.rows()[0]

    assert (row._up.isVisible(), row._up.isEnabled()) == (True, False), (
        "grayed and not hidden, so the arrows keep their column down the rows")
    assert row._up.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert row._down.isEnabled()
    assert row._down.cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_a_press_on_a_grayed_arrow_does_nothing_at_all(queue):
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
                           action="an action with a name long enough to run past the Job Queue",
                           cancel=lambda: None, shield=lambda _on: None)])
    QApplication.processEvents()
    row = queue.rows()[0]

    assert row.width() <= queue._scroll.viewport().width()
    assert row._lead.display_text(row._lead.width()).endswith("…")
    assert row._lead.text().endswith("past the Job Queue")


def test_every_rows_shield_sits_just_left_of_its_cancel(queue):
    queue.set_items([_item(key="a", cancel=lambda: None, shield=lambda _on: None),
                     _item(key="b", status="queued", cancel=lambda: None,
                           shield=lambda _on: None, populating=True)])
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
    queue.set_items([_item(key="a")])
    QApplication.processEvents()
    shield = queue.rows()[0]._shield
    assert (shield.isVisible(), shield.isEnabled()) == (True, False), (
        "the user's answer: grayed out like the arrows, rather than left off")
    assert shield.cursor().shape() == Qt.CursorShape.ArrowCursor


def test_pressing_the_shield_does_not_also_open_the_folder(queue, qtbot):
    revealed = []
    queue.set_items([_item(key="a", reveal=lambda: revealed.append(True),
                           cancel=lambda: None, shield=lambda _on: None)])
    QApplication.processEvents()

    qtbot.mouseClick(queue.rows()[0]._shield, Qt.MouseButton.LeftButton)

    assert revealed == []


def _box(queue, widget) -> QRect:
    return QRect(widget.mapTo(queue, QPoint(0, 0)), widget.size())


def test_shield_all_and_cancel_all_stand_stacked_at_the_right_end_of_the_strip(queue):
    queue.set_items([_item(key="a", cancel=lambda: None, shield=lambda _on: None),
                     _item(key="b", status="queued", cancel=lambda: None,
                           shield=lambda _on: None)])
    QApplication.processEvents()

    shield_all, cancel_all = _box(queue, queue._shield_all), _box(queue, queue._cancel_all)
    assert queue._scroll.geometry().right() < shield_all.left() == cancel_all.left(), (
        "the user's pick of four mockups: the fourth")
    assert shield_all.bottom() < cancel_all.top()
    above, below = shield_all.top(), queue.height() - 1 - cancel_all.bottom()
    assert abs(above - below) <= 1


def test_an_empty_job_queue_leaves_shield_all_and_cancel_all_off(queue):
    assert not (queue._shield_all.isVisible()), (
        "the user's answer: off, so the empty Job Queue looks as it always did")
    assert not (queue._cancel_all.isVisible())

    queue.set_items([_item(key="a", cancel=lambda: None, shield=lambda _on: None)])
    assert queue._shield_all.isVisible()
    assert queue._cancel_all.isVisible()

    queue.set_items([])
    assert not (queue._shield_all.isVisible())
    assert not (queue._cancel_all.isVisible())


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
                     _item(key="c", status="queued")])

    queue._shield_all.click()

    assert asked == [("b", True)]
    assert [row._shield.isChecked() for row in queue.rows()] == [True, True, False]


def test_shield_all_is_grayed_out_while_no_job_is_left_for_it_to_shield(queue):
    queue.set_items([_item(key="a", shield=lambda _on: None, shielded=True),
                     _item(key="b", status="queued")])
    assert (queue._shield_all.isVisible(), queue._shield_all.isEnabled()) == (True, False), (
        "the user's answer for a Job Queue whose jobs are all shielded already, which a Job "
        "Queue of jobs that take no shield from here reaches too: either way a press would do "
        "nothing")
    assert queue._shield_all.cursor().shape() == Qt.CursorShape.ArrowCursor

    queue.set_items([_item(key="a", shield=lambda _on: None, shielded=True),
                     _item(key="b", status="queued", shield=lambda _on: None)])
    assert queue._shield_all.isEnabled()
    assert queue._shield_all.cursor().shape() == Qt.CursorShape.PointingHandCursor

    queue._shield_all.click()
    assert not queue._shield_all.isEnabled()


def test_cancel_all_is_grayed_out_while_no_job_in_the_queue_can_be_canceled(queue):
    queue.set_items([_item(key="a"), _item(key="b", status="queued")])
    assert (queue._cancel_all.isVisible(), queue._cancel_all.isEnabled()) == (True, False), (
        "the user's answer, like Shield All's, for a Job Queue of jobs this window has no "
        "Cancel for, as when a restart has not taken them back yet")
    assert queue._cancel_all.cursor().shape() == Qt.CursorShape.ArrowCursor

    queue.set_items([_item(key="a"), _item(key="b", status="queued", cancel=lambda: None)])
    assert queue._cancel_all.isEnabled()
    assert queue._cancel_all.cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_cancel_all_is_asked_of_whoever_holds_the_jobs(queue, qtbot):
    queue.set_items([_item(key="a", cancel=lambda: None)])

    with qtbot.waitSignal(queue.cancel_all_requested, timeout=1000):
        queue._cancel_all.click()


def test_clicking_a_row_reveals_that_jobs_folder(queue, qtbot):
    revealed = []
    queue.set_items([
        _item(key="a", reveal=lambda: revealed.append("a")),
        _item(key="b", status="queued", reveal=lambda: revealed.append("b")),
    ])
    qtbot.mouseClick(queue.rows()[1], Qt.MouseButton.LeftButton)
    assert revealed == ["b"]


def test_double_clicking_a_row_opens_that_folder_too(queue, qtbot):
    revealed = []
    queue.set_items([_item(key="a", status="queued",
                           reveal=lambda: revealed.append("a"))])
    qtbot.mouseDClick(queue.rows()[0], Qt.MouseButton.LeftButton)
    assert revealed
    assert set(revealed) == {"a"}


def test_the_live_frame_opens_the_running_jobs_folder_too(queue, qtbot):
    revealed = []
    queue.set_items([_item(key="a", reveal=lambda: revealed.append("a"))])
    QApplication.processEvents()

    frame = queue._running._frame
    qtbot.mouseClick(frame, Qt.MouseButton.LeftButton)
    qtbot.mouseDClick(frame, Qt.MouseButton.LeftButton)
    assert revealed
    assert set(revealed) == {"a"}


def test_the_bar_beside_the_live_frame_is_not_a_way_into_a_folder(queue, qtbot):
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


def test_the_left_half_says_what_the_bar_is_sweeping_behind(queue):
    queue.set_items([_item(status="queued", foreign_ahead=3)])
    assert _timing(queue) == "Waiting on 3 jobs from another app", (
        "a bar sweeping with nothing said about it is exactly the thing a user is owed an "
        "explanation for")


def test_one_job_ahead_reads_in_the_singular(queue):
    queue.set_items([_item(status="queued", foreign_ahead=1)])
    assert _timing(queue) == "Waiting on 1 job from another app"


def test_the_row_does_not_repeat_the_wait(queue):
    queue.set_items([_item(status="queued", foreign_ahead=3)])
    assert queue.rows()[0]._note_text == ""


def test_the_wait_is_written_under_the_bar_it_explains(queue):
    queue.set_items([_item(status="queued", foreign_ahead=3)])
    QApplication.processEvents()
    half = queue._running

    assert half._progress.isVisible()
    assert half._progress.maximum() == 0
    assert half._caption.isVisible()
    assert half._caption.mapTo(half, QPoint(0, 0)).y() > half._progress.y()


def test_a_job_of_ours_being_made_keeps_the_slot_for_its_bar(queue):
    queue.set_items([_item(status="running", started_at=time.time() - 5.5)])
    assert not queue._running._caption.isVisible()


def test_a_video_waiting_out_the_minute_after_an_image_counts_down_under_the_bar(queue):
    queue.set_items([_item(status="queued", starts_at=time.monotonic() + 42.5)])
    assert _timing(queue) == "Starts in 0:43"


def test_the_countdown_advances_between_polls(queue):
    queue.set_items([_item(status="queued", starts_at=time.monotonic() + 42.5)])
    queue._running._item.starts_at -= 3
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
    queue._running._item.starts_at -= 60
    queue._running._tick.timeout.emit()
    assert queue._running._start_now.isHidden()


def test_pressing_start_now_asks_for_the_waiting_video(queue):
    asked = []
    queue.start_now_requested.connect(lambda: asked.append(True))
    queue.set_items([_item(status="queued", starts_at=time.monotonic() + 42.5)])

    queue._running._start_now.click()

    assert asked == [True]


def test_start_now_sits_under_the_bar_just_right_of_the_countdown(queue):
    queue.set_items([_item(status="queued", starts_at=time.monotonic() + 42.5)],
                    foreign_queued=2)
    QApplication.processEvents()
    bar, caption, start_now = (queue._running._progress, queue._running._caption,
                               queue._running._start_now)

    def place(widget):
        return QRect(widget.mapTo(queue, QPoint(0, 0)), widget.size())

    end_of_the_words = place(caption).left() + caption.fontMetrics().horizontalAdvance(
        caption.text())
    assert place(start_now).top() > place(bar).bottom(), (
        "where the user put it")
    assert end_of_the_words < place(start_now).left() <= end_of_the_words + 16
    assert caption.height() < 2 * caption.fontMetrics().lineSpacing()


def test_a_line_too_long_for_the_bar_wraps_at_the_bars_width(queue):
    queue.set_items([_item(status="queued", foreign_ahead=3)])
    queue._running.show_foreign("Waiting on 3 jobs from another app. " * 4)
    QApplication.processEvents()
    bar, caption = queue._running._progress, queue._running._caption

    assert caption.width() <= bar.width()
    assert caption.height() >= 2 * caption.fontMetrics().lineSpacing()


def test_the_users_own_queue_needs_no_explaining(queue):
    queue.set_items([_item(key="a", foreign_ahead=0),
                     _item(key="b", status="queued", foreign_ahead=0)])
    assert [row._note_text for row in queue.rows()] == ["", ""]
    assert _timing(queue) == ""
    assert queue._clear.isHidden(), (
        "Clear is only ever offered for another app's work: the user's own queue is what the "
        "user asked for, and every row of it carries its own Cancel already")


def _timing(queue) -> str:
    return queue._running.status_text()


def test_shows_how_far_along_it_is_the_elapsed_time_and_what_is_left(queue):
    queue.set_items([_item(status="running", progress=(10, 20),
                           started_at=time.time() - 90.5, typical_seconds=725.0)])
    assert _timing(queue) == "50% · 1:30 elapsed · ~6:02 left"


def test_shows_the_elapsed_time_alone_with_no_estimate(queue):
    queue.set_items([_item(status="running", progress=(1, 20),
                           started_at=time.time() - 45.5)])
    assert _timing(queue) == "5% · 0:45 elapsed"


def test_no_clock_on_a_job_comfyui_has_not_started(queue):
    queue.set_items([_item(status="queued", started_at=None, typical_seconds=724.0)])
    assert _timing(queue) == ""


def test_the_clock_advances_between_polls(queue):
    queue.set_items([_item(status="running", started_at=time.time() - 5.5)])
    assert _timing(queue) == "0:05 elapsed"
    queue._running._item.reading.started_at -= 3
    queue._running._tick.timeout.emit()
    assert _timing(queue) == "0:08 elapsed"


def test_the_clock_stops_when_the_queue_empties(queue):
    queue.set_items([_item(status="running", started_at=time.time() - 5.5)])
    assert queue._running._tick.isActive()

    queue.set_items([])

    assert not queue._running._tick.isActive()
    assert _timing(queue) == ""


def test_another_apps_backlog_takes_the_slot_back_when_ours_empties(queue):
    queue.set_items([_item(status="running", started_at=time.time() - 5.5)])
    assert "elapsed" in _timing(queue)

    queue.set_items([], foreign_queued=2)

    assert _timing(queue) == "2 jobs from another app are queued on ComfyUI"


def test_the_clock_keeps_the_strip_the_same_height(queue):
    queue.set_items([])
    idle = queue.sizeHint().height()
    queue.set_items([_item(status="running", progress=(10, 20),
                           started_at=time.time() - 90.5, typical_seconds=725.0)])
    assert queue.sizeHint().height() == idle


def _mouse(kind, x, y):
    return QMouseEvent(kind, QPointF(x, y), QPointF(x, y), Qt.MouseButton.LeftButton,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


def _press_and_drag(row, monkeypatch, *, watch=None):
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
    _four(queue)
    assert _press_and_drag(queue.rows()[2], monkeypatch) == ["c"]


def test_the_dragged_row_lights_up_while_it_is_being_dragged(queue, monkeypatch):
    _four(queue)
    row = queue.rows()[2]
    lit = []

    _press_and_drag(row, monkeypatch, watch=lit)

    assert lit == [True], (
        "lit while it moves, the drag reads as something the Job Queue offers, not an accident")
    assert row.property("dragging") is False


def test_a_press_on_a_row_outlives_a_poll_that_changes_the_line(queue, monkeypatch):
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
    _four(queue)
    assert queue.rows()[0].movable is False
    assert _press_and_drag(queue.rows()[0], monkeypatch) == []


def test_the_job_being_made_can_be_picked_up_where_it_can_move(queue, monkeypatch):
    queue.set_items([_item(key="a", movable=True), _item(key="b", status="queued")])

    assert queue.rows()[0].movable is True
    assert _press_and_drag(queue.rows()[0], monkeypatch) == ["a"]


def test_a_row_takes_up_its_jobs_moves_as_they_change(queue, monkeypatch):
    queue.set_items([_item(key="a", movable=True), _item(key="b", status="queued")])

    queue.set_items([_item(key="a"), _item(key="b", status="queued")])

    assert _press_and_drag(queue.rows()[0], monkeypatch) == []


def test_a_press_that_stays_put_is_a_click_not_a_drag(queue, monkeypatch):
    dragged = []
    monkeypatch.setattr(QDrag, "exec", lambda self, *a: dragged.append(True))
    _four(queue)

    row = queue.rows()[1]
    row.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 5, 5))
    row.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, 6, 6))

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
    QApplication.processEvents()
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
    queue.dropEvent(_drag_event(queue, QDropEvent, key, at_row, on_top_half=on_top_half))


def _asked_to_move(queue) -> list:
    asked = []
    queue.move_requested.connect(lambda key, before: asked.append((key, before)))
    return asked


def test_dropping_a_row_above_another_asks_to_move_it_there(queue):
    asked = _asked_to_move(queue)
    _four(queue)

    _drop(queue, "d", at_row=1)

    assert asked == [("d", "b")]


def test_dropping_a_row_onto_the_lower_half_puts_it_after(queue):
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
    asked = _asked_to_move(queue)
    queue.set_items([_item(key="a", movable=True), _item(key="b", status="queued"),
                     _item(key="c", status="queued")])

    _drop(queue, "c", at_row=0)

    assert asked == [("c", "a")]


def test_nothing_can_be_dropped_in_front_of_a_job_that_holds_its_place(queue):
    asked = _asked_to_move(queue)
    _four(queue)

    _drop(queue, "d", at_row=0)

    assert asked == [("d", "b")]


def test_a_drag_over_the_strip_marks_where_it_would_land(queue):
    _four(queue)

    queue.dragMoveEvent(_drag_event(queue, QDragMoveEvent, "d", 2))

    assert queue._drop_at == 2


def test_the_mark_is_drawn_over_the_rows_in_the_apps_own_dress(dressed, qtbot):
    _four(dressed)
    _settled(dressed)
    row = dressed.rows()[2]
    top = row.mapTo(dressed, row.rect().topLeft())
    mark = [top + QPoint(1, 0), top + QPoint(row.width() - 2, 0)]

    dressed.dragMoveEvent(_drag_event(dressed, QDragMoveEvent, "d", 2))

    qtbot.waitUntil(lambda: _drawn(_on_screen(dressed), mark, BLUE))


def test_what_the_rules_are_drawn_over_still_takes_every_press(queue):
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


def test_a_row_leads_with_what_the_job_costs_and_what_it_is(queue):
    queue.set_items([_item(typical_seconds=126.0, job_kind="Video")])
    assert queue.rows()[0]._lead.text() == "~2 min · Video"


def test_a_row_says_when_nobody_typed_its_prompt(queue):
    queue.set_items([_item(typical_seconds=30.0, job_kind="Image",
                           populating=True, requested=True)])
    assert queue.rows()[0]._lead.text() == "~30 sec · Image · Populate · Request", (
        "the two kinds of job that pile up unnoticed: Populate makes one every few seconds, and a "
        "spoken request never touched a form")


def test_a_hand_launched_job_says_neither(queue):
    queue.set_items([_item(typical_seconds=30.0, job_kind="Image")])
    assert queue.rows()[0]._lead.text() == "~30 sec · Image"


def test_a_row_names_the_action_it_was_asked_for(queue):
    queue.set_items([_item(typical_seconds=126.0, job_kind="Video",
                           action="dancing")])
    assert queue.rows()[0]._lead.text() == "~2 min · Video · dancing", (
        "the kind says a video is being made; the action says which, and is the one thing "
        "separating two runs on the same image")


def test_a_run_nobody_picked_an_action_for_names_none(queue):
    queue.set_items([_item(typical_seconds=126.0, job_kind="Video")])
    assert queue.rows()[0]._lead.text() == "~2 min · Video"


def test_the_hover_spells_out_where_the_action_came_from(queue):
    queue.set_items([_item(typical_seconds=126.0, job_kind="Video",
                           action="dancing")])
    assert "“dancing” action" in queue.rows()[0]._lead.toolTip()


def test_a_workflow_nobody_has_timed_admits_it(queue):
    queue.set_items([_item(typical_seconds=None, job_kind="Image")])
    assert queue.rows()[0]._lead.text() == "~? · Image"


def test_an_unregistered_workflow_leads_with_the_price_alone(queue):
    queue.set_items([_item(typical_seconds=30.0, job_kind="")])
    assert queue.rows()[0]._lead.text() == "~30 sec"


def test_the_hover_carries_the_name_the_row_no_longer_spends_width_on(queue):
    queue.set_items([_item(caption="Alpha Workflow \u203a a kite", typical_seconds=None,
                           job_kind="Video", requested=True)])
    tip = queue.rows()[0]._lead.toolTip()
    assert tip.startswith("Alpha Workflow \u203a a kite")
    assert "No timing data" in tip
    assert "start image" in tip
    assert "Queued by a request" in tip


def test_an_image_to_video_row_shows_the_frame_it_animates(queue, tmp_path):
    frame = _image(tmp_path / "frame.png")
    queue.set_items([_item(job_kind="Video", source_image=frame,
                           folder_thumbnails=(_image(tmp_path / "other.png"),))])
    assert queue.rows()[0]._thumbs._showing == ("source", Combination(frame)), (
        "the start frame wins whenever there is one: it is about this run rather than about "
        "where it will land, and it is all that separates two rows off one folder's settings")


def test_a_row_with_no_frame_shows_what_its_folder_holds(queue, tmp_path):
    mates = tuple(_image(tmp_path / f"{i}.png") for i in range(3))
    queue.set_items([_item(job_kind="Image", folder_thumbnails=mates)])
    assert queue.rows()[0]._thumbs._showing == ("folder", mates)


def test_a_frame_that_has_not_rendered_yet_falls_back_to_the_folder(queue, tmp_path):
    mates = (_image(tmp_path / "mate.png"),)
    queue.set_items([_item(job_kind="Video", source_image=str(tmp_path / "not-yet.png"),
                           folder_thumbnails=mates)])
    assert queue.rows()[0]._thumbs._showing == ("folder", mates), (
        "a video queued behind the image it animates has no frame on disk yet, "
        "and its folder's thumbnails say more than a blank square")


def test_a_combine_row_shows_the_frame_and_the_source_video_it_follows(queue, tmp_path):
    frame = _image(tmp_path / "frame.png")
    video = _image(tmp_path / "source.png", color=(255, 0, 0))
    queue.set_items([_item(job_kind="Video", source_image=frame, source_video_thumbnail=video,
                           folder_thumbnails=(_image(tmp_path / "other.png"),))])
    assert queue.rows()[0]._thumbs._showing == ("source", Combination(frame, video))


def test_a_combine_row_keeps_its_source_video_while_the_frame_is_still_rendering(queue, tmp_path):
    video = _image(tmp_path / "source.png", color=(255, 0, 0))
    queue.set_items([_item(job_kind="Video", source_image=str(tmp_path / "not-yet.png"),
                           source_video_thumbnail=video,
                           folder_thumbnails=(_image(tmp_path / "mate.png"),))])
    assert queue.rows()[0]._thumbs._showing == ("source", Combination(None, video)), (
        "the source video is about this run; the folder says only where it will land")


def test_a_combine_row_whose_prompt_was_edited_draws_its_source_video_in_parentheses(queue,
                                                                                     tmp_path):
    frame = _image(tmp_path / "frame.png")
    video = _image(tmp_path / "source.png", color=(255, 0, 0))
    queue.set_items([_item(job_kind="I2V", source_image=frame, source_video_thumbnail=video,
                           prompt_edited=True)])
    assert queue.rows()[0]._thumbs._showing == ("source", Combination(frame, video, True))


def test_a_row_that_is_not_a_job_yet_says_so(queue):
    queue.set_items([_item(status="queued", job_kind="Video", action="dancing",
                           cancel=None, starting=True)])
    assert len(queue.rows()) == 1, (
        "the row is there as soon as Generate is pressed, so the button never seems to have done nothing")
    row = queue.rows()[0]

    assert row._note_text == "Starting…"
    assert row._lead.text() == "~? · Video · dancing"
    assert not row._cancel.isEnabled()
    assert "Not sent to ComfyUI yet" in row._lead.toolTip()


def test_a_started_job_stops_saying_it_is_starting(queue):
    queue.set_items([_item(status="queued", job_kind="Video")])
    assert queue.rows()[0]._note_text == ""


def test_a_wait_note_too_long_for_the_row_is_elided_not_clipped(queue):
    queue.set_items([_item(status="queued", starting=True)])
    QApplication.processEvents()
    row = queue.rows()[0]
    room = row._note.fontMetrics().horizontalAdvance("Starting…") // 2

    row.resize(row.width() - row._note.width() + room, row.height())

    assert words(row._note).endswith("…")
    assert words(row._note) != "Starting…", (
        "the note asks for no width of its own: holding out for its full text, it would widen the row "
        "past the Job Queue and carry what follows off its end")
    assert row._note.toolTip() == "Starting…"


def test_the_thumbnail_sits_at_the_near_edge_of_the_line(queue, tmp_path):
    queue.set_items([_item(job_kind="Image", status="queued", starting=True,
                           folder_thumbnails=(_image(tmp_path / "m.png"),))])
    QApplication.processEvents()
    row = queue.rows()[0]

    assert row._cancel.x() < row._thumbs.x() < row._lead.x() < row._note.x()


def test_a_job_with_nothing_to_show_carries_no_block(queue):
    queue.set_items([_item(job_kind="Image")])
    assert queue.rows()[0]._thumbs.isHidden(), (
        "a folder with nothing in it yet leaves the block off the row rather than draw an empty "
        "grid")


def test_rows_are_the_height_that_shows_about_two_at_a_time(queue):
    _four(queue)
    assert all(row.height() == QueueRow.HEIGHT for row in queue.rows())


def test_cancel_leads_each_row_so_nothing_can_bury_it(queue):
    _four(queue)
    QApplication.processEvents()
    row = queue.rows()[1]
    assert row._cancel.x() < row._lead.x()


def test_the_bar_leaves_the_strip_to_the_queue(queue):
    _four(queue)
    QApplication.processEvents()
    assert queue._scroll.width() + queue._for_all.width() > queue._running.width()


def test_the_hand_is_on_the_frame_alone(queue):
    queue.set_items([_item(key="a", reveal=lambda: None)])
    QApplication.processEvents()

    assert queue._running._frame.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert queue._running.cursor().shape() != Qt.CursorShape.PointingHandCursor, (
        "the hand rides on the frame, the one thing in this half that opens anything")


def test_an_empty_half_keeps_the_line_under_its_bar_up(queue):
    queue.set_items([])

    queue._running.show_foreign("")

    assert not queue._running._under_the_bar.isHidden(), (
        "with no job of ours shown, the line holds the space its bar has stood down from")
