"""The generation queue as a block of the one panel a slideshow wears."""
from __future__ import annotations

import time

import numpy as np
from PIL import Image
from shared_ui.palette import RED

from origenerator.gui.hud_queue import (
    CANCEL,
    CLEAR,
    FRAME,
    OPEN,
    SHIELD,
    START_NOW,
    QueuePointer,
    queue_section,
)
from origenerator.gui.inflight import InFlightItem, RunReading


def _item(key="j1", caption="Alpha Workflow › a paper kite", status="queued", **kw):
    reading = {name: kw.pop(name) for name in list(kw)
               if name in ("frame", "progress", "pass_progress", "stage",
                           "started_at", "typical_seconds")}
    # The job being made holds its place unless a test says it can be moved.
    move = (lambda: None) if kw.pop("movable", status != "running") else None
    kw.setdefault("move_up", move)
    kw.setdefault("move_down", move)
    return InFlightItem(key=key, caption=caption,
                        reading=RunReading(status=status, **reading),
                        reveal=kw.pop("reveal", lambda: None), **kw)


def test_nothing_in_flight_is_no_block_at_all():
    """A slideshow with an idle queue wears the panel it always wore."""
    assert queue_section([], 0) is None


def test_every_job_in_flight_is_a_row_of_its_own():
    section = queue_section([_item("running-one", status="running", job_kind="Image",
                                   typical_seconds=30),
                             _item("waiting-one", job_kind="Video", typical_seconds=600)], 0)

    assert [line.key for line in section.lines] == ["running-one", "waiting-one"]
    assert section.lines[1].lead == "~10 min · Video"


def test_the_job_being_made_leads_the_block_with_its_frame_and_its_clock():
    """The live half of the lower strip, on the panel: what is being made, and
    how far along it is."""
    section = queue_section([_item("running-one", status="running", frame=b"jpeg",
                                   started_at=0.0, typical_seconds=30,
                                   progress=(5, 20))], 0)

    assert section.leader.key == "running-one"
    assert section.leader.frame == b"jpeg"
    assert section.leader.progress == (5, 20)
    assert "%" in section.leader.caption


def test_a_video_waiting_at_the_head_of_the_line_leads_the_block():
    section = queue_section([_item("waiting-one", job_kind="Video")], 0)

    assert section.leader.key == "waiting-one"
    assert section.idle_note == ""


def test_a_video_waiting_out_the_minute_after_an_image_says_when_it_starts():
    # The half-second keeps the count a clear half-second off a rollover.
    section = queue_section([_item("waiting-one", job_kind="Video",
                                   starts_at=time.monotonic() + 42.5)], 0)

    assert section.leader.wait == "Starts in 0:43"


def test_with_nothing_of_ours_in_flight_the_block_names_another_apps_backlog():
    section = queue_section([], 3)

    assert section.leader is None
    assert section.idle_note == "3 jobs from another app are queued on ComfyUI"


def _painted(section, width=400):
    """The block on a panel-sized canvas, with what it drew there."""
    image = Image.new("RGBA", (width + 20, section.size()[1] + 20), (0, 0, 0, 0))
    return image, section.paint(image, 10, 10, width, None)


def _posted(targets) -> list[str]:
    return [button.command for _rect, button in targets]


def test_a_video_waiting_out_the_minute_offers_start_now_beside_its_countdown():
    section = queue_section([_item("waiting-one", job_kind="Video",
                                   starts_at=time.monotonic() + 42.5)], 0)

    _image, targets = _painted(section)

    assert [button.glyph for _rect, button in targets
            if button.command == START_NOW] == ["Start now"]


def test_start_now_is_offered_only_while_a_countdown_runs():
    for leader in (_item("running-one", status="running", started_at=0.0, typical_seconds=30),
                   _item("waiting-one", job_kind="Video"),
                   _item("due-one", job_kind="Video", starts_at=time.monotonic() - 1)):
        _image, targets = _painted(queue_section([leader], 0))
        assert START_NOW not in _posted(targets)


def test_a_row_carries_the_button_that_throws_its_job_away():
    section = queue_section([_item("j1", cancel=lambda: None),
                             _item("j2", cancel=lambda: None, auto_generating=True)], 0)

    _image, targets = _painted(section)

    assert "queue_cancel|j1" in _posted(targets)
    assert [button.glyph for _rect, button in targets
            if button.command == "queue_cancel|j2"] == ["Next seed"]


