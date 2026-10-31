from __future__ import annotations

import io
import time

from PIL import Image
from PyQt6.QtCore import QPoint, Qt

from origenerator.gui.inflight import InFlightItem, RunReading, foreign_queue_text
from origenerator.gui.inflight_tile import InFlightTile
from origenerator.gui.item_type_icon import ItemTypeIcon


def _png_bytes(color=(200, 50, 50)):
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, format="PNG")
    return buf.getvalue()


_READING_KEYS = ("status", "frame", "progress", "pass_progress", "stage", "started_at", "typical_seconds")


def _item(**kw):
    reading = {"status": "queued"} | {k: kw.pop(k) for k in list(kw) if k in _READING_KEYS}
    base = dict(key="p1", caption="SDXL › a cat", reveal=lambda: None)
    base.update(kw)
    return InFlightItem(reading=RunReading(**reading), **base)


def test_tile_says_queued_over_the_frame(qtbot):
    tile = InFlightTile(_item(status="queued"))
    qtbot.addWidget(tile)
    assert tile._scrim.text() == "Queued…"
    assert tile._caption.text() == "SDXL › a cat"


def test_tile_says_the_lines_are_being_spoken_before_the_job_is_sent(qtbot):
    # A story with lines is voiced first, off the GUI thread, and until the
    # voice is done nothing is on the server: the tile says what the wait is.
    tile = InFlightTile(_item(status="speaking"))
    qtbot.addWidget(tile)
    assert tile._scrim.text() == "Speaking her lines…"


def test_tile_says_generating_when_running(qtbot):
    tile = InFlightTile(_item(status="running"))
    qtbot.addWidget(tile)
    assert tile._scrim.text() == "Generating…"


def test_tile_shows_the_live_frame_when_one_is_present(qtbot):
    tile = InFlightTile(_item(status="running", frame=_png_bytes()))
    qtbot.addWidget(tile)
    assert not tile._image.pixmap().isNull()


def test_the_stage_message_reads_over_the_frame_rather_than_replacing_it(qtbot):
    # The live frame is the one thing worth looking at; a placeholder that took
    # its place hid it. The scrim dims it and writes over the top instead.
    tile = InFlightTile(_item(status="running", frame=_png_bytes()))
    qtbot.addWidget(tile)

    assert not tile._image.pixmap().isNull()   # the thumbnail is still there
    assert tile._scrim.text() == "Generating…"  # and the stage is on top of it
    assert tile._scrim.geometry().intersects(tile._image.geometry())


def test_item_type_icon_shows_only_when_the_item_names_a_type(qtbot):
    # An in-flight tile in the Latest collection wears the same image/video badge as a
    # finished tile, so a queued video reads as a video before its first frame.
    plain = InFlightTile(_item())                    # no type known → no badge
    qtbot.addWidget(plain)
    assert plain.findChildren(ItemTypeIcon) == []
    badged = InFlightTile(_item(media_type="video"))
    qtbot.addWidget(badged)
    assert len(badged.findChildren(ItemTypeIcon)) == 1


def test_clicking_the_tile_emits_its_key(qtbot):
    tile = InFlightTile(_item(key="job-7"))
    qtbot.addWidget(tile)
    with qtbot.waitSignal(tile.clicked) as sig:
        qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)
    assert sig.args == ["job-7"]


def test_update_item_refreshes_caption_frame_and_stage_in_place(qtbot):
    tile = InFlightTile(_item(status="queued"))
    qtbot.addWidget(tile)
    assert tile._scrim.text() == "Queued…"

    tile.update_item(_item(caption="new caption", status="running", frame=_png_bytes()))
    assert tile._caption.text() == "new caption"
    assert tile._scrim.text() == "Generating…"
    assert not tile._image.pixmap().isNull()


def test_tile_names_another_apps_hold_instead_of_a_bare_queued(qtbot):
    # "Queued…" alone is the mystery: queued after what? Another app's jobs are
    # the part nothing else in this app can explain.
    tile = InFlightTile(_item(status="queued", foreign_ahead=2))
    qtbot.addWidget(tile)
    assert tile._scrim.text() == "Waiting on 2 jobs from another app"


def test_a_video_waiting_out_the_minute_after_an_image_counts_down_to_its_start(qtbot):
    # The half-second keeps the count a clear half-second off a rollover.
    tile = InFlightTile(_item(status="queued", starts_at=time.monotonic() + 42.5))
    qtbot.addWidget(tile)
    assert tile._scrim.text() == "Starts in 0:43"


def test_the_countdown_advances_between_polls(qtbot):
    tile = InFlightTile(_item(status="queued", starts_at=time.monotonic() + 42.5))
    qtbot.addWidget(tile)

    tile._item.starts_at -= 3  # as if three seconds had gone by
    tile._tick.timeout.emit()
    assert tile._scrim.text() == "Starts in 0:40"
    assert tile._tick.isActive()


