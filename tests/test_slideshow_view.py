"""SlideshowView — the one fullscreen player: show, advance, lock, neighbors, keys.

Also everything the retired second full-screen viewer used to do on its own, which
this view now covers because a double-clicked picture opens it at a pace of
nought: paging a folder in order, stepping an image's versions, following a
generation that is still being made, and driving the OSR2 off the clip on screen.
"""

from io import BytesIO
from unittest.mock import MagicMock

from PIL import Image
from PyQt6.QtCore import Qt, QEvent, QSize, QUrl
from PyQt6.QtGui import QKeyEvent, QResizeEvent
from PyQt6.QtWidgets import QApplication, QWidget

from origenerator.funscript import funscript_path_for, synthesize_actions, write_funscript
from origenerator.gui.slideshow_pace import SlideshowPace
from origenerator.gui.slideshow_view import SlideshowView
from origenerator.stroke_engine import Stroke

_ITEMS = [("a.png", "image"), ("b.mp4", "video"), ("c.png", "image")]


def _png(path):
    Image.new("RGB", (16, 16), (20, 80, 160)).save(path, "PNG")
    return str(path)


def _png_bytes():
    """A streamed in-progress frame: encoded image bytes, no file on disk."""
    buf = BytesIO()
    Image.new("RGB", (32, 24), (10, 120, 200)).save(buf, "PNG")
    return buf.getvalue()


def _view(qtbot, items=_ITEMS, **kw):
    kw.setdefault("shuffle", lambda order: None)  # deterministic order for these tests
    view = SlideshowView(items, player=MagicMock(), **kw)
    qtbot.addWidget(view)
    return view


def _press(view, key):
    view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def _shift(view, key):
    view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key,
                                 Qt.KeyboardModifier.ShiftModifier))


def _fade(view):
    """What a flash's own timer does when it fires: it is a single shot, so it is
    no longer running by the time the note falls back to whatever the show would
    otherwise be saying."""
    view._note_timer.stop()
    view._refresh_note()


def test_opens_on_the_first_item(qtbot):
    view = _view(qtbot)
    assert view._playlist.current() == ("a.png", "image")
    assert view._preview.is_showing_video() is False


def test_right_and_left_navigate(qtbot):
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Right)
    assert view._playlist.current() == ("b.mp4", "video")
    assert view._preview.is_showing_video() is True
    _press(view, Qt.Key.Key_Left)
    assert view._playlist.current() == ("a.png", "image")


def test_a_finished_video_advances_to_the_next(qtbot):
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Right)          # -> the video
    view._preview.video_ended.emit()        # it played through
    assert view._playlist.current() == ("c.png", "image")


def test_a_locked_video_replays_instead_of_advancing(qtbot):
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Right)          # -> the video
    _press(view, Qt.Key.Key_Down)           # lock it: repeat-one, as Fun Time's is
    view._preview.video_ended.emit()
    assert view._playlist.current() == ("b.mp4", "video")  # stayed put
    assert view._playlist.locked


def test_down_toggles_the_lock_and_the_caption_reflects_it(qtbot):
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Down)
    assert view._playlist.locked
    assert "locked" in view._counter.text()
    _press(view, Qt.Key.Key_Down)
    assert not view._playlist.locked
    assert "locked" not in view._counter.text()


def test_stepping_away_releases_the_lock(qtbot):
    # Right off a held slide is the way out of the hold — no second Down needed,
    # matching Fun Time's next/prev.
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Down)
    _press(view, Qt.Key.Key_Right)
    assert not view._playlist.locked
    assert view._playlist.current() == ("b.mp4", "video")
    assert "locked" not in view._counter.text()

    _press(view, Qt.Key.Key_Down)
    _press(view, Qt.Key.Key_Left)           # and back the other way
    assert not view._playlist.locked
    assert view._playlist.current() == ("a.png", "image")


def test_the_consoles_transport_releases_the_lock_too(qtbot):
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Down)
    view.stroke_step(1)                     # the console's transport, not the key
    assert not view.locked
    assert view._playlist.current() == ("b.mp4", "video")


def test_culling_releases_the_lock(qtbot):
    items = [("a.png", "image", "id-a"), ("b.png", "image", "id-b")]
    view = SlideshowView(items, player=MagicMock(), shuffle=lambda order: None,
                         on_delete=lambda prompt_id: None)
    qtbot.addWidget(view)
    _press(view, Qt.Key.Key_Down)
    _press(view, Qt.Key.Key_Up)             # the held slide is the one condemned
    assert not view._playlist.locked
    assert view._timer.isActive()           # so the rest keeps rotating


class _FakeStroke:
    """Enough of the stroke driver for the shared keys and the drive panel."""

    def __init__(self):
        self.active = False
        self.calls = []
        self.state = Stroke()

    def toggle(self):
        self.active = not self.active
        self.calls.append(("toggle", self.active))
        return self.active

    def adjust_speed(self, delta):
        self.calls.append(("speed", delta))

    def status_text(self):
        return "OSR2 stub"


def test_space_drives_the_shared_stroke_not_the_lock(qtbot):
    # Space belongs to the app-global OSR2 stroke everywhere; locking the
    # slideshow is Down. The standing caption comes with the wired stroke.
    stroke = _FakeStroke()
    view = SlideshowView(_ITEMS, player=MagicMock(), shuffle=lambda order: None,
                         stroke=stroke)
    qtbot.addWidget(view)
    assert view._stroke_panel is not None  # the drive panel rides along
    _press(view, Qt.Key.Key_Space)
    assert ("toggle", True) in stroke.calls
    assert not view._playlist.locked


