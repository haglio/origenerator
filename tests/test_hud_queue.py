"""The Job Queue as a block of the one HUD a slideshow wears."""
from __future__ import annotations

import time

import numpy as np
from funestra.satellite_hud import map_block_width
from PIL import Image
from shared_ui.palette import RED

from origenerator.gui import hud_queue
from origenerator.gui.hud_queue import (
    CANCEL,
    CANCEL_ALL,
    CLEAR,
    DOWN,
    FRAME,
    OPEN,
    SHIELD,
    SHIELD_ALL,
    START_NOW,
    UP,
    QueuePointer,
    QueueSection,
    queue_section,
)
from origenerator.gui.inflight import EMPTY_QUEUE_TEXT, InFlightItem, RunReading


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


def test_an_idle_job_queue_says_what_cores_does_when_nothing_is_queued():
    section = queue_section([], 0)

    assert section.empty_note == EMPTY_QUEUE_TEXT
    assert _inked(_painted(section)[0])


def test_a_job_queue_with_anything_in_it_says_nothing_of_being_empty():
    assert queue_section([_item("waiting-one")], 0).empty_note == ""
    assert queue_section([], 3).empty_note == EMPTY_QUEUE_TEXT


def test_the_job_queue_keeps_one_size_whatever_is_in_flight():
    sizes = {queue_section(items, foreign).size() for items, foreign in (
        ([], 0),
        ([], 3),
        ([_item("running-one", status="running", started_at=0.0, typical_seconds=30)], 0),
        ([_item(f"j{index}", typical_seconds=30) for index in range(7)], 2),
    )}

    assert len(sizes) == 1


def test_the_job_queue_fits_the_width_the_hud_already_has():
    long_line = [_item("j1", caption="Alpha Workflow › " + "a paper kite " * 40,
                       typical_seconds=30)]

    assert queue_section(long_line, 0).size()[0] == 0


def test_a_job_queue_kept_blank_holds_its_room_and_draws_nothing():
    shown = queue_section([_item("j1", typical_seconds=30)], 0)
    blank = QueueSection(blank=True)

    image, targets = _painted(blank)

    assert blank.size() == shown.size()
    assert targets == [] and not _inked(image)


def _inked(image) -> bool:
    return bool(np.asarray(image)[..., 3].any())


def test_every_job_in_flight_is_a_row_of_its_own():
    section = queue_section([_item("running-one", status="running", job_kind="Image",
                                   typical_seconds=30),
                             _item("waiting-one", job_kind="Video", typical_seconds=600)], 0)

    assert [line.key for line in section.lines] == ["running-one", "waiting-one"]
    assert section.lines[1].lead == "~10 min · Video"


