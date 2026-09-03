import io
import time

from PIL import Image
from PyQt6.QtCore import Qt, QPoint

from origenerator.gui.inflight import InFlightItem
from origenerator.gui.inflight_card import InFlightCard
from origenerator.gui.media_badge import MediaBadge


def _png_bytes(color=(200, 50, 50)):
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, format="PNG")
    return buf.getvalue()


def _item(**kw):
    base = dict(key="p1", caption="SDXL › a cat", status="queued",
                frame=None, reveal=lambda: None)
    base.update(kw)
    return InFlightItem(**base)


def test_card_says_queued_over_the_frame(qtbot):
    card = InFlightCard(_item(status="queued"))
    qtbot.addWidget(card)
    assert card._scrim.text() == "Queued…"
    assert card._caption.text() == "SDXL › a cat"


def test_card_says_generating_when_running(qtbot):
    card = InFlightCard(_item(status="running"))
    qtbot.addWidget(card)
    assert card._scrim.text() == "Generating…"


def test_card_shows_the_live_frame_when_one_is_present(qtbot):
    card = InFlightCard(_item(status="running", frame=_png_bytes()))
    qtbot.addWidget(card)
    assert not card._image.pixmap().isNull()


def test_the_stage_message_reads_over_the_frame_rather_than_replacing_it(qtbot):
    # The live frame is the one thing worth looking at; a placeholder that took
    # its place hid it. The scrim dims it and writes over the top instead.
    card = InFlightCard(_item(status="running", frame=_png_bytes()))
    qtbot.addWidget(card)

    assert not card._image.pixmap().isNull()   # the picture is still there
    assert card._scrim.text() == "Generating…"  # and the stage is on top of it
    assert card._scrim.geometry().intersects(card._image.geometry())


def test_media_badge_shows_only_when_the_item_names_a_type(qtbot):
    # An in-flight card on the Recents shelf wears the same image/video badge as a
    # finished tile, so a queued video reads as a video before its first frame.
    plain = InFlightCard(_item())                    # no type known → no badge
    qtbot.addWidget(plain)
    assert plain.findChildren(MediaBadge) == []
    badged = InFlightCard(_item(media_type="video"))
    qtbot.addWidget(badged)
    assert len(badged.findChildren(MediaBadge)) == 1


def test_clicking_the_card_emits_its_key(qtbot):
    card = InFlightCard(_item(key="job-7"))
    qtbot.addWidget(card)
    with qtbot.waitSignal(card.clicked) as sig:
        qtbot.mouseClick(card, Qt.MouseButton.LeftButton)
    assert sig.args == ["job-7"]


def test_update_item_refreshes_caption_frame_and_stage_in_place(qtbot):
    card = InFlightCard(_item(status="queued"))
    qtbot.addWidget(card)
    assert card._scrim.text() == "Queued…"

    card.update_item(_item(caption="new caption", status="running", frame=_png_bytes()))
    assert card._caption.text() == "new caption"
    assert card._scrim.text() == "Generating…"
    assert not card._image.pixmap().isNull()


def test_card_names_another_apps_hold_instead_of_a_bare_queued(qtbot):
    # "Queued…" alone is the mystery: queued behind what? Another app's jobs are
    # the part nothing else in this app can explain.
    card = InFlightCard(_item(status="queued", foreign_ahead=2))
    qtbot.addWidget(card)
    assert card._scrim.text() == "Waiting behind 2 jobs from another app"


def test_a_queue_of_the_users_own_jobs_says_nothing_extra(qtbot):
    # Waiting on his own queue is no mystery — ComfyUI is working through what he
    # asked for — so the card says what it always said.
    card = InFlightCard(_item(status="queued", foreign_ahead=0))
    qtbot.addWidget(card)
    assert card._scrim.text() == "Queued…"


# --- how far along, and how long it has taken --------------------------------

def test_the_bar_carries_the_percentage_and_the_clock(qtbot):
    # The same line the bottom strip's queue writes for the same job: the card
    # used to show neither number, so a run being watched here had to be looked
    # up in the strip to find out how far along it was.
    card = InFlightCard(_item(status="running", progress=(10, 20),
                              started_at=time.time() - 90.5, typical_seconds=725.0))
    qtbot.addWidget(card)
    assert card._bar.caption() == "50% · ~6:02 left"
    assert (card._bar.value(), card._bar.maximum()) == (10, 20)