def test_escape_closes_the_view(qtbot):
    view = _view(qtbot)
    view.show()
    _press(view, Qt.Key.Key_Escape)
    assert not view.isVisible()


def test_up_deletes_the_current_item_and_advances(qtbot):
    deleted = []
    items = [("a.png", "image", "id-a"), ("b.png", "image", "id-b"),
             ("c.png", "image", "id-c")]
    view = SlideshowView(items, player=MagicMock(), shuffle=lambda order: None,
                         on_delete=deleted.append)
    qtbot.addWidget(view)
    assert view._playlist.current()[2] == "id-a"

    _press(view, Qt.Key.Key_Up)

    assert deleted == ["id-a"]                     # culled via the on_delete hook
    assert len(view._playlist) == 2
    assert view._playlist.current()[2] == "id-b"   # advanced to the next


def test_down_holds_the_slideshow(qtbot):
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Down)
    assert view._playlist.locked


def test_the_caption_shows_the_item_number(qtbot):
    view = _view(qtbot)  # identity shuffle, so order == [0, 1, 2]
    assert view._counter.text().startswith("1 / 3")
    _press(view, Qt.Key.Key_Right)
    assert view._counter.text().startswith("2 / 3")


def test_enter_leaves_for_the_shown_items_folder(qtbot):
    items = [("a.png", "image", "id-a"), ("b.png", "image", "id-b")]
    view = SlideshowView(items, player=MagicMock(), shuffle=lambda order: None)
    qtbot.addWidget(view)
    view.show()
    opened = []
    view.open_requested.connect(opened.append)

    _press(view, Qt.Key.Key_Return)

    assert opened == ["id-a"]     # the gallery is handed the item on screen
    assert not view.isVisible()   # and the slideshow is out of the way


def _shelf_view(qtbot):
    """A two-item show whose handovers are recorded — the ways out of a show."""
    items = [("a.png", "image", "id-a"), ("b.png", "image", "id-b")]
    view = SlideshowView(items, player=MagicMock(), shuffle=lambda order: None)
    qtbot.addWidget(view)
    view.show()
    opened = []
    view.open_requested.connect(opened.append)
    return view, opened


def test_ending_a_show_on_a_locked_slide_hands_that_slide_over(qtbot):
    # Locking says "this is the one", so ending the show there means the same
    # thing Enter does: the gallery lands on that item rather than back wherever
    # it was when the show started.
    view, opened = _shelf_view(qtbot)
    _press(view, Qt.Key.Key_Right)  # onto the second slide
    _press(view, Qt.Key.Key_Down)   # hold it

    _press(view, Qt.Key.Key_Escape)

    assert opened == ["id-b"]
    assert not view.isVisible()


def test_ending_a_show_on_an_unheld_slide_hands_nothing_over(qtbot):
    # Every other way out is just leaving: the gallery stays where it was.
    view, opened = _shelf_view(qtbot)

    _press(view, Qt.Key.Key_Escape)

    assert opened == []


def test_enter_on_a_held_slide_hands_it_over_once(qtbot):
    # Enter and the lock name the same item, and the handover is closeEvent's, so
    # the gallery is asked to go there once rather than twice.
    view, opened = _shelf_view(qtbot)
    _press(view, Qt.Key.Key_Down)

    _press(view, Qt.Key.Key_Return)

    assert opened == ["id-a"]


def test_closing_a_show_twice_hands_over_once(qtbot):
    # Qt sends a close event to an already-closed window too.
    view, opened = _shelf_view(qtbot)
    _press(view, Qt.Key.Key_Down)

    view.close()
    view.close()

    assert opened == ["id-a"]


def test_culling_the_last_slide_hands_nothing_over(qtbot):
    # The show empties and closes itself, and the item it ended on is in the bin —
    # nowhere to land.
    deleted = []
    view = SlideshowView([("a.png", "image", "id-a")], player=MagicMock(),
                         shuffle=lambda order: None, on_delete=deleted.append)
    qtbot.addWidget(view)
    view.show()
    opened = []
    view.open_requested.connect(opened.append)
    _press(view, Qt.Key.Key_Down)  # held, then condemned anyway

    _press(view, Qt.Key.Key_Up)

    assert deleted == ["id-a"]
    assert opened == []


def test_the_items_either_side_ride_along_as_stills(qtbot, tmp_path):
    items = [(_png(tmp_path / f"{name}.png"), "image", f"id-{name}")
             for name in ("a", "b", "c")]
    view = SlideshowView(items, player=MagicMock(), shuffle=lambda order: None)
    qtbot.addWidget(view)
    view.resize(800, 600)

    left, right = view._neighbors._labels
    assert view._neighbors._sources == (items[2][0], items[1][0])  # c behind, b ahead
    assert not left.pixmap().isNull() and not right.pixmap().isNull()

    _press(view, Qt.Key.Key_Right)  # onto b: a behind it now, c ahead
    assert view._neighbors._sources == (items[0][0], items[2][0])


def test_a_video_neighbor_falls_back_to_its_thumbnail(qtbot, tmp_path):
    thumb = _png(tmp_path / "thumb.png")
    items = [("a.png", "image", "id-a"), ("b.mp4", "video", "id-b", thumb)]
    view = SlideshowView(items, player=MagicMock(), shuffle=lambda order: None)
    qtbot.addWidget(view)

    # Two items, so the clip is both what's behind and what's ahead — and it's
    # drawn as its stored still, the only thing a video can show small.
    assert view._neighbors._sources == (thumb, thumb)