def test_the_job_being_made_leads_the_block_with_its_frame_and_its_clock():
    """The live half of Core's Job Queue, on the HUD: what is being made, and
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
    """The block on a HUD-sized canvas, with what it drew there."""
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
    assert [(button.glyph, button.tooltip) for _rect, button in targets
            if button.command == "queue_cancel|j2"] == [
        ("Cancel", "Throw away this seed and start the next")]


def test_a_row_leads_with_an_up_and_a_down_arrow_ahead_of_its_shield():
    # Each grayed where its job cannot go that way: here, up.
    section = queue_section([_item("j1", cancel=lambda: None, shield=lambda _on: None,
                                   move_up=None, move_down=lambda: None)], 0)

    _image, targets = _painted(section)

    drawn = {button.command: (rect, button) for rect, button in targets}
    (up_x, _y, up_width, _h), up = drawn[f"{UP}|j1"]
    (down_x, _y, down_width, _h), down = drawn[f"{DOWN}|j1"]
    (shield_x, *_rest), _shield = drawn[f"{SHIELD}|j1"]
    assert up_x + up_width <= down_x and down_x + down_width <= shield_x
    assert (up.dim, down.dim) == (True, False)


def test_a_rows_shield_sits_just_left_of_its_cancel_lit_while_shielded():
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


def test_a_rows_shield_and_cancel_are_grayed_where_its_job_cannot_take_them():
    # His answer for the Job Queue (2026-10-29), and so here too.
    section = queue_section([_item("j1"), _item("j2", cancel=lambda: None,
                                                shield=lambda _on: None)], 0)

    _image, targets = _painted(section)

    dim = {button.command: button.dim for _rect, button in targets}
    assert (dim[f"{SHIELD}|j1"], dim[f"{CANCEL}|j1"]) == (True, True)
    assert (dim[f"{SHIELD}|j2"], dim[f"{CANCEL}|j2"]) == (False, False)


def test_the_block_stacks_shield_all_over_cancel_all_at_the_right_end_of_its_top_line():
    # Where the user moved them on every slideshow's HUD (2026-10-29): beside the
    # job being made, its bar stopping short of them.
    section = queue_section([_item("j1", status="running", cancel=lambda: None,
                                   shield=lambda _on: None),
                             _item("j2", cancel=lambda: None, shield=lambda _on: None)], 0)

    image, targets = _painted(section)

    drawn = {button.command: (rect, button) for rect, button in targets}
    (_x, frame_y, _w, frame_height), _frame = drawn[f"{FRAME}|j1"]
    (all_x, all_y, all_width, all_height), shield_all = drawn[SHIELD_ALL]
    (cancel_x, cancel_y, cancel_width, cancel_height), cancel_all = drawn[CANCEL_ALL]
    assert all_x == cancel_x and all_width == cancel_width
    assert all_x + all_width == 10 + 400  # flush with the block's right edge
    assert all_y + all_height < cancel_y
    above, below = all_y - frame_y, frame_y + frame_height - (cancel_y + cancel_height)
    assert above >= 0 and below >= 0 and abs(above - below) <= 1
    assert image.getpixel((all_x - 1, frame_y + 1))[3] == 0
    assert (shield_all.glyph, cancel_all.glyph) == ("All", "Cancel All")


def test_a_usual_line_reads_in_full_across_the_portrait_satellites_hud(monkeypatch):
    real_fit_text = hud_queue.fit_text
    fitted = []

    def fit_text(font, text, room):
        fitted.append(real_fit_text(font, text, room))
        return fitted[-1]

    monkeypatch.setattr(hud_queue, "fit_text", fit_text)
    width = map_block_width("portrait")
    section = queue_section([_item("j1", status="running", typical_seconds=30),
                             _item("j2", job_kind="Video", typical_seconds=600,
                                   cancel=lambda: None, shield=lambda _on: None)], 0)

    _image, targets = _painted(section, width)

    rows = [rect for rect, button in targets if button.command.startswith(f"{OPEN}|")]
    assert len(rows) == 2 and all((x, row) == (10, width) for x, _y, row, _h in rows)
    assert section.lines[1].lead in fitted


def test_with_nothing_of_ours_in_flight_shield_all_and_cancel_all_are_left_off():
    # His answer for the Job Queue (2026-10-29), and so here beside another app's backlog.
    _image, targets = _painted(queue_section([], 3))

    assert not {SHIELD_ALL, CANCEL_ALL} & set(_posted(targets))


def _brightest(image, rect) -> int:
    x, y, width, height = rect
    return int(np.asarray(image.crop((x, y, x + width, y + height)))[..., :3].max())


def test_shield_all_is_grayed_out_while_no_job_is_left_for_it_to_shield():
    # His answer for the Job Queue (2026-10-29), and so here too: the HUD's muted
    # ink, never its bright one, on a press that would do nothing.
    shielded = _item("j1", status="running", shield=lambda _on: None, shielded=True)
    grayed = queue_section([shielded, _item("j2")], 0)  # one the slideshow cannot shield
    lit = queue_section([shielded, _item("j2", shield=lambda _on: None)], 0)

    for section, dim in ((grayed, True), (lit, False)):
        image, targets = _painted(section)
        rect, shield_all = next((rect, b) for rect, b in targets if b.command == SHIELD_ALL)
        assert shield_all.dim == dim
        assert (_brightest(image, rect) < 180) == dim


def test_cancel_all_is_grayed_out_while_no_job_can_be_canceled():
    # His answer for the Job Queue (2026-10-29), and so here too.
    grayed = queue_section([_item("j1", status="running"), _item("j2")], 0)
    lit = queue_section([_item("j1", status="running"), _item("j2", cancel=lambda: None)], 0)

    for section, dim in ((grayed, True), (lit, False)):
        image, targets = _painted(section)
        rect, cancel_all = next((rect, b) for rect, b in targets if b.command == CANCEL_ALL)
        assert cancel_all.dim == dim
        assert (_brightest(image, rect) < 180) == dim


def test_a_row_is_a_way_into_the_folder_its_job_will_land_in():
    section = queue_section([_item("j1")], 0)

    _image, targets = _painted(section)

    assert "queue_open|j1" in _posted(targets)


def _reds(image) -> int:
    """How many pixels of the block are within a hair of the HUD's red."""
    pixels = np.asarray(image).reshape(-1, 4).astype(int)
    near = np.all(np.abs(pixels[:, :3] - np.array(RED[:3])) < 24, axis=1)
    return int(np.count_nonzero(near & (pixels[:, 3] > 0)))