def test_a_job_comfyui_has_not_started_leaves_the_bar_blank_and_sweeping(qtbot):
    # Its wait is the queue's to explain, not a zero counting up over a bar that
    # has not moved.
    card = InFlightCard(_item(status="queued", started_at=None, typical_seconds=724.0))
    qtbot.addWidget(card)
    assert card._bar.caption() == ""
    assert card._bar.maximum() == 0  # indeterminate: sweeping, not stuck at 0%
    assert not card._tick.isActive()  # and no clock ticking over an unmoving line


def test_the_clock_advances_between_polls(qtbot):
    # The gallery re-feeds the shelf every 1.5s, which would make a seconds count
    # skip; the card re-reads the clock itself so it moves a second at a time.
    card = InFlightCard(_item(status="running", started_at=time.time() - 5.5,
                              typical_seconds=100.0))
    qtbot.addWidget(card)
    assert card._bar.caption() == "~1:34 left"

    card._item.started_at -= 3  # as if three seconds had gone by
    card._tick.timeout.emit()
    assert card._bar.caption() == "~1:31 left"


def test_the_bar_sits_along_the_foot_of_the_frame(qtbot):
    # Overlaid rather than laid out beneath, so the card keeps the picture the
    # full height a finished tile's has.
    card = InFlightCard(_item(status="running"))
    qtbot.addWidget(card)
    frame, bar = card._image.geometry(), card._bar.geometry()

    assert frame.contains(bar)
    assert bar.top() > frame.center().y()


def test_foreign_queue_text_counts_the_whole_of_somebody_elses_queue():
    # Not "ahead of ours" — everything of theirs on the shared server, which is
    # what a surface needs to say while nothing of ours is in flight at all.
    from origenerator.gui.inflight import foreign_queue_text

    assert foreign_queue_text(6) == "6 jobs from another app are queued on ComfyUI"
    assert foreign_queue_text(1) == "1 job from another app is queued on ComfyUI"
    assert foreign_queue_text(0) is None
    assert foreign_queue_text(None) is None


# --- what a queued run came from, blurred behind the wait -------------------


def _source_file(tmp_path):
    path = tmp_path / "asked_of.png"
    Image.new("RGB", (32, 24), (40, 160, 80)).save(path)
    return str(path)


def test_a_queued_run_stands_what_it_came_from_behind_the_wait(qtbot, tmp_path):
    # A line of queued runs is otherwise a line of identical blank plates. What
    # each one was asked of is the only picture it has until it draws its own.
    card = InFlightCard(_item(status="queued", source_picture=_source_file(tmp_path)))
    qtbot.addWidget(card)

    assert not card._image.pixmap().isNull()


def test_a_run_that_came_from_nothing_keeps_its_plain_plate(qtbot):
    card = InFlightCard(_item(status="queued", source_picture=None))
    qtbot.addWidget(card)

    assert card._image.pixmap().isNull()


def test_the_run_s_own_frame_replaces_what_it_came_from(qtbot, tmp_path):
    backdrop = InFlightCard(_item(status="queued", source_picture=_source_file(tmp_path)))
    qtbot.addWidget(backdrop)
    standing_in = backdrop._image.pixmap().toImage()

    backdrop.update_item(_item(status="running", frame=_png_bytes(),
                               source_picture=_source_file(tmp_path)))

    assert backdrop._image.pixmap().toImage() != standing_in


def test_right_click_requests_a_menu_for_this_card(qtbot):
    # The card is the only thing on the shelf standing for a run still being made,
    # so a right-click on it has to reach that run. It hands the gesture up with
    # its key rather than answering it, the way a finished tile does — what the
    # menu offers is the pane's business, not the card's.
    card = InFlightCard(_item(status="running"))
    qtbot.addWidget(card)
    received = []
    card.context_requested.connect(lambda key, pos: received.append(key))

    # What a right-click on the card triggers (custom context-menu policy).
    card.customContextMenuRequested.emit(QPoint(5, 5))

    assert received == ["p1"]