def test_a_single_item_slideshow_shows_no_neighbors(qtbot, tmp_path):
    view = SlideshowView([(_png(tmp_path / "only.png"), "image", "id")],
                         player=MagicMock(), shuffle=lambda order: None)
    qtbot.addWidget(view)

    assert view._neighbors._sources == (None, None)  # itself is no neighbor
    assert all(label.isHidden() for label in view._neighbors._labels)


# --- a generation that lands while the show runs ----------------------------

def test_a_generation_that_lands_joins_the_show(qtbot):
    # Watching a folder that is still generating is the case this is for: the
    # loop's next item joins the set and comes up next, without disturbing the
    # slide being looked at.
    view = _view(qtbot, [("a.png", "image", "id-a")])

    view.note_added("new.png", "image", "id-new", None)

    assert len(view._playlist) == 2
    assert view._playlist.current()[2] == "id-a"
    assert view._playlist.peek(1)[2] == "id-new"


def test_a_generation_already_playing_does_not_join_twice(qtbot):
    view = _view(qtbot, [("a.png", "image", "id-a")])

    view.note_added("a.png", "image", "id-a", None)

    assert len(view._playlist) == 1


def test_an_arrival_takes_its_place_beside_the_slide_on_screen(qtbot, tmp_path):
    # The neighbor stills are what say a show has more than one item in it, so a
    # show that was alone until now has to redraw them.
    thumb = _png(tmp_path / "new_thumb.png")
    view = _view(qtbot, [(_png(tmp_path / "a.png"), "image", "id-a")])
    view.resize(800, 600)
    assert view._neighbors._sources == (None, None)

    view.note_added("new.mp4", "video", "id-new", thumb)

    assert view._neighbors._sources == (thumb, thumb)
    assert "2" in view._counter.text()  # and the counter counts it


# --- holding a slide asks for it to be enhanced -----------------------------

_KEYED = [("a.png", "image", "id-a"), ("b.png", "image", "id-b")]


def test_holding_a_slide_asks_for_it_to_be_enhanced(qtbot):
    # Stopping on a picture is the gesture that says you want it, so it is also
    # the one that asks for the better version.
    asked = []
    view = _view(qtbot, _KEYED, on_enhance=lambda pid: asked.append(pid) or True)

    _press(view, Qt.Key.Key_Down)

    assert asked == ["id-a"]
    assert view._playlist.locked
    # In the line until the gallery says otherwise — a launch is a place in the
    # queue, not a picture being made.
    assert view._note.text() == "Enhancement queued"


def test_releasing_the_hold_asks_for_nothing(qtbot):
    asked = []
    view = _view(qtbot, _KEYED, on_enhance=lambda pid: asked.append(pid) or True)
    _press(view, Qt.Key.Key_Down)   # hold
    _press(view, Qt.Key.Key_Down)   # release
    assert asked == ["id-a"]        # only the stop asked, not the resume


def test_the_gallery_can_refuse_and_nothing_is_claimed(qtbot):
    # It already has a version at these settings, or it is a video: the refusal
    # comes from the side that holds the settings, and the corner stays quiet.
    view = _view(qtbot, _KEYED, on_enhance=lambda pid: False)
    _press(view, Qt.Key.Key_Down)
    assert view._note.isHidden()


def test_e_turns_the_whole_behavior_off(qtbot):
    asked = []
    view = _view(qtbot, _KEYED, on_enhance=lambda pid: asked.append(pid) or True)

    _press(view, Qt.Key.Key_E)
    _press(view, Qt.Key.Key_Down)
    assert asked == []
    assert "off" in view._note.text()

    _press(view, Qt.Key.Key_E)      # and back on
    _press(view, Qt.Key.Key_Down)   # release the hold
    _press(view, Qt.Key.Key_Down)   # hold again
    assert asked == ["id-a"]


def test_a_slide_whose_run_is_still_in_the_line_says_queued_not_enhancing(qtbot):
    # Holding several slides sends out several runs and ComfyUI takes them one at
    # a time, so a slide the show comes back around to is usually still waiting.
    view = _view(qtbot, _KEYED, on_enhance=lambda pid: True)
    _press(view, Qt.Key.Key_Down)        # ask for this one
    _press(view, Qt.Key.Key_Down)        # let go, so the show can move
    _press(view, Qt.Key.Key_Right)
    _press(view, Qt.Key.Key_Down)        # and ask for the next

    view.note_enhancing({"id-a": "running", "id-b": "queued"})

    assert view._note.text() == "Enhancement queued"
    _press(view, Qt.Key.Key_Down)        # let go
    _press(view, Qt.Key.Key_Left)        # back to the one being made
    assert view._note.text() == "Enhancing…"


def test_the_note_follows_the_run_from_the_line_onto_the_gpu(qtbot):
    view = _view(qtbot, _KEYED, on_enhance=lambda pid: True)
    _press(view, Qt.Key.Key_Down)
    assert view._note.text() == "Enhancement queued"

    view.note_enhancing({"id-a": "running"})

    assert view._note.text() == "Enhancing…"


def test_a_run_of_an_item_this_show_never_asked_about_says_nothing(qtbot):
    # Enhance All queues its own runs while a show plays; the corner speaks for
    # the ones this show asked for, and stays out of the way otherwise.
    view = _view(qtbot, _KEYED)
    view.note_enhancing({"id-a": "running"})
    assert view._note.isHidden()


def test_a_status_arriving_mid_sentence_does_not_wipe_a_spoken_answer(qtbot):
    # The statuses arrive every poll; a spoken command's answer is on screen for
    # a beat, and losing it to one would leave the speaker with no reply.
    view = _view(qtbot, _KEYED, on_enhance=lambda pid: True)
    view.note_voice_run("id-a", "🎤 fixing teeth…")

    view.note_enhancing({"id-a": "running"})

    assert "fixing teeth" in view._note.text()
    _fade(view)
    assert view._note.text() == "Enhancing…"