def test_a_row_leads_with_a_shield_just_left_of_its_cancel_lit_while_shielded():
    section = queue_section([_item("j1", cancel=lambda: None, shield=lambda _on: None,
                                   shielded=True),
                             _item("j2", cancel=lambda: None, shield=lambda _on: None)], 0)

    _image, targets = _painted(section)

    drawn = {button.command: (rect, button) for rect, button in targets}
    (shield_x, _y, shield_width, _h), shield = drawn[f"{SHIELD}|j1"]
    (cancel_x, *_rest), _cancel = drawn[f"{CANCEL}|j1"]
    assert shield_x + shield_width <= cancel_x
    assert shield.lit
    assert not drawn[f"{SHIELD}|j2"][1].lit


def test_a_row_is_a_way_into_the_folder_its_job_will_land_in():
    section = queue_section([_item("j1")], 0)

    _image, targets = _painted(section)

    assert "queue_open|j1" in _posted(targets)


def _reds(image) -> int:
    """How many pixels of the block are within a hair of the panel's red."""
    pixels = np.asarray(image).reshape(-1, 4).astype(int)
    near = np.all(np.abs(pixels[:, :3] - np.array(RED[:3])) < 24, axis=1)
    return int(np.count_nonzero(near & (pixels[:, 3] > 0)))


def test_the_word_that_throws_a_job_away_is_drawn_in_the_panels_own_ink():
    """The strip under the window draws Cancel in the panel's ordinary gray,
    and the panel's own copy of that queue reads the same: red here is the
    color the Funestras keep for a live recording."""
    section = queue_section([_item("j1", cancel=lambda: None)], 0)

    image, _targets = _painted(section)

    assert _reds(image) == 0


class _Host:
    """What the pointer asks of the slideshow: the line, a re-line, and the Clear."""

    def __init__(self, items, foreign=0):
        self.hud_queue = (items, foreign)
        self.moved = []
        self.cleared = 0
        self.started_now = 0

    def move(self, key, before):
        self.moved.append((key, before))

    def clear_foreign_queue(self):
        self.cleared += 1

    def start_now(self):
        self.started_now += 1


def _pointer_over(items, foreign=0):
    host = _Host(items, foreign)
    pointer = QueuePointer(host)
    _painted(queue_section(items, foreign, first=pointer.first, drop_at=pointer.drop,
                           pointer=pointer))
    return pointer, host


def _middle_of(pointer, command):
    x, y, width, height = pointer.where(command)
    return x + width // 2, y + height // 2


def _lower_half_of(pointer, command):
    x, y, width, height = pointer.where(command)
    return x + width // 2, y + height - 2