def test_the_word_that_throws_a_job_away_is_drawn_in_the_huds_own_ink():
    """Core's Job Queue draws Cancel in the HUD's ordinary gray,
    and the HUD's own copy of that queue reads the same: red here is the
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
        self.cancelled_all = 0

    def move(self, key, before):
        self.moved.append((key, before))

    def clear_foreign_queue(self):
        self.cleared += 1

    def start_now(self):
        self.started_now += 1

    def cancel_all(self):
        self.cancelled_all += 1


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
    HUD hands it the pointer in the block's own pixels: a press, a drag,
    the button coming up and the wheel."""

    def test_a_press_on_a_rows_button_throws_that_job_away(self):
        stopped = []
        pointer, _host = _pointer_over([_item("j1", cancel=lambda: stopped.append("j1"),
                                              typical_seconds=30)])

        pointer.press(*_middle_of(pointer, f"{CANCEL}|j1"))

        assert stopped == ["j1"]

    def test_a_press_on_a_rows_arrows_moves_its_job_that_way(self):
        asked = []
        pointer, _host = _pointer_over([_item("j1", move_up=lambda: asked.append("up"),
                                              move_down=lambda: asked.append("down"))])

        pointer.press(*_middle_of(pointer, f"{UP}|j1"))
        pointer.press(*_middle_of(pointer, f"{DOWN}|j1"))

        assert asked == ["up", "down"]

    def test_a_press_on_a_grayed_arrow_does_nothing_at_all(self):
        # Not even the folder the rest of the row opens.
        opened = []
        pointer, _host = _pointer_over([_item("j1", reveal=lambda: opened.append("j1"),
                                              move_up=None, move_down=lambda: None)])
        at = _middle_of(pointer, f"{UP}|j1")

        pointer.press(*at)
        pointer.release(*at)

        assert opened == []

    def test_shield_all_puts_the_shield_on_every_job_that_has_none(self):
        asked = []
        pointer, host = _pointer_over([
            _item("j1", shield=lambda on: asked.append(("j1", on)), shielded=True),
            _item("j2", shield=lambda on: asked.append(("j2", on)))])

        pointer.press(*_middle_of(pointer, SHIELD_ALL))

        assert asked == [("j2", True)]
        assert all(line.shielded for line in queue_section(*host.hud_queue).lines)

    def test_cancel_all_is_asked_of_the_slideshow_which_asks_first(self):
        pointer, host = _pointer_over([_item("j1", cancel=lambda: None)])

        pointer.press(*_middle_of(pointer, CANCEL_ALL))

        assert host.cancelled_all == 1

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