def test_the_enhanced_version_replaces_the_slide_when_it_lands(qtbot, tmp_path):
    view = _view(qtbot, _KEYED, on_enhance=lambda pid: True)
    _press(view, Qt.Key.Key_Down)
    better = _png(tmp_path / "a_enhanced.png")

    view.note_enhanced("id-a", better)

    assert view._playlist.current()[0] == better
    assert view._note.isHidden()   # nothing cooking for this slide any more


def test_an_enhancement_that_lands_after_paging_on_still_upgrades_the_item(
        qtbot, tmp_path):
    # It arrives minutes later, by which time the show has moved — and the show
    # plays a set fixed when it opened, so an arrival dropped for being late
    # would replay the pre-enhance file every pass from here on.
    view = _view(qtbot, _KEYED, on_enhance=lambda pid: True)
    _press(view, Qt.Key.Key_Down)
    _press(view, Qt.Key.Key_Right)
    better = _png(tmp_path / "a_enhanced.png")

    view.note_enhanced("id-a", better)

    assert view._playlist.current()[0] == "b.png"   # the slide on screen is left alone
    _press(view, Qt.Key.Key_Left)                   # and a comes round upgraded
    assert view._playlist.current()[0] == better


def test_an_enhancement_of_another_folders_item_changes_nothing(qtbot, tmp_path):
    # Every landed enhancement is offered to every open show; this one belongs
    # to a folder this show isn't playing.
    view = _view(qtbot, _KEYED, on_enhance=lambda pid: True)

    view.note_enhanced("id-elsewhere", _png(tmp_path / "other.png"))

    assert [item[0] for item in view._playlist._items] == ["a.png", "b.png"]


def test_the_upgraded_item_is_drawn_as_its_new_still_beside_the_slide(
        qtbot, tmp_path):
    # An item rides along as a small still while its neighbor is on screen; the
    # thumbnail it arrived with is of the version the swap just retired.
    view = _view(qtbot, _KEYED, on_enhance=lambda pid: True)
    view.resize(800, 600)
    better_thumb = _png(tmp_path / "b_enhanced_thumb.png")

    view.note_enhanced("id-b", _png(tmp_path / "b_enhanced.png"),
                       still=better_thumb)

    assert better_thumb in view._neighbors._sources


def test_a_slideshow_with_no_enhancer_still_holds_on_down(qtbot):
    view = _view(qtbot, _KEYED)     # no on_enhance wired
    _press(view, Qt.Key.Key_Down)
    assert view._playlist.locked
    assert view._note.isHidden()


def test_the_enhancing_note_sits_above_the_counter_not_over_the_console(qtbot):
    # genau's console holds the top-left corner of this view too.
    view = _view(qtbot, _KEYED, on_enhance=lambda pid: True)
    view.resize(800, 600)
    _press(view, Qt.Key.Key_Down)

    note, counter = view._note.geometry(), view._counter.geometry()
    assert note.top() > view.height() // 2      # bottom half, clear of the console
    assert note.bottom() <= counter.top()       # stacked with it, not over it
    assert abs(note.center().x() - view.width() // 2) <= 1


# --- the queue, in the corner this view leaves empty -------------------------

def _inflight(**kw):
    from origenerator.gui.inflight import InFlightItem

    kw.setdefault("key", "j1")
    kw.setdefault("caption", "Alpha Workflow › a paper kite")
    kw.setdefault("status", "queued")
    kw.setdefault("frame", None)
    kw.setdefault("reveal", lambda: None)
    return InFlightItem(**kw)


def test_the_queue_rides_along_in_the_shows_bottom_left(qtbot):
    # The bottom strip that normally carries it is behind this view, and a show
    # is when the queue stops moving: its videos are held until it ends.
    view = _view(qtbot)
    view.resize(1920, 1080)
    QApplication.sendEvent(view, QResizeEvent(QSize(1920, 1080), QSize(640, 480)))
    view.set_queue([_inflight(status="running", typical_seconds=30, job_kind="Image"),
                    _inflight(key="j2", typical_seconds=600, job_kind="T2V",
                              held=True)])

    plate = view._queue.geometry()
    assert view._queue.keys() == ["j1", "j2"]        # the rows themselves
    assert view._queue.running_preview().key == "j1"  # and the live half
    assert plate.left() < view.width() // 2      # left…
    assert plate.top() > view.height() // 2      # …and low, clear of the console
    assert not plate.intersects(view._counter.geometry())  # beside it, not over it


def test_a_show_with_nothing_in_flight_shows_no_queue_at_all(qtbot):
    view = _view(qtbot)
    view.set_queue([])
    assert view._queue.isHidden()


def test_the_queue_follows_the_shows_bottom_edge_on_a_resize(qtbot):
    view = _view(qtbot)
    view.resize(800, 600)
    view.set_queue([_inflight(typical_seconds=30, job_kind="Image")])

    view.resize(1200, 900)
    QApplication.sendEvent(view, QResizeEvent(QSize(1200, 900), QSize(800, 600)))

    assert view._queue.y() + view._queue.height() == 900 - 24


def test_a_press_in_the_queue_leaves_the_arrows_stepping_the_show(qtbot):
    # A Cancel that took focus would stop the show responding to its own keys.
    view = _view(qtbot)
    view.set_queue([_inflight(status="running", typical_seconds=30,
                              cancel=lambda: None)])
    assert all(child.focusPolicy() == Qt.FocusPolicy.NoFocus
               for child in view._queue.findChildren(QWidget))


# --- locking also stars, and a double-click leaves ---------------------------

def test_locking_stars_the_item_on_screen(qtbot):
    # Holding a slide is how the user says this one is worth keeping; having said
    # it once they should not have to say it again in a second way.
    starred = []
    items = [("a.png", "image", "gen-a", None), ("b.png", "image", "gen-b", None)]
    view = _view(qtbot, items=items, on_star=starred.append)

    _press(view, Qt.Key.Key_Down)

    assert view._playlist.locked
    assert starred == ["gen-a"]


def test_letting_go_of_the_lock_does_not_unstar(qtbot):
    starred = []
    items = [("a.png", "image", "gen-a", None)]
    view = _view(qtbot, items=items, on_star=starred.append)

    _press(view, Qt.Key.Key_Down)
    _press(view, Qt.Key.Key_Down)

    assert not view._playlist.locked
    assert starred == ["gen-a"]  # starred once, on the way in


def test_a_slideshow_without_a_starrer_still_locks(qtbot):
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Down)
    assert view._playlist.locked