def test_a_queue_of_the_users_own_jobs_says_nothing_extra(qtbot):
    # Waiting on his own queue is no mystery — ComfyUI is working through what he
    # asked for — so the tile says what it always said.
    tile = InFlightTile(_item(status="queued", foreign_ahead=0))
    qtbot.addWidget(tile)
    assert tile._scrim.text() == "Queued…"


# --- how far along, and how long it has taken --------------------------------

def test_the_bar_carries_the_percentage_and_the_clock(qtbot):
    # The same line the Job Queue writes for the same job: the tile
    # used to show neither number, so a run being watched here had to be looked
    # up in the Job Queue to find out how far along it was.
    tile = InFlightTile(_item(status="running", progress=(10, 20),
                              started_at=time.time() - 90.5, typical_seconds=725.0))
    qtbot.addWidget(tile)
    assert tile._bar.caption() == "50% · ~6:02 left"
    assert (tile._bar.value(), tile._bar.maximum()) == (10, 20)


def test_a_job_comfyui_has_not_started_leaves_the_bar_blank_and_sweeping(qtbot):
    # Its wait is the queue's to explain, not a zero counting up over a bar that
    # has not moved.
    tile = InFlightTile(_item(status="queued", started_at=None, typical_seconds=724.0))
    qtbot.addWidget(tile)
    assert tile._bar.caption() == ""
    assert tile._bar.maximum() == 0  # indeterminate: sweeping, not stuck at 0%
    assert not tile._tick.isActive()  # and no clock ticking over an unmoving line


def test_the_clock_advances_between_polls(qtbot):
    # The gallery re-feeds the collection every 1.5s, which would make a seconds count
    # skip; the tile re-reads the clock itself so it moves a second at a time.
    tile = InFlightTile(_item(status="running", started_at=time.time() - 5.5,
                              typical_seconds=100.0))
    qtbot.addWidget(tile)
    assert tile._bar.caption() == "~1:34 left"

    tile._item.reading.started_at -= 3  # as if three seconds had gone by
    tile._tick.timeout.emit()
    assert tile._bar.caption() == "~1:31 left"


def test_the_bar_sits_along_the_foot_of_the_frame(qtbot):
    # Overlaid rather than laid out beneath, so the tile keeps the thumbnail the
    # full height a finished tile's has.
    tile = InFlightTile(_item(status="running"))
    qtbot.addWidget(tile)
    frame, bar = tile._image.geometry(), tile._bar.geometry()

    assert frame.contains(bar)
    assert bar.top() > frame.center().y()


def test_foreign_queue_text_counts_the_whole_of_somebody_elses_queue():
    # Not "ahead of ours" — everything of theirs on the shared server, which is
    # what a surface needs to say while nothing of ours is in flight at all.

    assert foreign_queue_text(6) == "6 jobs from another app are queued on ComfyUI"
    assert foreign_queue_text(1) == "1 job from another app is queued on ComfyUI"
    assert foreign_queue_text(0) is None
    assert foreign_queue_text(None) is None


# --- what a queued run came from, blurred under the wait -------------------


def _source_file(tmp_path):
    path = tmp_path / "asked_of.png"
    Image.new("RGB", (32, 24), (40, 160, 80)).save(path)
    return str(path)


def test_a_queued_run_stands_what_it_came_from_behind_the_wait(qtbot, tmp_path):
    # A line of queued runs is otherwise a line of identical blank plates. What
    # each one was asked of is the only image it has until it draws its own.
    tile = InFlightTile(_item(status="queued", source_file=_source_file(tmp_path)))
    qtbot.addWidget(tile)

    assert not tile._image.pixmap().isNull()


def test_a_run_that_came_from_nothing_keeps_its_plain_plate(qtbot):
    tile = InFlightTile(_item(status="queued", source_file=None))
    qtbot.addWidget(tile)

    assert tile._image.pixmap().isNull()


def test_the_run_s_own_frame_replaces_what_it_came_from(qtbot, tmp_path):
    backdrop = InFlightTile(_item(status="queued", source_file=_source_file(tmp_path)))
    qtbot.addWidget(backdrop)
    standing_in = backdrop._image.pixmap().toImage()

    backdrop.update_item(_item(status="running", frame=_png_bytes(),
                               source_file=_source_file(tmp_path)))

    assert backdrop._image.pixmap().toImage() != standing_in


def test_right_click_requests_a_menu_for_this_tile(qtbot):
    # The tile is the only thing in the collection standing for a run still being made,
    # so a right-click on it has to reach that run. It hands the gesture up with
    # its key rather than answering it, the way a finished tile does — what the
    # menu offers is the pane's business, not the tile's.
    tile = InFlightTile(_item(status="running"))
    qtbot.addWidget(tile)
    received = []
    tile.context_requested.connect(lambda key, pos: received.append(key))

    # What a right-click on the tile triggers (custom context-menu policy).
    tile.customContextMenuRequested.emit(QPoint(5, 5))

    assert received == ["p1"]