class TestThePointerOnTheBlock:
    """The source painted the block and knows what is drawn where, so the
    panel hands it the pointer in the block's own pixels: a press, a drag,
    the button coming up and the wheel."""

    def test_a_press_on_a_rows_button_throws_that_job_away(self):
        stopped = []
        pointer, _host = _pointer_over([_item("j1", cancel=lambda: stopped.append("j1"),
                                              typical_seconds=30)])

        pointer.press(*_middle_of(pointer, f"{CANCEL}|j1"))

        assert stopped == ["j1"]

    def test_a_press_on_a_rows_shield_puts_it_on_and_lights_it_at_once(self):
        asked = []
        pointer, host = _pointer_over([_item("j1", cancel=lambda: None,
                                             shield=asked.append, typical_seconds=30)])

        pointer.press(*_middle_of(pointer, f"{SHIELD}|j1"))

        assert asked == [True]
        assert queue_section(*host.hud_queue).lines[0].shielded

    def test_a_press_on_a_row_goes_to_the_folder_its_job_will_land_in(self):
        opened = []
        pointer, _host = _pointer_over([_item("j1", reveal=lambda: opened.append("j1"),
                                              typical_seconds=30)])
        at = _middle_of(pointer, f"{OPEN}|j1")

        pointer.press(*at)
        pointer.release(*at)

        assert opened == ["j1"]

    def test_clear_drops_another_apps_work(self):
        pointer, host = _pointer_over([], 3)

        pointer.press(*_middle_of(pointer, CLEAR))

        assert host.cleared == 1

    def test_start_now_starts_the_video_waiting_out_the_minute(self):
        pointer, host = _pointer_over([_item("v1", job_kind="Video",
                                             starts_at=time.monotonic() + 42.5)])

        pointer.press(*_middle_of(pointer, START_NOW))

        assert host.started_now == 1

    def test_start_now_sits_under_the_bar_and_clear_keeps_the_bars_row(self):
        # Where the user put it in the job queue, 2026-10-22: under the bar,
        # just right of the countdown.
        pointer, _host = _pointer_over([_item("v1", job_kind="Video",
                                              starts_at=time.monotonic() + 42.5)], 3)
        frame_x, _y, frame_width, _h = pointer.where(f"{FRAME}|v1")
        start_x, start_y, _w, _h = pointer.where(START_NOW)
        _x, clear_y, _w, _h = pointer.where(CLEAR)

        assert start_x > frame_x + frame_width
        assert start_y > clear_y

    def test_a_row_dragged_down_the_line_re_lines_the_queue(self):
        pointer, host = _pointer_over([_item("j1", status="running", typical_seconds=30),
                                       _item("j2", typical_seconds=30),
                                       _item("j3", typical_seconds=30)])

        pointer.press(*_middle_of(pointer, f"{OPEN}|j2"))
        pointer.drag(*_lower_half_of(pointer, f"{OPEN}|j3"))
        assert pointer.drop == 3
        pointer.release(*_lower_half_of(pointer, f"{OPEN}|j3"))

        assert host.moved == [("j2", None)]
        assert pointer.drop is None

    def test_a_row_let_go_above_the_job_being_made_asks_for_the_top(self):
        pointer, host = _pointer_over([_item("j1", status="running", movable=True,
                                             typical_seconds=30),
                                       _item("j2", typical_seconds=30),
                                       _item("j3", typical_seconds=30)])

        pointer.press(*_middle_of(pointer, f"{OPEN}|j3"))
        x, y, _width, _height = pointer.where(f"{OPEN}|j1")
        pointer.drag(x + 5, y + 2)
        pointer.release(x + 5, y + 2)

        assert host.moved == [("j3", "j1")]

    def test_a_row_that_was_dragged_does_not_also_open_its_folder(self):
        opened = []
        pointer, _host = _pointer_over([_item("j1", typical_seconds=30),
                                        _item("j2", reveal=lambda: opened.append("j2"),
                                              typical_seconds=30)])
        x, y = _middle_of(pointer, f"{OPEN}|j2")

        pointer.press(x, y)
        pointer.drag(x, y - 20)
        pointer.release(x, y - 20)

        assert opened == []

    def test_a_job_that_holds_its_place_cannot_be_picked_up(self):
        """A shielded run being made, or one this window holds no job for, has
        no move, so its row has nowhere to go."""
        pointer, host = _pointer_over([_item("j1", status="running", typical_seconds=30),
                                       _item("j2", typical_seconds=30)])
        x, y = _middle_of(pointer, f"{OPEN}|j1")

        pointer.press(x, y)
        pointer.drag(x, y + 40)
        pointer.release(x, y + 40)

        assert host.moved == []

    def test_nothing_can_be_let_go_in_front_of_a_job_that_holds_its_place(self):
        pointer, host = _pointer_over([_item("j1", status="running", typical_seconds=30),
                                       _item("j2", typical_seconds=30),
                                       _item("j3", typical_seconds=30)])

        pointer.press(*_middle_of(pointer, f"{OPEN}|j3"))
        x, y, _width, _height = pointer.where(f"{OPEN}|j1")
        pointer.drag(x + 5, y + 2)
        pointer.release(x + 5, y + 2)

        assert host.moved == [("j3", "j2")]

    def test_the_wheel_scrolls_a_line_longer_than_the_rows_drawn(self):
        pointer, host = _pointer_over([_item(f"j{index}", typical_seconds=30)
                                       for index in range(7)])

        pointer.wheel(-1, *_middle_of(pointer, f"{OPEN}|j2"))

        assert pointer.first == 1
        drawn = queue_section(*host.hud_queue, first=pointer.first).drawn
        assert drawn[0].key == "j1"

    def test_the_wheel_off_the_rows_scrolls_nothing(self):
        pointer, _host = _pointer_over([_item(f"j{index}", typical_seconds=30)
                                        for index in range(7)])

        pointer.wheel(-1, 0, -50)

        assert pointer.first == 0