# --- the transport a spoken word drives, saying which way rather than flipping

def test_asking_for_a_hold_holds_and_asking_again_changes_nothing(qtbot):
    # Someone talking to a picture is asking for a state, not for the other one,
    # and cannot see the counter's padlock to know which the flip would give.
    starred = []
    items = [("a.png", "image", "gen-a", None), ("b.png", "image", "gen-b", None)]
    view = _view(qtbot, items=items, on_star=starred.append)

    assert view.set_held(True) is True
    assert view.locked and starred == ["gen-a"]

    assert view.set_held(True) is False   # already holding: nothing moved
    assert view.locked and starred == ["gen-a"]


def test_a_spoken_hold_stars_the_slide_like_a_pressed_one(qtbot):
    # Holding is Down's whole gesture here; a spoken hold must not quietly mean
    # less than a pressed one.
    starred = []
    items = [("a.png", "image", "gen-a", None)]
    view = _view(qtbot, items=items, on_star=starred.append)

    view.set_held(True)

    assert starred == ["gen-a"]


def test_asking_to_let_go_releases_only_what_was_held(qtbot):
    view = _view(qtbot)

    assert view.set_held(False) is False   # nothing was held
    view.set_held(True)
    assert view.set_held(False) is True
    assert not view.locked


def test_starring_the_slide_on_screen_without_holding_it(qtbot):
    starred = []
    items = [("a.png", "image", "gen-a", None)]
    view = _view(qtbot, items=items, on_star=starred.append)

    assert view.star() is True

    assert starred == ["gen-a"]
    assert not view.locked  # bookmarked, still moving on


def test_starring_says_no_when_there_is_nothing_to_star(qtbot):
    # A show whose items carry no generation id — or a live one with no row of
    # its own yet — has nothing to bookmark, and says so rather than seeming to.
    assert _view(qtbot).star() is False


def test_stepping_and_culling_are_the_arrows_own_moves(qtbot):
    culled = []
    items = [("a.png", "image", "gen-a", None), ("b.png", "image", "gen-b", None),
             ("c.png", "image", "gen-c", None)]
    view = _view(qtbot, items=items, on_delete=culled.append)

    view.step(1)
    assert view._playlist.current()[2] == "gen-b"
    view.step(-1)
    assert view._playlist.current()[2] == "gen-a"

    view.cull()
    assert culled == ["gen-a"]
    assert view._playlist.current()[2] == "gen-b"


def test_stepping_off_a_held_slide_releases_it(qtbot):
    # The same rule the arrows follow: a lock holds the slide it was set on, not
    # wherever the user wanders to.
    view = _view(qtbot)
    view.set_held(True)

    view.step(1)

    assert not view.locked


def test_double_clicking_leaves_the_slideshow(qtbot):
    # The way out of every other fullscreen view here, and the way it used to work.
    view = _view(qtbot)
    view.show()
    closes = []
    view.closed.connect(lambda: closes.append(True))
    view._preview._on_double_click()
    assert not view.isVisible()
    assert closes == [True]  # the dismissal reaches the gallery, like Escape's


def test_a_spoken_fix_targets_the_slide_on_screen(qtbot):
    view = _view(qtbot, _KEYED)
    assert view.voice_target() == "id-a"
    _press(view, Qt.Key.Key_Right)
    assert view.voice_target() == "id-b"


def test_a_spoken_fix_answers_in_the_corner_then_reads_enhancing(qtbot):
    view = _view(qtbot, _KEYED, on_enhance=lambda pid: True)
    view.note_voice_run("id-a", "🎤 fixing teeth…")
    assert "fixing teeth" in view._note.text()
    # The flash fades into the same note a hold's enhance earns, which follows
    # the run: waiting its turn, then being made, until the version lands.
    _fade(view)
    assert view._note.text() == "Enhancement queued"
    view.note_enhancing({"id-a": "running"})
    assert view._note.text() == "Enhancing…"


def test_a_declined_spoken_fix_flashes_and_marks_nothing(qtbot):
    view = _view(qtbot, _KEYED)
    view.note_voice_run(None, "🎤 no teeth detector installed")
    assert "no teeth detector" in view._note.text()
    _fade(view)
    assert view._note.isHidden()


def test_closing_announces_itself(qtbot):
    # The gallery keeps voice-command listening tied to a surface being up, so
    # a dismissal it didn't initiate (Escape) must still reach it.
    view = _view(qtbot)
    closes = []
    view.closed.connect(lambda: closes.append(True))
    view.close()
    assert closes == [True]


# --- a pace of nought: what double-clicking a picture opens ------------------

def test_a_pace_of_nought_holds_the_slide_with_no_timer(qtbot):
    # The shape a double-clicked picture opens in: one show, standing still,
    # rather than a second full-screen viewer with its own keys to learn.
    view = _view(qtbot, image_dwell_ms=0)
    assert view.dwell_s == 0
    assert not view._timer.isActive()
    assert view._playlist.dwell_ms() is None


def test_the_arrows_still_move_a_show_held_at_nought(qtbot):
    view = _view(qtbot, image_dwell_ms=0)
    _press(view, Qt.Key.Key_Right)
    assert view._playlist.current() == ("b.mp4", "video")


def test_a_clip_replays_rather_than_advancing_at_nought(qtbot):
    # Nothing moves on its own at nought — a finished clip included, which is how
    # the retired viewer's looping video behaved.
    view = _view(qtbot, image_dwell_ms=0)
    _press(view, Qt.Key.Key_Right)          # -> the video
    view._preview.video_ended.emit()
    assert view._playlist.current() == ("b.mp4", "video")


def test_turning_the_console_pace_up_sets_a_held_show_going(qtbot):
    # The console's clip-seconds pair is what starts a double-clicked picture
    # moving, and the number it sets is the app-wide one.
    pace = SlideshowPace(parent=None)
    view = _view(qtbot, image_dwell_ms=0, pace=pace)

    view.set_dwell_s(2)

    assert view.dwell_s == 2
    assert pace.seconds == 2
    assert view._timer.isActive()


def test_turning_up_to_the_pace_the_app_already_held_still_starts_it(qtbot):
    # The app-wide pace never moves here, so no signal comes back — the show has
    # to take the number itself or it stays frozen at nought forever.
    pace = SlideshowPace(seconds=1, parent=None)
    view = _view(qtbot, image_dwell_ms=0, pace=pace)

    view.set_dwell_s(1)

    assert view.dwell_s == 1
    assert view._timer.isActive()


def test_the_pace_can_be_wound_back_down_to_nought(qtbot):
    view = _view(qtbot, image_dwell_ms=4000)
    view.set_dwell_s(0)
    assert view.dwell_s == 0
    assert not view._timer.isActive()


def test_a_show_opens_on_the_item_it_was_asked_for(qtbot):
    # Double-clicking the third picture in a folder opens on the third picture.
    view = _view(qtbot, start=2)
    assert view._playlist.current() == ("c.png", "image")
    assert view._counter.text().startswith("3 / 3")


# --- re-seeding the set after it opened -------------------------------------

def test_set_playlist_hands_the_folder_to_a_show_opened_on_one_item(qtbot):
    # The pane that was double-clicked knows one file; the gallery knows the
    # folder it sits in, and arms the show with it.
    view = _view(qtbot, [("b.png", "image", "id-b")])
    view.set_playlist([("a.png", "image", "id-a"), ("b.png", "image", "id-b"),
                       ("c.png", "image", "id-c")], 1)

    assert view._counter.text().startswith("2 / 3")
    _press(view, Qt.Key.Key_Right)
    assert view._playlist.current()[2] == "id-c"
    _press(view, Qt.Key.Key_Left)
    _press(view, Qt.Key.Key_Left)
    assert view._playlist.current()[2] == "id-a"   # in the folder's own order


def test_a_re_seeded_set_wraps_at_either_end(qtbot):
    view = _view(qtbot, [("a.png", "image", "id-a")])
    view.set_playlist([("a.png", "image", "id-a"), ("b.png", "image", "id-b")], 0)

    _press(view, Qt.Key.Key_Left)   # from the first, wrap back to the last
    assert view._playlist.current()[2] == "id-b"
    _press(view, Qt.Key.Key_Right)  # and forward off the last, wrap to the first
    assert view._playlist.current()[2] == "id-a"


def test_a_re_seeded_set_keeps_the_pace_the_show_opened_at(qtbot):
    view = _view(qtbot, [("a.png", "image", "id-a")], image_dwell_ms=0)
    view.set_playlist([("a.png", "image", "id-a"), ("b.png", "image", "id-b")], 0)
    assert view._playlist.dwell_ms() is None  # still held, not back at the default


# --- Shift+Left/Right: the versions of the image on screen -------------------

def test_shift_arrows_step_the_versions_of_the_image_on_screen(qtbot, tmp_path):
    enhanced, original = (_png(tmp_path / n) for n in ("e1.png", "src.png"))
    view = _view(qtbot, [(enhanced, "image", "id-a")])
    view.set_levels({enhanced: [(enhanced, "image"), (original, "image")]})

    _shift(view, Qt.Key.Key_Right)
    assert view._preview._media[0] == original
    # And back round: two versions wrap, so the pair is a toggle.
    _shift(view, Qt.Key.Key_Right)
    assert view._preview._media[0] == enhanced


def test_shift_arrows_do_nothing_for_an_image_with_one_version(qtbot, tmp_path):
    lone = _png(tmp_path / "only.png")
    view = _view(qtbot, [(lone, "image", "id-a")])
    view.set_levels({})

    _shift(view, Qt.Key.Key_Right)

    # Silently nothing, rather than stepping the set when the shift was the
    # whole point of the press.
    assert view._preview._media[0] == lone


def test_stepping_to_another_image_starts_its_versions_from_the_top(qtbot, tmp_path):
    first, second, second_base = (_png(tmp_path / n) for n in
                                  ("a.png", "b.png", "b_base.png"))
    view = _view(qtbot, [(first, "image", "id-a"), (second, "image", "id-b")])
    view.set_levels({second: [(second, "image"), (second_base, "image")]})

    _press(view, Qt.Key.Key_Right)   # onto the second image
    _shift(view, Qt.Key.Key_Right)   # its own versions, from the top

    assert view._preview._media[0] == second_base


def test_the_note_says_which_version_is_on_screen(qtbot, tmp_path):
    # Two versions of one picture differ by texture, which is exactly what you
    # cannot tell apart from memory — so the view has to say which one this is.
    enhanced, original = (_png(tmp_path / n) for n in ("e1.png", "src.png"))
    view = _view(qtbot, [(enhanced, "image", "id-a")])
    view.set_levels({enhanced: [(enhanced, "image", "Enhance 1"),
                                (original, "image", "Original")]})

    assert view._note.text() == "Enhance 1 — 1 of 2"
    _shift(view, Qt.Key.Key_Right)
    assert view._note.text() == "Original — 2 of 2"


def test_an_image_with_one_version_says_nothing(qtbot, tmp_path):
    view = _view(qtbot, [(_png(tmp_path / "only.png"), "image", "id-a")])
    view.set_levels({})
    assert view._note.isHidden()


def test_a_version_step_keeps_the_item_as_the_enhance_target(qtbot, tmp_path):
    # The file on screen is one of this item's versions, but the generation being
    # asked about is still the item's — read off the playlist, not off the file.
    enhanced, original = (_png(tmp_path / n) for n in ("e1.png", "src.png"))
    view = _view(qtbot, [(enhanced, "image", "id-a")])
    view.set_levels({enhanced: [(enhanced, "image"), (original, "image")]})

    _shift(view, Qt.Key.Key_Right)

    assert view.voice_target() == "id-a"


def test_a_version_step_re_aims_the_device(qtbot, tmp_path):
    enhanced, original = (_png(tmp_path / n) for n in ("e1.png", "src.png"))
    view = _view(qtbot, [(enhanced, "image", "id-a")])
    view.set_levels({enhanced: [(enhanced, "image"), (original, "image")]})
    changed = []
    view.media_changed.connect(lambda: changed.append(True))

    _shift(view, Qt.Key.Key_Right)

    assert changed == [True]


# --- opened over a generation still being made ------------------------------

def test_opens_over_a_running_generation_showing_its_frame(qtbot):
    view = _view(qtbot, [], frame=_png_bytes())
    assert view.is_live() is True
    assert view._preview._media is None                     # no file behind it yet
    assert not view._preview._image_label.pixmap().isNull()  # the streamed frame shows


def test_opened_before_the_first_frame_it_says_it_is_generating(qtbot):
    view = _view(qtbot, [])
    assert view.is_live() is True
    assert view._preview._image_label.text() == "Generating…"


def test_a_later_frame_replaces_the_one_it_opened_over(qtbot):
    view = _view(qtbot, [])
    view.show_frame(_png_bytes())
    assert not view._preview._image_label.pixmap().isNull()


def test_the_landed_file_takes_over_from_the_frames(qtbot, tmp_path):
    # Watching a generation full-screen ends on the finished image, not the last
    # low-res frame it streamed.
    png = _png(tmp_path / "done.png")
    view = _view(qtbot, [], frame=_png_bytes())
    changed = []
    view.media_changed.connect(lambda: changed.append(True))

    view.show_landed((png, "image"))

    assert view._preview._media == (png, "image")
    assert view.is_live() is False
    assert changed == [True]  # a landed video is a fresh OSR2 target


def test_frames_are_ignored_once_it_has_landed(qtbot, tmp_path):
    png = _png(tmp_path / "done.png")
    view = _view(qtbot, [])
    view.show_landed((png, "image"))

    view.show_frame(_png_bytes())  # a later run's frames must not paint over it

    assert view._preview._media == (png, "image")


def test_stepping_leaves_the_live_generation_behind(qtbot, tmp_path):
    # Stepped onto a saved item, the show is no longer the run's — later frames of
    # it must not paint over what the user stepped to.
    a, b = (_png(tmp_path / n) for n in ("a.png", "b.png"))
    view = _view(qtbot, [], frame=_png_bytes())
    view.set_playlist([(a, "image", "id-a"), (b, "image", "id-b")], 0)

    _press(view, Qt.Key.Key_Right)

    assert view.is_live() is False
    assert view._preview._media == (b, "image")


def test_a_run_with_no_folder_armed_behind_it_ignores_the_arrows(qtbot):
    view = _view(qtbot, [], frame=_png_bytes())
    _press(view, Qt.Key.Key_Right)
    assert view.is_live() is True
    assert not view._preview._image_label.pixmap().isNull()


def test_a_live_show_counts_nothing_until_it_steps_off(qtbot, tmp_path):
    # It has no place among the folder's files while it is still being made.
    a, b = (_png(tmp_path / n) for n in ("a.png", "b.png"))
    view = _view(qtbot, [], frame=_png_bytes())
    view.set_playlist([(a, "image", "id-a"), (b, "image", "id-b")], 0)
    assert view._counter.isHidden()
    assert view._neighbors._sources == (None, None)

    _press(view, Qt.Key.Key_Right)

    assert view._counter.isHidden() is False
    assert view._counter.text().startswith("2 / 2")


def test_a_live_show_drives_no_device(qtbot):
    # Streamed frames are no video: nothing for the OSR2 to follow.
    view = _view(qtbot, [], frame=_png_bytes())
    assert view.osr2_drive_target() is None


# --- what a fullscreen show is, as media ------------------------------------

def test_it_fits_the_image_to_the_screen_without_clipping(qtbot, tmp_path):
    # The reported "black on all four sides" was the image left scaled at its tiny
    # pre-show size on the full screen.
    Image.new("RGB", (24, 60), (10, 120, 200)).save(tmp_path / "tall.png", "PNG")
    view = _view(qtbot, [(str(tmp_path / "tall.png"), "image")])
    label = view._preview._image_label
    old = label.size()
    label.resize(600, 500)  # stand in for the screen the window grows to
    QApplication.sendEvent(label, QResizeEvent(QSize(600, 500), old))

    pm = label.pixmap()
    assert pm.width() <= 600 and pm.height() <= 500        # nothing clipped off
    assert pm.width() == 600 or pm.height() == 500         # as large as it fits


def test_it_plays_audio_unlike_the_muted_inline_preview(qtbot):
    # Filling the screen with a clip is deliberate, so it's heard.
    view = _view(qtbot)
    assert view._preview._audio.isMuted() is False


def test_a_scripted_clip_shows_its_strip(qtbot, tmp_path):
    vid = tmp_path / "c.mp4"
    write_funscript(funscript_path_for(vid), synthesize_actions(2.0, hz=1.0, loop=False))
    view = _view(qtbot, [(str(vid), "video")])
    assert view._preview._strip is not None
    assert view._preview._strip.has_script() is True


def test_it_does_not_nest_another_fullscreen_view(qtbot):
    view = _view(qtbot)
    assert view._preview.open_fullscreen() is None


def test_closing_releases_the_video_file(qtbot, tmp_path):
    # A held media handle blocks move-to-trash on Windows, so closing must drop it.
    view = _view(qtbot, [(str(tmp_path / "c.mp4"), "video")])
    view.close()
    view._preview._player.setSource.assert_called_with(QUrl())


def test_releasing_a_condemned_file_lets_go_of_it(qtbot, tmp_path):
    clip = str(tmp_path / "c.mp4")
    view = _view(qtbot, [(clip, "video")])

    view.release_media([clip])

    assert view._preview.is_showing_any([clip]) is False


def test_releasing_another_file_leaves_the_show_alone(qtbot, tmp_path):
    kept = str(tmp_path / "kept.mp4")
    view = _view(qtbot, [(kept, "video")])

    view.release_media([str(tmp_path / "doomed.mp4")])

    assert view._preview.is_showing_any([kept]) is True


# --- the OSR2 drive target: the clip on screen ------------------------------

def test_osr2_drive_target_bundles_the_scripted_video(qtbot, tmp_path):
    vid = tmp_path / "c.mp4"
    write_funscript(funscript_path_for(vid), synthesize_actions(2.0, hz=1.0, loop=False))
    player = MagicMock()
    view = SlideshowView([(str(vid), "video")], player=player,
                         shuffle=lambda order: None)
    qtbot.addWidget(view)

    target = view.osr2_drive_target()

    assert target is not None
    path, tgt_player, actions = target
    assert path == str(vid) and tgt_player is player and actions


def test_osr2_drive_target_is_none_for_an_image(qtbot, tmp_path):
    view = _view(qtbot, [(_png(tmp_path / "p.png"), "image")])
    assert view.osr2_drive_target() is None


def test_osr2_drive_target_is_none_for_an_unscripted_video(qtbot, tmp_path):
    view = _view(qtbot, [(str(tmp_path / "c.mp4"), "video")])
    assert view.osr2_drive_target() is None


def test_stepping_re_aims_the_device(qtbot):
    view = _view(qtbot)
    changed = []
    view.media_changed.connect(lambda: changed.append(True))
    _press(view, Qt.Key.Key_Right)
    assert changed == [True]

# --- the hold a spoken request puts on the show -----------------------------


def test_a_request_holds_the_advance_and_says_so(qtbot):
    view = _view(qtbot, _KEYED)
    assert view._timer.isActive()  # an image, dwelling

    view.hold_for_request(True, "🎤 Request: no hat…")

    assert not view._timer.isActive()
    assert view._playlist.paused
    assert "Request" in view._note.text()


def test_releasing_the_hold_resumes_the_dwell(qtbot):
    view = _view(qtbot, _KEYED)
    view.hold_for_request(True, "🎤 Request…")

    view.hold_for_request(False)

    assert view._timer.isActive()
    assert not view._playlist.paused
    assert view._note.isHidden()


def test_the_slide_stays_put_while_a_request_is_being_said(qtbot):
    # The point of the hold: the request is about this slide, so the show must
    # not page on while the sentence is still being spoken.
    view = _view(qtbot, _KEYED)
    view.hold_for_request(True, "🎤 Request…")

    view._on_video_ended()  # the clip on screen ran out mid-sentence

    assert view.voice_target() == "id-a"


def test_releasing_the_hold_leaves_a_locked_slide_locked(qtbot):
    view = _view(qtbot, _KEYED)
    view._hold_current()  # the user locked this one
    view.hold_for_request(True, "🎤 Request…")

    view.hold_for_request(False)

    assert view._playlist.locked
    assert not view._timer.isActive()  # still held — by the lock, now


def test_a_request_targets_the_slide_on_screen(qtbot):
    view = _view(qtbot, _KEYED)
    assert view.voice_target() == "id-a"
    _press(view, Qt.Key.Key_Right)
    assert view.voice_target() == "id-b"


def test_a_finished_request_answers_in_the_corner(qtbot):
    view = _view(qtbot, _KEYED)
    view.note_request("🎤 dropped “a hat” — generating")
    assert "dropped" in view._note.text()
