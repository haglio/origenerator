"""SlideshowView — the one fullscreen Funestra: show, advance, lock, neighbors, keys.

Also everything the retired second full-screen viewer used to do on its own, which
this view now covers: paging a folder in order, stepping an image's versions,
following a generation that is still being made, and driving the OSR2 off the
clip on screen.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import NamedTuple

import pytest
from funestra.volume import VolumeHud
from PIL import Image
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QIcon, QKeyEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QWidget
from shared_ui.colors import AMBER, GREEN, RED, TEXT_PRIMARY
from shared_ui.icons import marked_text
from shared_ui.notice_shape import NOTICE_TOP_MARGIN

from origenerator.funscript import (
    synthesize_actions,
    write_funscript,
)
from origenerator.gui.inflight import InFlightItem, RunReading
from origenerator.gui.notice_overlay import ERROR, FAVORITE, HEARD_MARK, WARNING, NoticeOverlay
from origenerator.gui.slideshow_map import MapNeighbors, MapRow
from origenerator.gui.slideshow_pace import SlideshowPace
from origenerator.gui.slideshow_view import SlideshowView
from origenerator.gui.slideshow_wiring import HudFacts, SlideshowActions
from origenerator.gui.stylesheet import dress_application
from origenerator.slideshow import LIVE, Slide, SlideshowFilters, in_order
from tests import gestures
from tests.funestra_fakes import FakeEngine
from tests.marked_words import words
from tests.motion_doubles import FakeMotion
from tests.slideshow_hud_support import button_on_screen, speaker_on_screen, thumbnail_on_screen
from tests.slideshow_support import ahead, slides_named

_ITEMS = [("a.png", "image"), ("b.mp4", "video"), ("c.png", "image")]


def _png(path):
    Image.new("RGB", (16, 16), (20, 80, 160)).save(path, "PNG")
    return str(path)


def _png_bytes(color=(10, 120, 200)):
    """A streamed in-progress frame: encoded image bytes, no file on disk."""
    buf = BytesIO()
    Image.new("RGB", (32, 24), color).save(buf, "PNG")
    return buf.getvalue()


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _view(qtbot, items=_ITEMS, **kw):
    kw.setdefault("shuffle", lambda order: None)  # deterministic order for these tests
    view = SlideshowView(items, engine=FakeEngine(), clock=_Clock(), **_wired(kw))
    qtbot.addWidget(view)
    view.slideshow._timer.stop()  # read by hand (_settle), so a test says when
    return view


def _settle(view):
    """The slideshow reads its Funestra, as its poll does a moment later -- and
    once more, for whatever that reading sent it."""
    view.slideshow.tick()
    view.slideshow.tick()


def _engine(view):
    """The Funestras' engine the slideshow's Funestra runs on."""
    return view._pane._engine


def _media_on_screen(view) -> str:
    """The file the Funestra has up, or "" while a run's frames are up over it or
    it has let go of everything."""
    engine = _engine(view)
    if view.slideshow._frame_on_funestra is not None or engine.idle or engine.on_screen is None:
        return ""
    return str(engine.on_screen)


def _clip_up(view) -> bool:
    """Whether a clip, rather than a picture or a run's frames, is on screen."""
    return view.slideshow._clip_on_screen() is not None


def _runs_out(view):
    """The item on screen ran out -- a clip played through, or a picture's
    pace expired -- and the Funestra rolled onto what it had staged next, if
    anything; the slideshow follows a frame later."""
    _engine(view).run_out()
    view._pane.tick()
    view._pane.tick()
    _settle(view)


def _time_passes(view, seconds: float):
    view._clock.now += seconds
    view._pane.tick()
    view._pane.tick()
    _settle(view)


def _will_move_on(view) -> bool:
    return not view._paused and not view.slideshow._keeps()


def _wired(kw: dict) -> dict:
    """The slideshow takes its HUD facts and its gallery actions as two records;
    these cases name the facts and the actions flat, the way the words read."""
    facts = {k: kw.pop(k) for k in ("order_label", "favorite_ids", "enhanced_ids", "enhancing")
             if k in kw}
    if facts:
        kw["hud"] = HudFacts(**facts)
    acts = {k[3:]: kw.pop(k) for k in list(kw) if k.startswith("on_")}
    if acts:
        kw["actions"] = SlideshowActions(**acts)
    return kw


def _named(tmp_path, *names):
    return [(_png(tmp_path / f"{name}.png"), "image", name, None) for name in names]


def test_the_enhanced_switch_narrows_the_pass_and_keeps_the_slide_showing(qtbot, tmp_path):
    # A switch is a narrowing of what you are looking through, not a new slideshow:
    # taking the picture away as well would make the switch impossible to try.
    view = _view(qtbot, _named(tmp_path, "a", "b", "c"), enhanced_ids={"b", "c"})
    view.slideshow.slideshow_step(1)
    _settle(view)
    assert view.slideshow._set.playlist.current()[2] == "b"

    assert view.slideshow.toggle_enhanced_mode() is True

    assert view.slideshow.hud_enhanced_mode is True
    assert [item[2] for item in view.slideshow._set.playlist._items] == ["b", "c"]
    assert view.slideshow._set.playlist.current()[2] == "b"     # still the one on screen

    assert view.slideshow.toggle_enhanced_mode() is True     # and back to all of them
    assert view.slideshow.hud_enhanced_mode is False
    assert len(view.slideshow._set.playlist) == 3
    assert view.slideshow._set.playlist.current()[2] == "b"


def test_a_switch_that_takes_the_slide_away_moves_to_what_is_left(qtbot, tmp_path):
    view = _view(qtbot, _named(tmp_path, "a", "b", "c"), enhanced_ids={"b", "c"})
    assert view.slideshow._set.playlist.current()[2] == "a"

    view.slideshow.set_enhanced_mode(True)
    _settle(view)

    assert view.slideshow._set.playlist.current()[2] == "b"


def test_a_switch_that_would_leave_nothing_is_refused(qtbot, tmp_path):
    # An empty slideshow is not a mode: the button stays dark and the set stays whole.
    view = _view(qtbot, _named(tmp_path, "a", "b"))

    assert view.slideshow.set_enhanced_mode(True) is False

    assert view.slideshow.hud_enhanced_mode is False
    assert len(view.slideshow._set.playlist) == 2


def test_both_switches_together_keep_what_answers_both(qtbot, tmp_path):
    view = _view(qtbot, _named(tmp_path, "a", "b", "c"),
                 favorite_ids={"a", "b"}, enhanced_ids={"b", "c"})

    view.slideshow.toggle_favorites_filter()
    _settle(view)
    view.slideshow.toggle_enhanced_mode()
    _settle(view)

    assert [item[2] for item in view.slideshow._set.playlist._items] == ["b"]
    assert view.slideshow.clear_modes() is True              # the way out of both at once
    assert (view.slideshow.hud_favorites_filter, view.slideshow.hud_enhanced_mode) == (False, False)
    assert len(view.slideshow._set.playlist) == 3


def test_a_narrowed_slideshow_takes_in_only_what_passes_its_switches(qtbot, tmp_path):
    # The slideshow keeps up with the folder it plays; the switches decide that too,
    # or a narrowed slideshow would fill back up with the very items it left out.
    view = _view(qtbot, _named(tmp_path, "a", "b"), enhanced_ids={"a"})
    view.slideshow.set_enhanced_mode(True)
    _settle(view)

    view.slideshow.note_added(_png(tmp_path / "c.png"), "image", "c", None)                 # plain
    _settle(view)
    view.slideshow.note_added(_png(tmp_path / "d.png"), "image", "d", None, enhanced=True)  # enhanced
    _settle(view)

    assert sorted(item[2] for item in view.slideshow._set.playlist._items) == ["a", "d"]
    view.slideshow.clear_modes()
    _settle(view)
    assert sorted(item[2] for item in view.slideshow._set.playlist._items) == ["a", "b", "c", "d"]


def test_an_enhancement_landing_brings_its_item_into_an_enhanced_only_pass(qtbot, tmp_path):
    view = _view(qtbot, _named(tmp_path, "a", "b"), enhanced_ids={"a"})
    view.slideshow.set_enhanced_mode(True)
    _settle(view)
    assert [item[2] for item in view.slideshow._set.playlist._items] == ["a"]

    better = _png(tmp_path / "b_enhanced.png")
    view.slideshow.note_enhanced("b", better, "image")
    _settle(view)

    assert sorted(item[2] for item in view.slideshow._set.playlist._items) == ["a", "b"]
    assert next(item for item in view.slideshow._set.playlist._items if item[2] == "b")[0] == better
    view.slideshow.clear_modes()
    _settle(view)
    assert next(item for item in view.slideshow._set.playlist._items if item[2] == "b")[0] == better


def test_a_culled_slide_stays_gone_when_a_switch_comes_off(qtbot, tmp_path):
    view = _view(qtbot, _named(tmp_path, "a", "b", "c"), enhanced_ids={"a", "b"})
    view.slideshow.set_enhanced_mode(True)
    _settle(view)
    assert view.slideshow._set.playlist.current()[2] == "a"

    view.slideshow.cull()
    _settle(view)
    view.slideshow.clear_modes()
    _settle(view)

    assert sorted(item[2] for item in view.slideshow._set.playlist._items) == ["b", "c"]


def test_locking_a_slide_makes_it_a_favorite_the_switch_can_see(qtbot, tmp_path):
    # Down favorites the slide; the star readout and F-mode follow, not only the
    # database the gallery writes.
    favorite = []
    view = _view(qtbot, _named(tmp_path, "a", "b"), on_favorite=favorite.append)
    assert view.slideshow.hud_is_favorite is False

    view.slideshow.slideshow_toggle_lock()
    _settle(view)

    assert favorite == ["a"]
    assert view.slideshow.hud_is_favorite is True
    assert view.slideshow.set_favorites_filter(True) is True
    assert [item[2] for item in view.slideshow._set.playlist._items] == ["a"]


def test_reset_drops_both_switches(qtbot, tmp_path):
    view = _view(qtbot, _named(tmp_path, "a", "b", "c"),
                 favorite_ids={"a"}, enhanced_ids={"a"})
    view.slideshow.toggle_favorites_filter()
    _settle(view)
    view.slideshow.toggle_enhanced_mode()
    _settle(view)
    assert len(view.slideshow._set.playlist) == 1

    view.slideshow.reset_in_place()
    _settle(view)

    assert (view.slideshow.hud_favorites_filter, view.slideshow.hud_enhanced_mode) == (False, False)
    assert len(view.slideshow._set.playlist) == 3


def test_a_slideshow_following_a_running_generation_has_no_set_to_narrow(qtbot, tmp_path):
    # It is watching one thing being made; the frames are not a set to narrow.
    view = _following(qtbot)

    assert view.slideshow.set_enhanced_mode(True) is False

    assert view.slideshow._set.current_prompt_id() == "id-run"
    assert len(view.slideshow._set.playlist) == 1


def _press(view, key, modifiers=Qt.KeyboardModifier.NoModifier):
    """A key pressed at the slideshow the way a keyboard presses it: through its
    window, to whatever there has the focus."""
    if not view.isActiveWindow():
        view.show()
        view.activateWindow()
        QTest.qWaitForWindowActive(view)
    gestures.press_key(view, key, modifiers)


def _shift(view, key):
    _press(view, key, Qt.KeyboardModifier.ShiftModifier)


class _Arrows(NamedTuple):
    up: Qt.Key
    left: Qt.Key
    down: Qt.Key
    right: Qt.Key


_ARROW_KEYS_OR_WASD = pytest.mark.parametrize("arrows", [
    _Arrows(up=Qt.Key.Key_Up, left=Qt.Key.Key_Left, down=Qt.Key.Key_Down, right=Qt.Key.Key_Right),
    _Arrows(up=Qt.Key.Key_W, left=Qt.Key.Key_A, down=Qt.Key.Key_S, right=Qt.Key.Key_D),
], ids=["arrow keys", "WASD"])


def _fade(view):
    """What a flash's own timer does when it fires: it is a single shot, so it is
    no longer running by the time the note falls back to whatever the slideshow would
    otherwise be saying."""
    view._note_timer.stop()
    view._refresh_note()


def test_opens_on_the_first_item(qtbot):
    view = _view(qtbot)
    assert view.slideshow._set.playlist.current() == Slide("a.png", "image")
    assert _clip_up(view) is False


@_ARROW_KEYS_OR_WASD
def test_right_and_left_navigate(qtbot, arrows):
    view = _view(qtbot)
    _press(view, arrows.right)
    assert view.slideshow._set.playlist.current() == Slide("b.mp4", "video")
    assert _clip_up(view) is True
    _press(view, arrows.left)
    assert view.slideshow._set.playlist.current() == Slide("a.png", "image")


def test_a_finished_video_advances_to_the_next(qtbot):
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Right)          # -> the video
    _runs_out(view)                         # it played through
    assert view.slideshow._set.playlist.current() == Slide("c.png", "image")


def test_a_locked_video_replays_instead_of_advancing(qtbot):
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Right)          # -> the video
    _press(view, Qt.Key.Key_Down)           # lock it: repeat-one, as Fun Time's is
    _runs_out(view)
    assert view.slideshow._set.playlist.current() == Slide("b.mp4", "video")  # stayed put
    assert view.slideshow.locked


@_ARROW_KEYS_OR_WASD
def test_down_toggles_the_lock(qtbot, arrows):
    view = _view(qtbot)
    _press(view, arrows.down)
    assert view.slideshow.locked
    assert _engine(view).loop_file is True
    _press(view, arrows.down)
    assert not view.slideshow.locked
    assert _engine(view).loop_file is False


def test_stepping_away_releases_the_lock(qtbot):
    # Right off a locked slide is the way out of the lock — no second Down needed,
    # matching Fun Time's next/prev.
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Down)
    _press(view, Qt.Key.Key_Right)
    assert not view.slideshow.locked
    assert view.slideshow._set.playlist.current() == Slide("b.mp4", "video")

    _press(view, Qt.Key.Key_Down)
    _press(view, Qt.Key.Key_Left)           # and back the other way
    assert not view.slideshow.locked
    assert view.slideshow._set.playlist.current() == Slide("a.png", "image")


def test_the_consoles_transport_releases_the_lock_too(qtbot):
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Down)
    view.slideshow.slideshow_step(1)                     # the console's transport, not the key
    _settle(view)
    assert not view.slideshow.locked
    assert view.slideshow._set.playlist.current() == Slide("b.mp4", "video")


def test_a_new_set_played_into_an_open_slideshow_starts_it_over_on_that_set(qtbot):
    # Standalone the monitor holds one slideshow, so a second set asked for while
    # this one is up arrives here rather than in a window of its own: it plays
    # the new set from the top, the way a slideshow opened on it would.
    view = _view(qtbot, [("a.png", "image", "id-a")])

    view.slideshow.play([("b.png", "image", "id-b"), ("c.png", "image", "id-c")],
              shuffle=in_order)

    assert view.slideshow._set.playlist.current() == Slide("b.png", "image", "id-b")
    assert [slide.path for slide in view.slideshow._set.playlist.in_play_order()] == ["b.png", "c.png"]


def test_a_new_set_played_in_drops_the_switches_the_last_one_left_on(qtbot):
    # A fresh slideshow opens with neither switch on, so a re-pointed one does too:
    # the favorites filter belonged to the set it was narrowing, and carrying
    # it over would hide most of a set nobody had narrowed.
    view = _view(qtbot, [("a.png", "image", "id-a")], favorite_ids={"id-a"})
    view.slideshow.toggle_favorites_filter()
    _settle(view)
    assert view.slideshow.hud_favorites_filter

    view.slideshow.play([("b.png", "image", "id-b")], shuffle=in_order)
    _settle(view)

    assert not view.slideshow.hud_favorites_filter
    assert not view.slideshow.hud_enhanced_mode


def test_culling_releases_the_lock(qtbot):
    items = [("a.png", "image", "id-a"), ("b.png", "image", "id-b")]
    view = SlideshowView(items, engine=FakeEngine(), shuffle=lambda order: None,
                         actions=SlideshowActions(delete=lambda prompt_id: None))
    qtbot.addWidget(view)
    _press(view, Qt.Key.Key_Down)
    _press(view, Qt.Key.Key_Up)             # the locked slide is the one condemned
    assert not view.slideshow.locked
    assert _will_move_on(view)   # so the rest keeps rotating


def test_space_drives_the_shared_motion_not_the_lock(qtbot):
    # Space belongs to the app-global OSR2 motion everywhere; locking the
    # slideshow is Down. The device rides on the slideshow's one panel.
    motion = FakeMotion()
    view = SlideshowView(_ITEMS, engine=FakeEngine(), shuffle=lambda order: None,
                         motion=motion)
    qtbot.addWidget(view)
    assert view.hud_device is not None  # the device half of the panel is there
    _press(view, Qt.Key.Key_Space)
    assert ("toggle", True) in motion.calls
    assert not view.slideshow.locked


def test_esc_leaves_the_slideshow_up(qtbot):
    view = _view(qtbot)
    view.show()
    _press(view, Qt.Key.Key_Escape)
    assert view.isVisible()


@_ARROW_KEYS_OR_WASD
def test_up_deletes_the_current_item_and_advances(qtbot, arrows):
    deleted = []
    items = [("a.png", "image", "id-a"), ("b.png", "image", "id-b"),
             ("c.png", "image", "id-c")]
    view = SlideshowView(items, engine=FakeEngine(), shuffle=lambda order: None,
                         actions=SlideshowActions(delete=deleted.append))
    qtbot.addWidget(view)
    assert view.slideshow._set.playlist.current()[2] == "id-a"

    _press(view, arrows.up)

    assert deleted == ["id-a"]                     # culled via the delete act
    assert len(view.slideshow._set.playlist) == 2
    assert view.slideshow._set.playlist.current()[2] == "id-b"   # advanced to the next


def test_enter_leaves_for_the_shown_items_folder(qtbot):
    items = [("a.png", "image", "id-a"), ("b.png", "image", "id-b")]
    view = SlideshowView(items, engine=FakeEngine(), shuffle=lambda order: None)
    qtbot.addWidget(view)
    view.show()
    opened = []
    view.slideshow.open_requested.connect(opened.append)

    _press(view, Qt.Key.Key_Return)

    assert opened == ["id-a"]     # the gallery is handed the item on screen
    assert not view.isVisible()   # and the slideshow is out of the way


def _collection_view(qtbot):
    """A two-item slideshow whose handovers are recorded — the ways out of a slideshow."""
    items = [("a.png", "image", "id-a"), ("b.png", "image", "id-b")]
    view = SlideshowView(items, engine=FakeEngine(), shuffle=lambda order: None)
    qtbot.addWidget(view)
    _on_screen_wearing_its_panel(qtbot, view)
    opened = []
    view.slideshow.open_requested.connect(opened.append)
    return view, opened


def _leave_by_double_clicking_the_picture(qtbot, view):
    gestures.double_click(view._pane._window, _on_the_picture(view))
    qtbot.waitUntil(lambda: not view.isVisible())


def test_ending_a_slideshow_on_a_locked_slide_hands_that_slide_over(qtbot):
    # Locking says "this is the one", so ending the slideshow there means the same
    # thing Enter does: the gallery lands on that item rather than back wherever
    # it was when the slideshow started.
    view, opened = _collection_view(qtbot)
    _press(view, Qt.Key.Key_Right)  # onto the second slide
    _press(view, Qt.Key.Key_Down)   # lock it

    _leave_by_double_clicking_the_picture(qtbot, view)

    assert opened == ["id-b"]


def test_ending_a_slideshow_on_an_unlocked_slide_hands_that_slide_over(qtbot):
    # The picture on screen when you leave is the one you want to find afterwards.
    view, opened = _collection_view(qtbot)
    on_screen = view.slideshow._set.playlist.current()[2]

    _leave_by_double_clicking_the_picture(qtbot, view)

    assert opened == [on_screen]


def test_enter_on_a_locked_slide_hands_it_over_once(qtbot):
    # Enter and the lock name the same item, and the handover is closeEvent's, so
    # the gallery is asked to go there once rather than twice.
    view, opened = _collection_view(qtbot)
    _press(view, Qt.Key.Key_Down)

    _press(view, Qt.Key.Key_Return)

    assert opened == ["id-a"]


def test_closing_a_slideshow_twice_hands_over_once(qtbot):
    # Qt sends a close event to an already-closed window too.
    view, opened = _collection_view(qtbot)
    _press(view, Qt.Key.Key_Down)

    view.close()
    view.close()

    assert opened == ["id-a"]


def test_culling_the_last_slide_hands_nothing_over(qtbot):
    # The slideshow empties and closes itself, and the item it ended on is in the bin —
    # nowhere to land.
    deleted = []
    view = SlideshowView([("a.png", "image", "id-a")], engine=FakeEngine(),
                         shuffle=lambda order: None, actions=SlideshowActions(delete=deleted.append))
    qtbot.addWidget(view)
    view.show()
    opened = []
    view.slideshow.open_requested.connect(opened.append)
    _press(view, Qt.Key.Key_Down)  # locked, then condemned anyway

    _press(view, Qt.Key.Key_Up)

    assert deleted == ["id-a"]
    assert opened == []


# --- a generation that lands while the slideshow runs -----------------------

def test_a_generation_that_lands_joins_the_slideshow(qtbot):
    # Watching a folder that is still generating is the case this is for: the
    # loop's next item joins the set and comes up next, without disturbing the
    # slide being looked at.
    view = _view(qtbot, [("a.png", "image", "id-a")])

    view.slideshow.note_added("new.png", "image", "id-new", None)
    _settle(view)

    assert len(view.slideshow._set.playlist) == 2
    assert view.slideshow._set.playlist.current()[2] == "id-a"
    assert ahead(view.slideshow._set.playlist, 1)[2] == "id-new"


def test_a_generation_already_playing_does_not_join_twice(qtbot):
    view = _view(qtbot, [("a.png", "image", "id-a")])

    view.slideshow.note_added("a.png", "image", "id-a", None)
    _settle(view)

    assert len(view.slideshow._set.playlist) == 1


def test_an_arrival_is_handed_to_the_funestra_to_play_next(qtbot, tmp_path):
    # The Funestra walks the pass by itself, so a slideshow that was alone until now
    # has to hand it the pass with the arrival in it.
    a = _png(tmp_path / "a.png")
    view = _view(qtbot, [(a, "image", "id-a")])
    assert _engine(view).staged_next == Path(a)  # alone, it has only itself to follow

    view.slideshow.note_added("new.mp4", "video", "id-new", _png(tmp_path / "new_thumb.png"))
    _settle(view)

    assert _engine(view).staged_next == Path("new.mp4")


# --- locking a slide asks for it to be enhanced -----------------------------

_KEYED = [("a.png", "image", "id-a"), ("b.png", "image", "id-b")]


def test_locking_a_slide_asks_for_it_to_be_enhanced(qtbot):
    # Stopping on a picture is the gesture that says you want it, so it is also
    # the one that asks for the better version.
    asked = []
    view = _view(qtbot, _KEYED, actions=SlideshowActions(enhance=lambda pid: asked.append(pid) or True))

    _press(view, Qt.Key.Key_Down)

    assert asked == ["id-a"]
    assert view.slideshow.locked
    assert view.slideshow.hud_item_note == "Enhancement queued"


def test_locking_a_slide_whose_enhancement_is_waiting_still_asks_so_it_goes_first(qtbot):
    asked = []
    view = _view(qtbot, _KEYED, actions=SlideshowActions(enhance=lambda pid: asked.append(pid) or False))
    view.slideshow.note_enhancing({"id-a": "queued"})
    _settle(view)

    _press(view, Qt.Key.Key_Down)

    assert asked == ["id-a"]


def test_a_locked_slideshow_names_the_generation_it_is_locked_on(qtbot):
    view = _view(qtbot, _KEYED)
    assert view.slideshow.locked_on is None

    _press(view, Qt.Key.Key_Down)

    assert view.slideshow.locked_on == "id-a"


def test_releasing_the_lock_asks_for_nothing(qtbot):
    asked = []
    view = _view(qtbot, _KEYED, actions=SlideshowActions(enhance=lambda pid: asked.append(pid) or True))
    _press(view, Qt.Key.Key_Down)   # lock
    _press(view, Qt.Key.Key_Down)   # release
    assert asked == ["id-a"]        # only the stop asked, not the resume


def test_the_gallery_can_refuse_and_nothing_is_claimed(qtbot):
    # It already has a version at these settings, or it is a video: the refusal
    # comes from the side that holds the settings, and the corner stays quiet.
    view = _view(qtbot, _KEYED, actions=SlideshowActions(enhance=lambda pid: False))
    _press(view, Qt.Key.Key_Down)
    assert view.slideshow.hud_item_note == ""


def test_the_loop_key_with_nothing_to_loop_is_the_lock_and_always_enhances(qtbot):
    # E and Home are the loop key, on both of the keys a session gives its two
    # satellites; with nothing on either axis of the map the press is the
    # lock — Down's whole gesture, the enhancement included, with no switch to
    # turn that off any more — and the next press lets go, so the key is never
    # a trap.
    asked = []
    view = _view(qtbot, _KEYED, actions=SlideshowActions(enhance=lambda pid: asked.append(pid) or True))

    _press(view, Qt.Key.Key_E)
    assert view.slideshow.locked and asked == ["id-a"]
    assert words(view._note) == "Locked"

    _press(view, Qt.Key.Key_Home)
    assert not view.slideshow.locked
    assert words(view._note) == "Unlocked"


def _around(prompt_id):
    if prompt_id != "id-a":
        return MapNeighbors()
    other_act = Slide("c.png", "image", "id-c")
    return MapNeighbors(seeds=(Slide("b.png", "image", "id-b"),),
                        column=(MapRow(other_act, "dawn"),), label="fox",
                        group=(other_act,))


def test_a_cull_that_leaves_one_picture_in_the_row_locks_it(qtbot):
    """A row worn down to one picture is that picture over and over, which is
    the lock — so the cull that wore it down ends the loop and locks what is
    left, as a satellite's does.  Only the lock: none of what a pressed lock
    also does, since nobody pressed one."""
    asked, starred, opened = [], [], []
    view = _view(qtbot, _KEYED,
                 actions=SlideshowActions(neighbors=_around, delete=lambda prompt_id: None,
                                          favorite=starred.append, lock=opened.append,
                                          enhance=lambda prompt_id: asked.append(prompt_id) or True))
    _press(view, Qt.Key.Key_E)                   # loop the seed row: id-a, id-b

    view.slideshow.cull()                                  # weird the picture on screen
    _settle(view)

    assert view.slideshow.locked is True
    assert view.slideshow.hud_map().loop == ""
    assert (asked, starred, opened) == ([], [], [])


def test_a_picture_taken_away_leaves_the_map_of_the_row_it_was_playing(qtbot):
    """While a row is playing round, the map is drawn from the row as it was
    dealt — so the picture just taken away has to leave that row too, or it goes
    on being drawn and is merely skipped when the row comes round again."""
    deleted = []
    view = _view(qtbot, _KEYED,
                 actions=SlideshowActions(neighbors=_around, delete=deleted.append))
    _press(view, Qt.Key.Key_E)                   # play the seed row round: id-a, id-b

    view.slideshow.cull()                                  # weird the picture on screen
    _settle(view)

    assert deleted == ["id-a"]
    assert "id-a" not in [cell.prompt_id for cell in view.slideshow.hud_map().cells()]


def test_a_loop_button_for_a_row_of_one_picture_locks_it_instead(qtbot):
    """A row holding only the picture on screen cannot be looped, and the press
    still means "this one" — so it locks the picture, the way a satellite's loop
    button locks a clip whose group holds only it, rather than refusing."""
    view = _view(qtbot, _KEYED)                  # no neighbors: every row is one picture

    view.slideshow.slideshow_loop("seed")
    _settle(view)

    assert view.slideshow.locked is True
    assert words(view._note) == "Locked"


def test_the_loop_key_loops_the_seed_row_then_the_config_column_then_stops(qtbot):
    browsing = [*_KEYED, ("z.png", "image", "id-z")]     # more than one row, so nothing loops yet
    view = _view(qtbot, browsing, actions=SlideshowActions(neighbors=_around))

    _press(view, Qt.Key.Key_E)
    assert view.slideshow.hud_map().loop == "seed"
    assert [item[2] for item in view.slideshow._set.playlist._items] == ["id-a", "id-b"]
    assert words(view._note) == "Looping seeds: 2"

    _press(view, Qt.Key.Key_E)
    assert view.slideshow.hud_map().loop == "action"
    assert [item[2] for item in view.slideshow._set.playlist._items] == ["id-a", "id-c"]

    _press(view, Qt.Key.Key_E)
    assert view.slideshow.hud_map().loop == ""
    assert [item[2] for item in view.slideshow._set.playlist._items] == ["id-a", "id-b", "id-z"]  # its own set
    assert words(view._note) == "Loop off"


def test_the_forward_step_out_of_a_row_down_to_one_picture_ends_the_loop(qtbot):
    """A cull can leave the row holding only the picture on screen, and a row of
    one has nowhere to step: the forward step ends the loop and puts up what the
    set plays next, the way it steps out of a lock."""
    browsing = [*_KEYED, ("z.png", "image", "id-z")]
    view = _view(qtbot, browsing, actions=SlideshowActions(neighbors=_around))
    _press(view, Qt.Key.Key_E)                   # the seed row is the pass: id-a, id-b
    view.slideshow._set.playlist.drop("id-b")                  # culled down to the picture on screen
    shown = _put_up(view)

    view.slideshow.slideshow_step(1)
    _settle(view)

    assert view.slideshow.hud_map().loop == ""
    assert shown == ["id-b"]


def test_the_forward_step_in_a_row_with_somewhere_to_go_stays_in_the_loop(qtbot):
    view = _view(qtbot, [*_KEYED, ("z.png", "image", "id-z")],
                 actions=SlideshowActions(neighbors=_around))
    _press(view, Qt.Key.Key_E)                   # the seed row is the pass: id-a, id-b

    view.slideshow.slideshow_step(1)
    _settle(view)

    assert view.slideshow.hud_map().loop == "seed"
    assert view.slideshow._set.current_prompt_id() == "id-b"


def test_the_back_step_in_a_row_down_to_one_picture_leaves_it_looping(qtbot):
    """Only the forward step is the way out, as on a Funestra: back is the row's
    own step the other way, and what it finds in a row of one is that picture."""
    view = _view(qtbot, [*_KEYED, ("z.png", "image", "id-z")],
                 actions=SlideshowActions(neighbors=_around))
    _press(view, Qt.Key.Key_E)
    view.slideshow._set.playlist.drop("id-b")

    view.slideshow.slideshow_step(-1)
    _settle(view)

    assert view.slideshow.hud_map().loop == "seed"


def _put_up(view) -> list:
    shown = []
    view.slideshow.media_changed.connect(lambda: shown.append(view.slideshow._set.playlist.current()[2]))
    return shown


def _acts(prompt_ids):
    named_for = {"id-a": "Source image, alpha", "id-b": "beta"}
    return {prompt_id: named_for.get(prompt_id, "") for prompt_id in prompt_ids}


def test_a_rows_button_narrows_the_slideshow_to_that_act_without_redrawing_what_shows_it(qtbot):
    view = _view(qtbot, _KEYED, actions=SlideshowActions(acts=_acts))
    shown = _put_up(view)

    view.slideshow.slideshow_filter("source_image,_alpha")
    _settle(view)

    assert (view.slideshow.hud_act_filter, view.slideshow.pass_size()) == ("source image, alpha", 1)
    assert shown == []
    assert words(view._note) == "Filter: 'source image, alpha' (1)"


def test_a_filter_past_the_slide_on_screen_puts_up_what_is_left(qtbot):
    view = _view(qtbot, _KEYED, actions=SlideshowActions(acts=_acts))
    shown = _put_up(view)

    view.slideshow.slideshow_filter("beta")
    _settle(view)

    assert shown == ["id-b"]


def test_an_act_nothing_here_shows_says_so_and_moves_nothing(qtbot):
    view = _view(qtbot, _KEYED, actions=SlideshowActions(acts=_acts))
    shown = _put_up(view)

    view.slideshow.slideshow_filter("gamma")
    _settle(view)

    assert (shown, view.slideshow.hud_act_filter) == ([], "")
    assert words(view._note) == "Filter: no matches for 'gamma'"


def test_filter_said_of_its_side_narrows_to_what_the_item_on_screen_is_named_for(qtbot):
    view = _view(qtbot, _KEYED, actions=SlideshowActions(acts=_acts))

    view.slideshow.slideshow_filter_to_the_act_on_screen()
    _settle(view)

    assert (view.slideshow.hud_act_filter, view.slideshow.pass_size()) == ("source image, alpha", 1)
    assert words(view._note) == "Filter: 'source image, alpha' (1)"


def test_filter_said_over_an_item_named_for_no_act_says_so(qtbot):
    view = _view(qtbot, _KEYED)

    view.slideshow.slideshow_filter_to_the_act_on_screen()
    _settle(view)

    assert (view.slideshow.hud_act_filter, words(view._note)) == ("", "No act for this one")


def test_clearing_the_filters_lifts_the_act_filter_with_the_other_two(qtbot):
    view = _view(qtbot, _KEYED, actions=SlideshowActions(acts=_acts))
    view.slideshow.slideshow_filter("beta")
    _settle(view)

    assert view.slideshow.clear_modes() is True

    assert (view.slideshow.hud_act_filter, view.slideshow.pass_size()) == ("", 2)


def test_a_walk_along_the_map_puts_the_next_cell_up(qtbot):
    view = _view(qtbot, _KEYED, actions=SlideshowActions(neighbors=_around))
    shown = _put_up(view)

    view.slideshow.slideshow_nav("right")
    _settle(view)
    view.slideshow.show_item("a.png")
    _settle(view)
    view.slideshow.slideshow_nav("down")
    _settle(view)

    assert shown == ["id-b", "id-a", "id-c"]


def _a_column_of_two(prompt_id):
    if prompt_id != "id-a":
        return MapNeighbors()
    dawn, dusk = Slide("c.png", "image", "id-c"), Slide("d.png", "image", "id-d")
    return MapNeighbors(column=(MapRow(dawn, "dawn"), MapRow(dusk, "dusk")), label="fox",
                        group=(dawn, dusk))


@_ARROW_KEYS_OR_WASD
def test_shift_down_and_up_walk_the_maps_column_as_a_sessions_map_keys_do(qtbot, arrows):
    deleted = []
    view = _view(qtbot, _KEYED,
                 actions=SlideshowActions(neighbors=_a_column_of_two, delete=deleted.append))
    shown = _put_up(view)

    _shift(view, arrows.down)
    view.slideshow.show_item("a.png")
    _settle(view)
    _shift(view, arrows.up)

    assert shown == ["id-c", "id-a", "id-d"]
    assert (deleted, view.slideshow.locked) == ([], False)


def test_entering_a_loop_lets_go_of_a_locked_slide_as_a_funestra_does(qtbot):
    view = _view(qtbot, _KEYED, actions=SlideshowActions(neighbors=_around))
    _press(view, Qt.Key.Key_Down)                 # lock the slide on screen
    assert view.slideshow.locked

    view.slideshow.slideshow_loop("seed")
    _settle(view)
    _runs_out(view)                               # the slide that was locked runs out

    assert view.slideshow.locked is False
    assert view.slideshow._set.playlist.current()[2] == "id-b"  # and the loop moves on to its next seed


def test_a_folder_played_as_a_slideshow_opens_with_its_seed_loop_lit(qtbot):
    """The pictures of one folder are one configuration's seeds, so playing the
    folder is looping that row — and the map's loop light says so from the start."""
    view = _view(qtbot, _KEYED, actions=SlideshowActions(neighbors=_around))

    assert view.slideshow.hud_map().loop == "seed"

    view.slideshow.slideshow_loop("")                            # the lit button, pressed
    _settle(view)
    assert view.slideshow.hud_map().loop == ""


def _seeds_only(prompt_id):
    """A folder's row and nothing else made of it — so the loop key's next stop
    is off rather than the act column."""
    return (MapNeighbors(seeds=(Slide("b.png", "image", "id-b"),), label="fox")
            if prompt_id == "id-a" else MapNeighbors())


def test_taking_the_loop_off_a_folder_slideshow_asks_the_gallery_for_the_library(qtbot):
    widened = []
    view = _view(qtbot, _KEYED, actions=SlideshowActions(
        neighbors=_seeds_only, browse_all=lambda slideshow: widened.append(slideshow) or True))

    view.slideshow.slideshow_loop("")
    _settle(view)

    assert widened == [view.slideshow]
    assert words(view._note) == "Loop off"


def test_the_loop_key_off_a_folder_slideshow_leaves_the_folder_in_one_press(qtbot):
    widened = []
    view = _view(qtbot, _KEYED, actions=SlideshowActions(
        neighbors=_seeds_only, browse_all=lambda slideshow: widened.append(slideshow) or True))

    _press(view, Qt.Key.Key_Home)

    assert widened == [view.slideshow]
    assert words(view._note) == "Loop off"


def test_up_over_a_favorite_takes_the_star_back_rather_than_the_picture(qtbot):
    # The Funestras' "weird": a favorite loses its star and the slideshow moves on;
    # only a picture wearing no star is condemned — so locking a slide, which
    # stars it, takes two presses of Up to undo all the way.
    unfavorited, deleted = [], []
    view = _view(qtbot, _KEYED, favorite_ids={"id-a"},
                 actions=SlideshowActions(unfavorite=unfavorited.append, delete=deleted.append))

    _press(view, Qt.Key.Key_Up)

    assert (unfavorited, deleted) == (["id-a"], [])
    assert view.slideshow._set.playlist.current()[2] == "id-b"    # moved on
    assert len(view.slideshow._set.playlist) == 2                  # and still in the set
    assert view.slideshow.hud_is_favorite is False

    view.slideshow.slideshow_step(-1)
    _settle(view)
    _press(view, Qt.Key.Key_Up)                     # no star left to take back

    assert deleted == ["id-a"]


def test_a_slide_whose_run_is_still_in_the_line_says_queued_not_enhancing(qtbot):
    # Locking several slides sends out several runs and ComfyUI takes them one at
    # a time, so a slide the slideshow comes back around to is usually still waiting.
    view = _view(qtbot, _KEYED, actions=SlideshowActions(enhance=lambda pid: True))
    _press(view, Qt.Key.Key_Down)        # ask for this one
    _press(view, Qt.Key.Key_Down)        # let go, so the slideshow can move
    _press(view, Qt.Key.Key_Right)
    _press(view, Qt.Key.Key_Down)        # and ask for the next

    view.slideshow.note_enhancing({"id-a": "running", "id-b": "queued"})
    _settle(view)

    assert view.slideshow.hud_item_note == "Enhancement queued"
    _press(view, Qt.Key.Key_Down)        # let go
    _press(view, Qt.Key.Key_Left)        # back to the one being made
    assert view.slideshow.hud_item_note == "Enhancing…"


def test_the_note_follows_the_run_from_the_line_onto_the_gpu(qtbot):
    view = _view(qtbot, _KEYED, actions=SlideshowActions(enhance=lambda pid: True))
    _press(view, Qt.Key.Key_Down)
    assert view.slideshow.hud_item_note == "Enhancement queued"

    view.slideshow.note_enhancing({"id-a": "running"})
    _settle(view)

    assert view.slideshow.hud_item_note == "Enhancing…"


def test_a_run_of_an_item_this_slideshow_never_asked_about_is_named_all_the_same(qtbot):
    view = _view(qtbot, _KEYED)
    view.slideshow.note_enhancing({"id-a": "running"})
    _settle(view)
    assert view.slideshow.hud_item_note == "Enhancing…"
    assert view._note.isHidden()


def test_a_status_arriving_mid_sentence_does_not_wipe_a_spoken_answer(qtbot):
    view = _view(qtbot, _KEYED, actions=SlideshowActions(enhance=lambda pid: True))
    view.slideshow.note_voice_run("id-a", "fixing teeth…")

    view.slideshow.note_enhancing({"id-a": "running"})
    _settle(view)

    assert "fixing teeth" in words(view._note)
    assert view.slideshow.hud_item_note == "Enhancing…"


def test_the_enhanced_version_replaces_the_slide_when_it_lands(qtbot, tmp_path):
    view = _view(qtbot, _KEYED, actions=SlideshowActions(enhance=lambda pid: True))
    _press(view, Qt.Key.Key_Down)
    better = _png(tmp_path / "a_enhanced.png")

    view.slideshow.note_enhanced("id-a", better)
    _settle(view)

    assert view.slideshow._set.playlist.current()[0] == better
    assert view.slideshow.hud_item_note == ""


def test_an_enhancement_that_lands_after_paging_on_still_upgrades_the_item(
        qtbot, tmp_path):
    # It arrives minutes later, by which time the slideshow has moved — and the slideshow
    # plays a set fixed when it opened, so an arrival dropped for being late
    # would replay the pre-enhance file every pass from here on.
    view = _view(qtbot, _KEYED, actions=SlideshowActions(enhance=lambda pid: True))
    _press(view, Qt.Key.Key_Down)
    _press(view, Qt.Key.Key_Right)
    better = _png(tmp_path / "a_enhanced.png")

    view.slideshow.note_enhanced("id-a", better)
    _settle(view)

    assert view.slideshow._set.playlist.current()[0] == "b.png"   # the slide on screen is left alone
    _press(view, Qt.Key.Key_Left)                   # and a comes round upgraded
    assert view.slideshow._set.playlist.current()[0] == better


def test_an_enhancement_of_another_folders_item_changes_nothing(qtbot, tmp_path):
    # Every landed enhancement is offered to every open slideshow; this one belongs
    # to a folder this slideshow isn't playing.
    view = _view(qtbot, _KEYED, actions=SlideshowActions(enhance=lambda pid: True))

    view.slideshow.note_enhanced("id-elsewhere", _png(tmp_path / "other.png"))
    _settle(view)

    assert [item[0] for item in view.slideshow._set.playlist._items] == ["a.png", "b.png"]


def test_the_upgraded_item_is_drawn_on_the_map_as_its_new_still(qtbot, tmp_path):
    # An item is drawn small on the map while another is on screen; the
    # thumbnail it arrived with is of the version the swap just retired.
    view = _view(qtbot, _KEYED, actions=SlideshowActions(enhance=lambda pid: True))
    better_thumb = _png(tmp_path / "b_enhanced_thumb.png")

    view.slideshow.note_enhanced("id-b", _png(tmp_path / "b_enhanced.png"),
                       still=better_thumb)

    assert [item.still for item in view.slideshow._set.playlist.items if item.prompt_id == "id-b"] == [better_thumb]


def test_a_slideshow_with_no_enhancer_still_locks_on_down(qtbot):
    view = _view(qtbot, _KEYED)     # nothing wired to enhance with
    _press(view, Qt.Key.Key_Down)
    assert view.slideshow.locked
    assert view.slideshow.hud_item_note == ""


def test_a_spoken_answer_is_a_notice_across_the_top(qtbot):
    view = _view(qtbot, _KEYED)
    view.resize(800, 600)

    view.slideshow.note_voice_command("next")

    note = view._note.geometry()
    assert note.top() == NOTICE_TOP_MARGIN
    assert abs(note.center().x() - view.width() // 2) <= 1


def test_a_press_is_answered_plain_and_a_spoken_word_after_the_mic(qtbot):
    view = _view(qtbot, _KEYED)

    _press(view, Qt.Key.Key_E)
    assert (view._note.textFormat(), view._note.text()) == (Qt.TextFormat.PlainText, "Locked")

    view.slideshow.note_voice_command("next")
    assert view._note.text() == marked_text(HEARD_MARK, "next", color=TEXT_PRIMARY,
                                            size=view._note.fontMetrics().height())


def test_what_is_being_made_of_the_slide_is_no_notice_across_the_top(qtbot):
    view = _view(qtbot, _KEYED, actions=SlideshowActions(enhance=lambda pid: True))
    _press(view, Qt.Key.Key_Down)
    _fade(view)

    view.slideshow.note_enhancing({"id-a": "running"})
    _settle(view)

    assert view._note.isHidden()


def test_the_notice_wears_the_color_of_what_it_says(qtbot):
    # Red only for an error, yellow for a warning, green for the favorites, white
    # for the rest: the colors Fun Time's own notices read in, since this is
    # the same overlay.
    host = QWidget()
    qtbot.addWidget(host)
    notice = NoticeOverlay(host)

    notice.say("a plain line")
    assert TEXT_PRIMARY.name() in notice.styleSheet()
    notice.say("nothing to do", kind=WARNING)
    assert AMBER.name() in notice.styleSheet()
    notice.say("it broke", kind=ERROR)
    assert RED.name() in notice.styleSheet()
    notice.say("starred", kind=FAVORITE)
    assert GREEN.name() in notice.styleSheet()


# --- the queue, which rides on the one panel this view wears -----------------

def _inflight(**kw):
    kw.setdefault("key", "j1")
    kw.setdefault("caption", "Alpha Workflow › a paper kite")
    kw.setdefault("status", "queued")
    kw.setdefault("reveal", lambda: None)
    reading = {k: kw.pop(k) for k in list(kw) if k in ("status", "frame", "progress", "pass_progress", "stage", "started_at", "typical_seconds")}
    return InFlightItem(reading=RunReading(**reading), **kw)


def test_the_view_holds_what_is_in_flight_for_its_panel(qtbot):
    # The lower strip that normally carries the line is under this view.
    view = _view(qtbot)

    view.set_queue([_inflight(status="running", typical_seconds=30, job_kind="Image"),
                    _inflight(key="j2", typical_seconds=600, job_kind="Video")], 3)

    items, foreign = view.hud_queue
    assert [item.key for item in items] == ["j1", "j2"]
    assert foreign == 3


def test_a_row_dragged_down_the_line_is_re_listed_before_the_queue_agrees(qtbot):
    # The queue's own answer is a poll away, and a row that springs back to
    # where it was reads as a failure.
    asked = []
    view = _view(qtbot, actions=SlideshowActions(requeue=asked.append))
    view.set_queue([_inflight(), _inflight(key="j2"), _inflight(key="j3")])

    view.requeue(["j1", "j3", "j2"])

    assert [item.key for item in view.hud_queue[0]] == ["j1", "j3", "j2"]
    assert asked == [["j1", "j3", "j2"]]


def test_clearing_another_apps_work_goes_back_to_the_gallery(qtbot):
    cleared = []
    view = _view(qtbot, actions=SlideshowActions(clear_queue=lambda: cleared.append(True)))

    view.clear_foreign_queue()

    assert cleared == [True]


def test_start_now_goes_back_to_the_gallery(qtbot):
    started = []
    view = _view(qtbot, actions=SlideshowActions(start_now=lambda: started.append(True)))

    view.start_now()

    assert started == [True]


# --- locking also stars, and a double-click leaves ---------------------------

def test_locking_favorites_the_item_on_screen(qtbot):
    # Locking a slide is how the user says this one is worth keeping; having said
    # it once they should not have to say it again in a second way.
    favorite = []
    items = [("a.png", "image", "gen-a", None), ("b.png", "image", "gen-b", None)]
    view = _view(qtbot, items=items, actions=SlideshowActions(favorite=favorite.append))

    _press(view, Qt.Key.Key_Down)

    assert view.slideshow.locked
    assert favorite == ["gen-a"]


def test_letting_go_of_the_lock_does_not_unfavorite(qtbot):
    favorite = []
    items = [("a.png", "image", "gen-a", None)]
    view = _view(qtbot, items=items, actions=SlideshowActions(favorite=favorite.append))

    _press(view, Qt.Key.Key_Down)
    _press(view, Qt.Key.Key_Down)

    assert not view.slideshow.locked
    assert favorite == ["gen-a"]  # favorited once, on the way in


def test_a_slideshow_without_a_favoriter_still_locks(qtbot):
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Down)
    assert view.slideshow.locked


# --- the transport a spoken word drives, saying which way rather than flipping

def test_asking_for_a_lock_locks_and_asking_again_changes_nothing(qtbot):
    # Someone talking to a picture is asking for a state, not for the other one,
    # and cannot see the counter's padlock to know which the flip would give.
    favorite = []
    items = [("a.png", "image", "gen-a", None), ("b.png", "image", "gen-b", None)]
    view = _view(qtbot, items=items, actions=SlideshowActions(favorite=favorite.append))

    assert view.slideshow.set_locked(True) is True
    assert view.slideshow.locked and favorite == ["gen-a"]

    assert view.slideshow.set_locked(True) is False   # already locked: nothing moved
    assert view.slideshow.locked and favorite == ["gen-a"]


def test_a_spoken_lock_favorites_the_slide_like_a_pressed_one(qtbot):
    # Locking is Down's whole gesture here; a spoken lock must not quietly mean
    # less than a pressed one.
    favorite = []
    items = [("a.png", "image", "gen-a", None)]
    view = _view(qtbot, items=items, actions=SlideshowActions(favorite=favorite.append))

    view.slideshow.set_locked(True)
    _settle(view)

    assert favorite == ["gen-a"]


def test_asking_to_let_go_releases_only_what_was_locked(qtbot):
    view = _view(qtbot)

    assert view.slideshow.set_locked(False) is False   # nothing was locked
    view.slideshow.set_locked(True)
    _settle(view)
    assert view.slideshow.set_locked(False) is True
    assert not view.slideshow.locked


def test_favoriting_the_slide_on_screen_without_locking_it(qtbot):
    favorite = []
    items = [("a.png", "image", "gen-a", None)]
    view = _view(qtbot, items=items, actions=SlideshowActions(favorite=favorite.append))

    assert view.slideshow.favorite() is True

    assert favorite == ["gen-a"]
    assert not view.slideshow.locked  # bookmarked, still moving on


def test_favoriting_says_no_when_there_is_nothing_to_favorite(qtbot):
    # A slideshow whose items carry no generation id — or a live one with no row of
    # its own yet — has nothing to bookmark, and says so rather than seeming to.
    assert _view(qtbot).slideshow.favorite() is False


def test_stepping_and_culling_are_the_arrows_own_moves(qtbot):
    culled = []
    items = [("a.png", "image", "gen-a", None), ("b.png", "image", "gen-b", None),
             ("c.png", "image", "gen-c", None)]
    view = _view(qtbot, items=items, actions=SlideshowActions(delete=culled.append))

    view.slideshow.slideshow_step(1)
    _settle(view)
    assert view.slideshow._set.playlist.current()[2] == "gen-b"
    view.slideshow.slideshow_step(-1)
    _settle(view)
    assert view.slideshow._set.playlist.current()[2] == "gen-a"

    view.slideshow.cull()
    _settle(view)
    assert culled == ["gen-a"]
    assert view.slideshow._set.playlist.current()[2] == "gen-b"


def test_stepping_off_a_locked_slide_releases_it(qtbot):
    # The same rule the arrows follow: a lock holds the slide it was set on, not
    # wherever the user wanders to.
    view = _view(qtbot)
    view.slideshow.set_locked(True)
    _settle(view)

    view.slideshow.slideshow_step(1)
    _settle(view)

    assert not view.slideshow.locked


def _on_screen_wearing_its_panel(qtbot, view):
    view.resize(900, 700)
    view.show()
    qtbot.waitExposed(view)
    view.wear_the_hud("portrait")
    view._pane.tick()
    _settle(view)
    return view


def test_a_move_of_its_volume_is_told_to_the_gallery(qtbot):
    moved = []
    view = _on_screen_wearing_its_panel(qtbot, _view(qtbot, on_volume_moved=moved.append))

    gestures.click(view._pane._window, speaker_on_screen(view._pane))

    assert moved == [VolumeHud(volume=100, muted=True)]


def _on_the_picture(view) -> QPoint:
    """Clear of the panel in the upper left and of the corners that open it."""
    window = view._pane._window
    return QPoint(window.width() * 3 // 4, window.height() * 3 // 4)


def test_double_clicking_the_picture_leaves_the_slideshow(qtbot):
    # The way out of every other fullscreen view here, and the way it used to work.
    view = _on_screen_wearing_its_panel(qtbot, _view(qtbot))
    closes = []
    view.slideshow.closed.connect(lambda: closes.append(True))

    gestures.double_click(view._pane._window, _on_the_picture(view))

    qtbot.waitUntil(lambda: not view.isVisible())
    assert closes == [True]  # the dismissal reaches the gallery, like Escape's


def test_double_clicking_a_thumbnail_on_the_map_locks_the_slideshow_on_it(qtbot):
    view = _on_screen_wearing_its_panel(
        qtbot, _view(qtbot, _KEYED, actions=SlideshowActions(neighbors=_around)))

    gestures.double_click(view._pane._window, thumbnail_on_screen(view, "b.png"))

    assert view.isVisible()
    assert (_media_on_screen(view), view.slideshow.locked) == ("b.png", True)


def test_two_quick_clicks_on_next_step_on_twice_and_leave_the_slideshow_up(qtbot):
    view = _on_screen_wearing_its_panel(qtbot, _view(qtbot))

    gestures.double_click(view._pane._window, button_on_screen(view, "portrait_next"))

    assert view.isVisible()
    assert _media_on_screen(view) == "c.png"


def test_a_spoken_fix_targets_the_slide_on_screen(qtbot):
    view = _view(qtbot, _KEYED)
    assert view.slideshow.voice_target() == "id-a"
    _press(view, Qt.Key.Key_Right)
    assert view.slideshow.voice_target() == "id-b"


def test_a_spoken_fix_answers_in_the_corner_and_the_hud_follows_its_run(qtbot):
    view = _view(qtbot, _KEYED, actions=SlideshowActions(enhance=lambda pid: True))
    view.slideshow.note_voice_run("id-a", "fixing teeth…")
    assert "fixing teeth" in words(view._note)
    assert view.slideshow.hud_item_note == "Enhancement queued"
    view.slideshow.note_enhancing({"id-a": "running"})
    _settle(view)
    assert view.slideshow.hud_item_note == "Enhancing…"


def test_a_declined_spoken_fix_flashes_and_marks_nothing(qtbot):
    view = _view(qtbot, _KEYED)
    view.slideshow.note_voice_run(None, "no teeth detector installed")
    assert "no teeth detector" in words(view._note)
    _fade(view)
    assert view._note.isHidden()
    assert view.slideshow.hud_item_note == ""


def test_closing_announces_itself(qtbot):
    # The gallery keeps voice-command listening tied to a surface being up, so
    # a dismissal it didn't initiate (Escape) must still reach it.
    view = _view(qtbot)
    closes = []
    view.slideshow.closed.connect(lambda: closes.append(True))
    view.close()
    assert closes == [True]


# --- the Clip seconds: one number, app-wide ---------------------------------


def test_the_consoles_clip_seconds_are_the_app_wide_ones(qtbot):
    pace = SlideshowPace(parent=None)
    view = _view(qtbot, pace=pace)

    view.slideshow.set_dwell_s(2)
    _settle(view)

    assert (view.slideshow.dwell_s, pace.seconds, _engine(view).pace_s) == (2, 2, 2)


def test_the_clip_seconds_start_at_four():
    assert SlideshowPace().seconds == 4


def test_the_clip_seconds_go_no_lower_than_one():
    pace = SlideshowPace(seconds=0)
    opened_at = pace.seconds
    pace.step(-5)
    assert (opened_at, pace.seconds) == (1, 1)


def test_turning_the_pace_up_changes_a_running_slideshow(qtbot):
    pace = SlideshowPace()
    view = _view(qtbot, items=[("a.png", "image", "g1"), ("b.png", "image", "g2")], pace=pace)
    pace.set_seconds(9)
    assert _engine(view).pace_s == 9  # its Funestra is told
    assert view.slideshow.dwell_s == 9


def test_a_slideshow_opens_on_the_item_it_was_asked_for(qtbot):
    # Double-clicking the third picture in a folder opens on the third picture.
    view = _view(qtbot, start=2)
    assert view.slideshow._set.playlist.current() == Slide("c.png", "image")


# --- the dwell a picture keeps the screen for, and what stops the clock ------
# A still's move is the engine's own (funestra.ken_burns), paced by the dwell
# it was given, so the slideshow's part is the dwell it hands over and the freeze it
# hands with it.


def test_a_still_slide_is_handed_the_dwell_it_keeps_the_screen_for(qtbot):
    view = _view(qtbot, _KEYED)

    _press(view, Qt.Key.Key_Right)

    assert _engine(view).pace_s == 4


def test_locking_a_slide_leaves_it_where_it_is(qtbot):
    view = _view(qtbot, _KEYED)
    opened = list(_engine(view).opened)

    _press(view, Qt.Key.Key_Down)           # lock it

    assert _engine(view).opened == opened   # not opened again under the lock
    assert not _will_move_on(view)


def test_a_new_pace_reaches_a_locked_slide_without_opening_it_again(qtbot):
    # Not back out to the top of the move: a locked slide keeps where its move
    # had got to, and the pace changes only how fast the rest of it goes.
    view = _view(qtbot, _KEYED)
    _press(view, Qt.Key.Key_Down)
    opened = list(_engine(view).opened)

    view.slideshow.set_dwell_s(8)
    _settle(view)

    assert _engine(view).pace_s == 8
    assert _engine(view).opened == opened


def test_a_new_pace_reaches_the_picture_on_screen_without_opening_it_again(qtbot):
    # The engine takes a new pace on the picture it has up, so the picture
    # keeps its place on its move and on its scrubber, as a locked one does.
    view = _view(qtbot, _KEYED)
    opened = list(_engine(view).opened)

    view.slideshow.set_dwell_s(8)
    _settle(view)

    assert _engine(view).pace_s == 8
    assert _engine(view).opened == opened


def test_a_slideshow_reopened_on_a_locked_slide_opens_it_locked(qtbot):
    closed = _view(qtbot, _KEYED)
    _press(closed, Qt.Key.Key_Down)
    reopened = _view(qtbot, _KEYED)

    reopened.slideshow.resume(closed.slideshow.state())
    _settle(reopened)

    assert _engine(reopened).pace_s == 4
    assert not _will_move_on(reopened)


def test_a_request_keeps_the_picture_on_screen_still_moving_and_its_release_lets_it_go(qtbot):
    view = _view(qtbot, _KEYED)

    view.slideshow.pause_for_request(True, "listening…")
    _settle(view)
    while_said = (_engine(view).loop_file, _engine(view).pace_s)
    view.slideshow.pause_for_request(False)
    _settle(view)

    assert (while_said, _engine(view).loop_file) == ((True, 4), False)


def test_the_rooms_freeze_holds_it_and_its_resume_lets_it_go(qtbot):
    view = _view(qtbot, _KEYED)

    view.slideshow.set_paused(True)
    assert _engine(view).paused is True

    view.slideshow.set_paused(False)
    assert _engine(view).paused is False


def test_a_locked_slide_stays_locked_through_a_request_and_is_stilled_by_the_rooms_freeze(qtbot):
    view = _view(qtbot, _KEYED)
    _press(view, Qt.Key.Key_Down)

    view.slideshow.pause_for_request(True, "listening…")
    _settle(view)
    view.slideshow.pause_for_request(False)
    _settle(view)
    assert _engine(view).loop_file is True

    view.slideshow.set_paused(True)
    assert _engine(view).paused is True
    view.slideshow.set_paused(False)
    assert _engine(view).paused is False
    assert not _will_move_on(view)


def test_a_request_released_under_the_rooms_freeze_leaves_it_frozen(qtbot):
    view = _view(qtbot, _KEYED)

    view.slideshow.set_paused(True)
    view.slideshow.pause_for_request(True, "listening…")
    _settle(view)
    view.slideshow.pause_for_request(False)
    _settle(view)

    assert _engine(view).paused is True


def test_a_request_leaves_a_clip_playing_and_only_stops_the_slideshow_moving_on(qtbot):
    """The request is about what is on screen; a clip that stopped mid-sentence
    would be answering a question nobody asked."""
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Right)          # -> the video

    view.slideshow.pause_for_request(True, "listening…")
    _settle(view)

    assert _engine(view).paused is False
    assert not _will_move_on(view)


def _click(view):
    view._pane.press(QPointF(view._pane.width() / 2, view._pane.height() / 2))


def _escape(view):
    _press(view, Qt.Key.Key_Escape)


_A_CLICK_OR_ESC = pytest.mark.parametrize("pause_press", [_click, _escape],
                                          ids=["a click on the picture", "Esc"])


@_A_CLICK_OR_ESC
def test_a_pause_press_pauses_a_slideshow_with_no_room_to_ask_at_once_and_a_second_plays_it(
        qtbot, pause_press):
    view = _view(qtbot, _KEYED)

    pause_press(view)
    assert not _will_move_on(view)
    assert _engine(view).paused is True

    pause_press(view)
    assert _will_move_on(view)
    assert _engine(view).paused is False


@_A_CLICK_OR_ESC
def test_a_pause_press_asks_the_room_to_pause_rather_than_pausing_the_slideshow_alone(
        qtbot, pause_press):
    asked = []
    view = _view(qtbot, _KEYED,
                 on_omnipause=lambda: asked.append(True))

    pause_press(view)

    assert asked == [True]
    assert _will_move_on(view)


def test_each_slide_is_opened_in_its_own_right(qtbot):
    view = _view(qtbot, _KEYED)
    _press(view, Qt.Key.Key_Right)
    opened = len(_engine(view).opened)

    _press(view, Qt.Key.Key_Right)

    assert len(_engine(view).opened) == opened + 1


def test_closing_the_slideshow_lets_the_engine_go(qtbot):
    view = _view(qtbot, _KEYED)

    view.close()

    assert _engine(view).closed is True


# --- re-seeding the set after it opened -------------------------------------

def test_a_slideshow_opened_on_one_item_of_a_folder_walks_the_folder_in_its_order(qtbot):
    view = _view(qtbot, [("a.png", "image", "id-a"), ("b.png", "image", "id-b"),
                         ("c.png", "image", "id-c")], start=1, shuffle=in_order)

    assert view.slideshow._set.playlist.current()[2] == "id-b"
    _press(view, Qt.Key.Key_Right)
    assert view.slideshow._set.playlist.current()[2] == "id-c"
    _press(view, Qt.Key.Key_Left)
    _press(view, Qt.Key.Key_Left)
    assert view.slideshow._set.playlist.current()[2] == "id-a"   # in the folder's own order


def test_a_folder_walked_in_its_order_wraps_at_either_end(qtbot):
    view = _view(qtbot, [("a.png", "image", "id-a"), ("b.png", "image", "id-b")],
                 start=0, shuffle=in_order)

    _press(view, Qt.Key.Key_Left)   # from the first, wrap back to the last
    assert view.slideshow._set.playlist.current()[2] == "id-b"
    _press(view, Qt.Key.Key_Right)  # and forward off the last, wrap to the first
    assert view.slideshow._set.playlist.current()[2] == "id-a"


# --- Shift+Left/Right: the versions of the image on screen -------------------

def test_shift_arrows_step_the_versions_of_the_image_on_screen(qtbot, tmp_path):
    enhanced, original = (_png(tmp_path / n) for n in ("e1.png", "src.png"))
    view = _view(qtbot, [(enhanced, "image", "id-a")])
    view.slideshow.set_levels({enhanced: [(enhanced, "image"), (original, "image")]})
    _settle(view)

    _shift(view, Qt.Key.Key_Right)
    assert _media_on_screen(view) == original
    # And back round: two versions wrap, so the pair is a toggle.
    _shift(view, Qt.Key.Key_Right)
    assert _media_on_screen(view) == enhanced


FACE = ((0.4, 0.1, 0.6, 0.3),)


def test_versions_that_arrive_with_places_hand_the_funestra_the_picture_on_screens(qtbot, tmp_path):
    enhanced, original = (_png(tmp_path / n) for n in ("e1.png", "src.png"))
    view = _view(qtbot, [(enhanced, "image", "id-a")])

    view.slideshow.set_levels({enhanced: [(enhanced, "image", "Enhance 1", FACE), (original, "image")]})
    _settle(view)

    assert _engine(view).points_told == [FACE]


def test_a_version_stepped_to_goes_up_with_its_own_places(qtbot, tmp_path):
    newest, older = (_png(tmp_path / n) for n in ("e2.png", "e1.png"))
    view = _view(qtbot, [(newest, "image", "id-a")])
    view.slideshow.set_levels({newest: [(newest, "image", "Enhance 2", FACE),
                              (older, "image", "Enhance 1", ((0.0, 0.0, 0.5, 0.5),))]})

    _shift(view, Qt.Key.Key_Right)

    assert _engine(view).points_told[-1] == ((0.0, 0.0, 0.5, 0.5),)


@_ARROW_KEYS_OR_WASD
def test_shift_left_counts_the_enhancements_down_and_shift_right_counts_them_up(
        qtbot, tmp_path, arrows):
    newest, middle, original = (_png(tmp_path / n) for n in ("e2.png", "e1.png", "src.png"))
    view = _view(qtbot, [(newest, "image", "id-a")])
    view.slideshow.set_levels({newest: [(newest, "image", "Enhancement 2/2"),
                              (middle, "image", "Enhancement 1/2"),
                              (original, "image", "Original")]})

    named = []
    for arrow in (arrows.left, arrows.left, arrows.right, arrows.right):
        _shift(view, arrow)
        named.append(view.slideshow.hud_item_note)

    assert named == ["Enhancement 1/2", "Original", "Enhancement 1/2", "Enhancement 2/2"]


def test_a_version_shift_stepped_to_comes_up_moving_and_holds_the_slideshow(qtbot, tmp_path):
    enhanced, original = (_png(tmp_path / n) for n in ("e1.png", "src.png"))
    view = _view(qtbot, [(enhanced, "image", "id-a"), ("b.png", "image", "id-b")])
    view.slideshow.set_levels({enhanced: [(enhanced, "image"), (original, "image")]})
    _settle(view)

    _shift(view, Qt.Key.Key_Right)
    _runs_out(view)

    assert (_engine(view).opened_at_pace[-1], _engine(view).loop_file) == (4, True)
    assert _media_on_screen(view) == original


@pytest.mark.parametrize("arrow", [Qt.Key.Key_Left, Qt.Key.Key_Right], ids=["Left", "Right"])
def test_a_plain_arrow_after_comparing_versions_sets_the_slideshow_going_again(
        qtbot, tmp_path, arrow):
    enhanced, original, other = (_png(tmp_path / n) for n in ("e1.png", "src.png", "b.png"))
    view = _view(qtbot, [(enhanced, "image", "id-a"), (other, "image", "id-b")])
    view.slideshow.set_levels({enhanced: [(enhanced, "image"), (original, "image")]})
    _settle(view)
    _shift(view, Qt.Key.Key_Right)

    _press(view, arrow)

    assert _media_on_screen(view) == other
    assert _engine(view).opened_at_pace[-1] == 4
    assert _will_move_on(view)


def test_a_pace_set_while_versions_are_compared_waits_for_the_arrow_that_moves_on(
        qtbot, tmp_path):
    enhanced, original, other = (_png(tmp_path / n) for n in ("e1.png", "src.png", "b.png"))
    view = _view(qtbot, [(enhanced, "image", "id-a"), (other, "image", "id-b")])
    view.slideshow.set_levels({enhanced: [(enhanced, "image"), (original, "image")]})
    _settle(view)
    _shift(view, Qt.Key.Key_Right)
    opened = list(_engine(view).opened)

    view.slideshow.set_dwell_s(9)
    _settle(view)
    held = (_engine(view).loop_file, list(_engine(view).opened))
    _press(view, Qt.Key.Key_Right)

    assert held == (True, opened)
    assert _engine(view).opened_at_pace[-1] == 9


def test_a_version_landing_while_versions_are_compared_keeps_the_slideshow_held(
        qtbot, tmp_path):
    a, a_base, better = (_png(tmp_path / n) for n in ("a.png", "a0.png", "a2.png"))
    view = _view(qtbot, [(a, "image", "id-a"), ("b.png", "image", "id-b")])
    view.slideshow.set_levels({a: [(a, "image", "Enhancement 1/1"), (a_base, "image", "Original")]})
    _settle(view)
    _shift(view, Qt.Key.Key_Right)

    view.slideshow.note_enhanced("id-a", better)
    _settle(view)
    _runs_out(view)

    assert (_engine(view).loop_file, _media_on_screen(view)) == (True, better)


def test_comparing_a_videos_versions_holds_the_slideshow_on_them_too(qtbot):
    view = _view(qtbot, [("clip.mp4", "video", "id-a"), ("b.png", "image", "id-b")])
    view.slideshow.set_levels({"clip.mp4": [("clip_evolved.mp4", "video", "Evolved"),
                                  ("clip.mp4", "video", "Original")]})

    _shift(view, Qt.Key.Key_Left)
    _runs_out(view)

    assert _media_on_screen(view) == "clip.mp4"
    assert _engine(view).loop_file is True


def test_a_picture_being_enhanced_is_not_moved_on_early_while_its_versions_are_compared(
        qtbot, tmp_path):
    a, a_base = (_png(tmp_path / n) for n in ("a.png", "a0.png"))
    view = _view(qtbot, [(a, "image", "id-a"), ("b.png", "image", "id-b")], enhancing={"id-a": "running"})
    view.slideshow.set_levels({a: [(a, "image", "Enhancement 1/1"), (a_base, "image", "Original")]})
    _settle(view)
    _shift(view, Qt.Key.Key_Right)

    _time_passes(view, 3)

    assert view.slideshow._set.playlist.current()[2] == "id-a"


def test_shift_arrows_do_nothing_for_an_image_with_one_version(qtbot, tmp_path):
    lone = _png(tmp_path / "only.png")
    view = _view(qtbot, [(lone, "image", "id-a")])
    view.slideshow.set_levels({})
    _settle(view)

    _shift(view, Qt.Key.Key_Right)

    # Silently nothing, rather than stepping the set when the shift was the
    # whole point of the press -- or holding a picture with nothing to compare.
    assert _media_on_screen(view) == lone
    assert _engine(view).pace_s == view.slideshow.dwell_s


def test_stepping_to_another_image_starts_its_versions_from_the_top(qtbot, tmp_path):
    first, second, second_base = (_png(tmp_path / n) for n in
                                  ("a.png", "b.png", "b_base.png"))
    view = _view(qtbot, [(first, "image", "id-a"), (second, "image", "id-b")])
    view.slideshow.set_levels({second: [(second, "image"), (second_base, "image")]})
    _settle(view)

    _press(view, Qt.Key.Key_Right)   # onto the second image
    _shift(view, Qt.Key.Key_Right)   # its own versions, from the top

    assert _media_on_screen(view) == second_base


def test_the_hud_says_which_version_is_on_screen(qtbot, tmp_path):
    enhanced, original = (_png(tmp_path / n) for n in ("e1.png", "src.png"))
    view = _view(qtbot, [(enhanced, "image", "id-a")])
    view.slideshow.set_levels({enhanced: [(enhanced, "image", "Enhancement 1/1"),
                                (original, "image", "Original")]})

    assert view.slideshow.hud_item_note == "Enhancement 1/1"
    _shift(view, Qt.Key.Key_Right)
    assert view.slideshow.hud_item_note == "Original"
    assert view._note.isHidden()


def test_an_image_with_one_version_says_nothing(qtbot, tmp_path):
    view = _view(qtbot, [(_png(tmp_path / "only.png"), "image", "id-a")])
    view.slideshow.set_levels({})
    _settle(view)
    assert view.slideshow.hud_item_note == ""


def test_a_version_step_keeps_the_item_as_the_enhance_target(qtbot, tmp_path):
    # The file on screen is one of this item's versions, but the generation being
    # asked about is still the item's — read off the playlist, not off the file.
    enhanced, original = (_png(tmp_path / n) for n in ("e1.png", "src.png"))
    view = _view(qtbot, [(enhanced, "image", "id-a")])
    view.slideshow.set_levels({enhanced: [(enhanced, "image"), (original, "image")]})
    _settle(view)

    _shift(view, Qt.Key.Key_Right)

    assert view.slideshow.voice_target() == "id-a"


def test_a_version_step_re_aims_the_device(qtbot, tmp_path):
    enhanced, original = (_png(tmp_path / n) for n in ("e1.png", "src.png"))
    view = _view(qtbot, [(enhanced, "image", "id-a")])
    view.slideshow.set_levels({enhanced: [(enhanced, "image"), (original, "image")]})
    _settle(view)
    changed = []
    view.slideshow.media_changed.connect(lambda: changed.append(True))

    _shift(view, Qt.Key.Key_Right)

    assert changed == [True]


# --- opened over a generation still being made ------------------------------

def _frame_up(view):
    """The frame the Funestra was last handed, as bytes -- None while a file
    of the set or a line is up instead."""
    engine = _engine(view)
    if engine is None or view.slideshow._frame_on_funestra is None:
        return None
    on_screen = engine.on_screen
    return on_screen.read_bytes() if on_screen is not None and on_screen.exists() else None


def _showing_a_picture(view):
    return _frame_up(view) is not None


def _following(qtbot, folder=(), frame=None, **kw):
    """A slideshow opened over a run being made, as a double-click on a tab's preview
    of one opens it: the folder the run is made in, the run in front, held on it."""
    view = _view(qtbot, list(folder), **kw)
    view.slideshow.note_generating("id-run", frame or _png_bytes())
    view.slideshow.follow_what_is_being_made()
    _settle(view)
    return view


def test_opens_over_a_running_generation_showing_its_frame(qtbot):
    view = _following(qtbot)
    assert _media_on_screen(view) == ""               # no file under it yet
    assert _showing_a_picture(view)  # the streamed frame shows
    assert _engine(view).loop_file is True  # and held there


def test_a_run_whose_first_frame_comes_after_the_slideshow_opened_joins_it(qtbot):
    view = _view(qtbot, [])
    assert _engine(view) is None  # nothing to open on yet

    view.slideshow.note_generating("id-run", _png_bytes())
    _settle(view)

    assert _showing_a_picture(view)


def test_a_later_frame_replaces_the_one_it_opened_over(qtbot):
    view = _following(qtbot, frame=_png_bytes((10, 10, 10)))

    view.slideshow.note_generating("id-run", _png_bytes((200, 10, 10)))
    _settle(view)

    assert _frame_up(view) == _png_bytes((200, 10, 10))


def test_the_landed_file_takes_over_from_the_frames(qtbot, tmp_path):
    # Watching a generation full-screen ends on the finished image, not the last
    # low-res frame it streamed.
    png = _png(tmp_path / "done.png")
    view = _following(qtbot)
    changed = []
    view.slideshow.media_changed.connect(lambda: changed.append(True))

    view.slideshow.note_added(png, "image", "id-run")
    _settle(view)

    assert _media_on_screen(view) == png
    assert changed == [True]  # a landed video is a fresh OSR2 target


def test_frames_are_ignored_once_it_has_landed(qtbot, tmp_path):
    png = _png(tmp_path / "done.png")
    view = _following(qtbot)
    view.slideshow.note_added(png, "image", "id-run")
    _settle(view)

    view.slideshow.note_generating("id-run", _png_bytes())  # a late frame must not paint over it
    _settle(view)

    assert _media_on_screen(view) == png
    assert not _showing_a_picture(view)


def test_stepping_leaves_the_live_generation_behind(qtbot, tmp_path):
    # Stepped onto a saved item, the slideshow is no longer the run's — later frames of
    # it must not paint over what the user stepped to.
    a, b = (_png(tmp_path / n) for n in ("a.png", "b.png"))
    view = _following(qtbot, [(a, "image", "id-a"), (b, "image", "id-b")], shuffle=in_order)

    _press(view, Qt.Key.Key_Right)
    view.slideshow.note_generating("id-run", _png_bytes((200, 10, 10)))
    _settle(view)

    assert _media_on_screen(view) == a


def test_a_run_with_no_folder_armed_behind_it_ignores_the_arrows(qtbot):
    view = _following(qtbot)
    _press(view, Qt.Key.Key_Right)
    assert _showing_a_picture(view)


def test_a_live_slideshow_drives_no_device(qtbot):
    # Streamed frames are no video: nothing for the OSR2 to follow.
    view = _following(qtbot)
    assert view.slideshow.osr2_drive_target() is None


# --- what a fullscreen slideshow is, as media -------------------------------

def test_it_plays_audio_unlike_the_muted_inline_preview(qtbot):
    # Filling the screen with a clip is deliberate, so it's heard.
    view = _view(qtbot)
    assert _engine(view).muted is False


def test_a_scripted_clip_hands_its_motion_to_the_panel(qtbot, tmp_path):
    """The colors used to be a strip under the picture; they fill the panel's
    own track now, and this is where they come from."""
    vid = tmp_path / "c.mp4"
    write_funscript(vid.with_suffix(".funscript"),
                    synthesize_actions(2.0, hz=1.0))
    view = _view(qtbot, [(str(vid), "video")])
    assert view._pane.playback.has_funscript


def test_closing_releases_the_video_file(qtbot, tmp_path):
    # A held media handle blocks move-to-trash on Windows, so closing must drop it.
    view = _view(qtbot, [(str(tmp_path / "c.mp4"), "video")])
    view.close()
    assert _engine(view).closed is True


def test_closing_lets_the_engine_go_before_what_it_draws_into(qtbot, tmp_path):
    # A closed slideshow is dropped by whoever held it, and a new one opening on the
    # same region drops it at once. Its engine must be finished with by then,
    # not still rendering into a framebuffer about to go under it: that was the
    # crash on every slideshow replace and every quit.
    view = _view(qtbot, [(str(tmp_path / "c.mp4"), "video")])
    view.close()
    assert _engine(view).closed is True


def test_a_slideshow_wears_the_apps_icon_in_the_window_switcher(qtbot, qapp):
    # The slideshow is a window of its own with no frame and no icon of its own, and
    # the switcher drew it a blank page until the app carried one for every
    # window it opens.
    before = qapp.windowIcon()
    qapp.setWindowIcon(QIcon())
    try:
        dress_application(qapp, None)

        assert not _view(qtbot).windowIcon().isNull()
    finally:
        qapp.setWindowIcon(before)


def test_releasing_a_condemned_file_lets_go_of_it(qtbot, tmp_path):
    clip = str(tmp_path / "c.mp4")
    view = _view(qtbot, [(clip, "video")])

    view.slideshow.release_media([clip])
    _settle(view)

    assert _media_on_screen(view) == ""
    assert _engine(view).stopped is True


def test_releasing_another_file_leaves_the_slideshow_alone(qtbot, tmp_path):
    kept = str(tmp_path / "kept.mp4")
    view = _view(qtbot, [(kept, "video")])

    view.slideshow.release_media([str(tmp_path / "doomed.mp4")])
    _settle(view)

    assert _media_on_screen(view) == kept


# --- the OSR2 drive target: the clip on screen ------------------------------

def test_osr2_drive_target_bundles_the_scripted_video(qtbot, tmp_path):
    vid = tmp_path / "c.mp4"
    write_funscript(vid.with_suffix(".funscript"),
                    synthesize_actions(2.0, hz=1.0))
    view = SlideshowView([(str(vid), "video")], engine=FakeEngine(),
                         shuffle=lambda order: None)
    qtbot.addWidget(view)

    target = view.slideshow.osr2_drive_target()

    assert target is not None
    path, tgt_player, actions = target
    # The pane itself is what the drive follows: it is what knows where the
    # clip has got to, the way the config panel's media Funestra is there.
    assert path == str(vid) and tgt_player is view._pane and actions


def test_osr2_drive_target_is_none_for_an_image(qtbot, tmp_path):
    view = _view(qtbot, [(_png(tmp_path / "p.png"), "image")])
    assert view.slideshow.osr2_drive_target() is None


def test_osr2_drive_target_is_none_for_an_unscripted_video(qtbot, tmp_path):
    view = _view(qtbot, [(str(tmp_path / "c.mp4"), "video")])
    assert view.slideshow.osr2_drive_target() is None


# --- the video on screen, by the run it came from ---------------------------

def test_the_video_on_screen_is_named_by_the_run_it_came_from(qtbot):
    view = _view(qtbot, [Slide("b.mp4", "video", "beta-1")])
    assert view.slideshow.video_on_screen() == "beta-1"


def test_a_picture_or_the_frames_of_a_run_still_going_are_no_video_on_screen(qtbot, tmp_path):
    assert _view(qtbot, [Slide(_png(tmp_path / "p.png"), "image", "alpha-1")]
                 ).slideshow.video_on_screen() is None
    assert _following(qtbot).slideshow.video_on_screen() is None


def test_the_video_on_screen_follows_the_slideshow_onto_the_next_item(qtbot, tmp_path):
    view = _view(qtbot, [Slide(_png(tmp_path / "p.png"), "image", "alpha-1"),
                         Slide("b.mp4", "video", "beta-1")])

    _runs_out(view)

    assert view.slideshow.video_on_screen() == "beta-1"


def test_stepping_re_aims_the_device(qtbot):
    view = _view(qtbot)
    changed = []
    view.slideshow.media_changed.connect(lambda: changed.append(True))
    _press(view, Qt.Key.Key_Right)
    assert changed == [True]


def test_stepping_a_paused_slideshow_still_re_aims_the_device(qtbot):
    view = _view(qtbot)
    view.slideshow.set_paused(True)
    changed = []
    view.slideshow.media_changed.connect(lambda: changed.append(True))

    _press(view, Qt.Key.Key_Right)

    assert changed == [True]

# --- the pause a spoken request puts on the slideshow -----------------------


def test_a_request_pauses_the_advance_and_says_so(qtbot):
    view = _view(qtbot, _KEYED)
    assert _will_move_on(view)  # an image, dwelling

    view.slideshow.pause_for_request(True, "Request: no hat…")
    _settle(view)

    assert not _will_move_on(view)
    assert "Request" in words(view._note)


def test_releasing_the_pause_resumes_the_dwell(qtbot):
    view = _view(qtbot, _KEYED)
    view.slideshow.pause_for_request(True, "Request…")
    _settle(view)

    view.slideshow.pause_for_request(False)
    _settle(view)

    assert _will_move_on(view)
    assert view._note.isHidden()


def test_the_slide_stays_put_while_a_request_is_being_said(qtbot):
    # The point of the pause: the request is about this slide, so the slideshow must
    # not page on while the sentence is still being spoken.
    view = _view(qtbot, _KEYED)
    view.slideshow.pause_for_request(True, "Request…")
    _settle(view)

    _runs_out(view)  # the clip on screen ran out mid-sentence

    assert view.slideshow.voice_target() == "id-a"


def test_releasing_the_pause_leaves_a_locked_slide_locked(qtbot):
    view = _view(qtbot, _KEYED)
    view.slideshow.set_locked(True)  # the user locked this one
    _settle(view)
    view.slideshow.pause_for_request(True, "Request…")
    _settle(view)

    view.slideshow.pause_for_request(False)
    _settle(view)

    assert view.slideshow.locked
    assert not _will_move_on(view)  # still stopped — by the lock, now


def test_a_request_targets_the_slide_on_screen(qtbot):
    view = _view(qtbot, _KEYED)
    assert view.slideshow.voice_target() == "id-a"
    _press(view, Qt.Key.Key_Right)
    assert view.slideshow.voice_target() == "id-b"


def test_a_finished_request_answers_in_the_corner(qtbot):
    view = _view(qtbot, _KEYED)
    view.slideshow.note_request("dropped “a hat” — generating")
    assert "dropped" in words(view._note)


def test_a_clip_the_backend_cannot_open_does_not_park_the_slideshow(qtbot, tmp_path):
    """A video carries no dwell timer — its own length is its dwell — so a clip
    that never reports an end is a black screen for the rest of the session.
    One this backend has no codec for is exactly that, and browsing the whole
    library is where it turns up.  It gets stepped past instead."""
    first, second = tmp_path / "a.png", tmp_path / "b.png"
    for path in (first, second):
        Image.new("RGB", (40, 30)).save(path)
    items = [(str(tmp_path / "broken.mp4"), "video", "v-1", None),
             (str(first), "image", "i-1", None),
             (str(second), "image", "i-2", None)]
    view = _view(qtbot, items, shuffle=in_order)
    assert view.slideshow._set.playlist.current()[2] == "v-1"

    _engine(view).idle = True           # the engine opened nothing at all
    view._pane.tick()
    _settle(view)

    assert view.slideshow._set.playlist.current()[2] == "i-1"


def test_an_unopenable_clip_is_stepped_past_even_while_locked(qtbot, tmp_path):
    """A lock replays the clip it holds, which would hold a clip that cannot
    play forever.  So this one step happens regardless: the item stays in the
    set, but the screen does not stay black."""

    still = tmp_path / "a.png"
    Image.new("RGB", (40, 30)).save(still)
    view = _view(qtbot, [(str(tmp_path / "broken.mp4"), "video", "v-1", None),
                         (str(still), "image", "i-1", None)],
                 shuffle=in_order)
    view.slideshow.set_locked(True)
    _settle(view)

    _engine(view).idle = True
    view._pane.tick()
    _settle(view)

    assert view.slideshow._set.playlist.current()[2] == "i-1"


# --- picking a closed slideshow back up -------------------------------------

_THREE = [("a.png", "image", "id-a"), ("b.png", "image", "id-b"),
          ("c.png", "image", "id-c")]


def test_the_state_names_the_pass_and_the_slide_it_is_on(qtbot):
    view = _view(qtbot, _THREE)
    _press(view, Qt.Key.Key_Right)

    state = view.slideshow.state()

    assert state.order == ("id-a", "id-b", "id-c")
    assert state.current == "id-b"
    assert state.locked is False


def test_a_reopened_slideshow_stands_where_the_last_one_was_closed(qtbot):
    # Closing a slideshow is usually a detour — the folder under the picture, a fix
    # in a tab — so coming back is coming back to that picture.
    closed = _view(qtbot, _THREE)
    _press(closed, Qt.Key.Key_Right)
    _press(closed, Qt.Key.Key_Right)

    reopened = _view(qtbot, _THREE, shuffle=lambda order: order.reverse())
    assert reopened.slideshow.resume(closed.slideshow.state()) is True

    assert reopened.slideshow._set.playlist.current()[2] == "id-c"
    assert _media_on_screen(reopened) == "c.png"


def test_a_reopened_slideshow_carries_on_in_the_order_it_was_playing(qtbot):
    closed = _view(qtbot, _THREE, shuffle=lambda order: order.reverse())  # c, b, a
    _press(closed, Qt.Key.Key_Right)   # -> b

    reopened = _view(qtbot, _THREE)    # a fresh shuffle would lead with a
    reopened.slideshow.resume(closed.slideshow.state())
    _settle(reopened)

    _press(reopened, Qt.Key.Key_Right)
    assert reopened.slideshow._set.playlist.current()[2] == "id-a"   # the closed slideshow's pass


def test_a_slide_closed_under_a_lock_reopens_locked(qtbot):
    closed = _view(qtbot, _THREE)
    _press(closed, Qt.Key.Key_Down)    # locked: this is the one
    state = closed.slideshow.state()
    closed.close()

    reopened = _view(qtbot, _THREE)
    reopened.slideshow.resume(state)
    _settle(reopened)

    assert reopened.slideshow.locked
    assert not _will_move_on(reopened)  # locked, so nothing moves it on


def test_a_slideshow_takes_up_each_filter_that_leaves_it_something(qtbot):
    view = _view(qtbot, _THREE, favorite_ids={"id-a"}, enhanced_ids={"id-b", "id-c"})

    view.slideshow.take_up(SlideshowFilters(favorites=True, enhanced=True))
    _settle(view)

    assert (view.slideshow.hud_favorites_filter, view.slideshow.hud_enhanced_mode) == (True, False)
    assert [item[2] for item in view.slideshow._set.playlist._items] == ["id-a"]


def test_a_slideshow_opened_on_a_picture_keeps_it_up_under_filters_that_leave_it_out(qtbot):
    view = _view(qtbot, _THREE, start=0, enhanced_ids={"id-b", "id-c"})

    view.slideshow.take_up(SlideshowFilters(enhanced=True), keep_the_slide=True)
    _settle(view)

    assert view.slideshow.hud_enhanced_mode
    assert view.slideshow._set.playlist.current()[2] == "id-a"
    _press(view, Qt.Key.Key_Right)
    assert view.slideshow._set.playlist.current()[2] == "id-b"


def test_a_slideshow_closed_looping_actions_reopens_looping_them_where_it_stood(qtbot):
    library = SlideshowActions(neighbors=_around, slides=slides_named(
        Slide("a.png", "image", "id-a"), Slide("c.png", "image", "id-c")))
    browsing = [*_KEYED, ("z.png", "image", "id-z")]
    closed = _view(qtbot, browsing, actions=library)
    _press(closed, Qt.Key.Key_E)
    _press(closed, Qt.Key.Key_E)
    _press(closed, Qt.Key.Key_Right)

    reopened = _view(qtbot, browsing, actions=library)
    reopened.slideshow.resume(closed.slideshow.state())
    _settle(reopened)

    assert reopened.slideshow.hud_map() == closed.slideshow.hud_map()
    assert reopened.slideshow.hud_map().loop == "action"
    assert _media_on_screen(reopened) == "c.png"


def test_a_slideshow_of_a_set_without_that_slide_starts_fresh(qtbot):
    # Another folder, or one the slide has since been culled from: there is
    # nowhere in here to put it, so the shuffle it opened with stands.
    closed = _view(qtbot, _THREE)
    _press(closed, Qt.Key.Key_Down)

    elsewhere = _view(qtbot, [("x.png", "image", "id-x"), ("y.png", "image", "id-y")])
    assert elsewhere.slideshow.resume(closed.slideshow.state()) is False

    assert elsewhere.slideshow._set.playlist.current()[2] == "id-x"
    assert not elsewhere.slideshow.locked


def test_a_reopened_slideshow_shows_the_version_that_was_on_screen(qtbot, tmp_path):
    enhanced, original = (_png(tmp_path / n) for n in ("e1.png", "src.png"))
    levels = {enhanced: [(enhanced, "image"), (original, "image")]}
    closed = _view(qtbot, [(enhanced, "image", "id-a")])
    closed.slideshow.set_levels(levels)
    _settle(closed)
    _shift(closed, Qt.Key.Key_Left)    # stepped down to the original

    reopened = _view(qtbot, [(enhanced, "image", "id-a")])
    reopened.slideshow.set_levels(levels)        # armed before the resume, as the gallery does
    _settle(reopened)
    reopened.slideshow.resume(closed.slideshow.state())
    _settle(reopened)

    assert _media_on_screen(reopened) == original


def test_a_slideshow_following_a_running_generation_resumes_nothing(qtbot):
    # It has no items of its own yet, so there is no slide in it to stand on.
    closed = _view(qtbot, _THREE)
    live = _following(qtbot)

    assert live.slideshow.resume(closed.slideshow.state()) is False
    assert live.slideshow._set.current_prompt_id() == "id-run"


def test_the_state_read_as_a_slideshow_closes_still_shows_its_lock(qtbot):
    # The gallery reads it from the ``closed`` signal, and the lock is dropped
    # immediately after — a slide closed under a lock has to still be locked there,
    # or a reopened slideshow would come back to it released.
    view = _view(qtbot, _THREE)
    _press(view, Qt.Key.Key_Down)
    seen = []
    view.slideshow.closed.connect(lambda: seen.append(view.slideshow.state()))

    view.close()

    assert seen[0].current == "id-a"
    assert seen[0].locked


# --- a generation that is still being made ----------------------------------

def test_a_run_that_starts_to_look_like_something_joins_the_slideshow(qtbot):
    # Not the wait — a black screen saying "Generating…" is nothing to watch —
    # but the first iterations coming in, which are what the slideshow is being
    # watched for in the first place.
    view = _view(qtbot, [("a.png", "image", "id-a")])

    view.slideshow.note_generating("id-run", _png_bytes())
    _settle(view)

    assert len(view.slideshow._set.playlist) == 2
    assert view.slideshow._set.playlist.current()[2] == "id-a"      # the slide on screen is left alone
    assert ahead(view.slideshow._set.playlist, 1)[1] == LIVE
    assert view.slideshow.holds("id-run")


def test_a_live_slide_shows_the_newest_frame_while_it_is_on_screen(qtbot):
    view = _view(qtbot, [("a.png", "image", "id-a")])
    view.slideshow.note_generating("id-run", _png_bytes())
    _settle(view)
    _press(view, Qt.Key.Key_Right)                    # step onto it

    later = _png_bytes(color=(200, 40, 40))
    view.slideshow.note_generating("id-run", later)
    _settle(view)

    assert _frame_up(view) == later


def test_a_live_slide_becomes_the_file_when_the_run_lands(qtbot, tmp_path):
    # The same slide, finished — not a second one beside the frames it arrived as.
    landed = _png(tmp_path / "landed.png")
    view = _view(qtbot, [(_png(tmp_path / "a.png"), "image", "id-a")])
    view.slideshow.note_generating("id-run", _png_bytes())
    _settle(view)
    _press(view, Qt.Key.Key_Right)

    view.slideshow.note_added(landed, "image", "id-run", None)
    _settle(view)

    assert len(view.slideshow._set.playlist) == 2
    assert view.slideshow._set.playlist.current() == (landed, "image", "id-run", None)
    assert _media_on_screen(view) == landed


def test_a_run_that_was_cancelled_leaves_the_slideshow(qtbot, tmp_path):
    # No file is coming, so the half-rendered frame it got to would otherwise
    # hold a place in the pass forever.
    view = _view(qtbot, [(_png(tmp_path / "a.png"), "image", "id-a")])
    view.slideshow.note_generating("id-run", _png_bytes())
    _settle(view)

    view.slideshow.note_in_flight(set())
    _settle(view)

    assert len(view.slideshow._set.playlist) == 1
    assert not view.slideshow.holds("id-run")


def test_a_run_still_going_keeps_its_slide(qtbot):
    view = _view(qtbot, [("a.png", "image", "id-a")])
    view.slideshow.note_generating("id-run", _png_bytes())
    _settle(view)

    view.slideshow.note_in_flight({"id-run"})
    _settle(view)

    assert view.slideshow.holds("id-run")


def test_culling_a_slide_being_made_calls_nothing_off(qtbot, tmp_path):
    # The run is on the GPU and its row is a record of that, not a picture that
    # has been judged. Up takes it off the slideshow and leaves the run alone.
    condemned = []
    view = _view(qtbot, [(_png(tmp_path / "a.png"), "image", "id-a")],
                 actions=SlideshowActions(delete=condemned.append))
    view.slideshow.note_generating("id-run", _png_bytes())
    _settle(view)
    _press(view, Qt.Key.Key_Right)

    _press(view, Qt.Key.Key_Up)

    assert condemned == []
    assert not view.slideshow.holds("id-run")


def test_a_culled_run_does_not_come_back_on_its_next_frame(qtbot, tmp_path):
    # Offered once, or Up over it would mean nothing at all.
    view = _view(qtbot, [(_png(tmp_path / "a.png"), "image", "id-a")])
    view.slideshow.note_generating("id-run", _png_bytes())
    _settle(view)
    _press(view, Qt.Key.Key_Right)
    _press(view, Qt.Key.Key_Up)

    view.slideshow.note_generating("id-run", _png_bytes())
    _settle(view)

    assert not view.slideshow.holds("id-run")


def test_locking_a_slide_being_made_asks_for_no_enhancement(qtbot, tmp_path):
    # There is no file yet to make a better version of; the lock still holds.
    asked = []
    view = _view(qtbot, [(_png(tmp_path / "a.png"), "image", "id-a")],
                 actions=SlideshowActions(enhance=lambda pid: asked.append(pid) or True))
    view.slideshow.note_generating("id-run", _png_bytes())
    _settle(view)
    _press(view, Qt.Key.Key_Right)

    _press(view, Qt.Key.Key_Down)

    assert asked == []
    assert view.slideshow.locked


def test_a_run_followed_full_screen_is_one_slide_however_many_frames_it_sends(qtbot):
    # It is already showing that generation; a second slide of it would be it twice.
    view = _following(qtbot)

    view.slideshow.note_generating("id-run", _png_bytes())
    _settle(view)

    assert len(view.slideshow._set.playlist) == 1


def test_a_slide_still_being_made_says_so(qtbot, tmp_path):
    # An early iteration looks exactly like a bad generation, so the corner says
    # which it is — the same corner an enhancement in flight speaks from.
    view = _view(qtbot, [(_png(tmp_path / "a.png"), "image", "id-a")])
    view.slideshow.note_generating("id-run", _png_bytes())
    _settle(view)

    _press(view, Qt.Key.Key_Right)

    assert view.slideshow.hud_item_note == "Generating…"


def test_the_order_pair_asks_the_gallery_for_the_side_in_that_order(qtbot):
    asked = []
    view = _view(qtbot, on_reorder=lambda items, latest: asked.append((items, latest)))

    view.slideshow.slideshow_order(latest=True)
    _settle(view)
    view.slideshow.slideshow_order(latest=False)
    _settle(view)

    assert asked == [(view.slideshow, True), (view.slideshow, False)]


def test_a_reorder_puts_the_top_of_the_new_set_on_screen_and_lets_go(qtbot, tmp_path):
    view = _view(qtbot, _named(tmp_path, "a", "b", "c"))
    view.slideshow.slideshow_step(1)
    _settle(view)
    view.slideshow.slideshow_toggle_lock()
    _settle(view)

    view.slideshow.reorder(_named(tmp_path, "e", "d"), latest=True)
    _settle(view)

    assert view.slideshow._set.playlist.current()[2] == "e"
    assert view.slideshow.locked is False
    assert view.slideshow.hud_order_label == "Latest"


def test_a_reorder_keeping_the_slide_leaves_the_picture_up_and_browses_on(qtbot, tmp_path):
    view = _view(qtbot, _named(tmp_path, "a", "b", "c"))
    view.slideshow.slideshow_step(1)
    _settle(view)
    shown = _put_up(view)

    view.slideshow.reorder(_named(tmp_path, "d", "b"), latest=True, keep_slide=True)
    _settle(view)

    assert shown == []                              # nothing new was put up
    assert view.slideshow._set.playlist.current()[2] == "b"
    assert [item[2] for item in view.slideshow._set.playlist._items] == ["d", "b"]


def test_a_configuration_rows_button_puts_it_up_and_loops_its_seeds(qtbot):
    """The other half of the column: its rows are gone to and looped, where an
    act's row narrows the slideshow instead."""
    a_configuration = Slide("c.png", "image", "id-c")
    around = lambda pid: MapNeighbors(  # noqa: E731
        column=(MapRow(a_configuration, "E629425B", configuration=True),)
        if pid == "id-a" else (),
        seeds=(Slide("d.png", "image", "id-d"),) if pid == "id-c" else ())
    view = _view(qtbot, _KEYED, actions=SlideshowActions(neighbors=around, acts=_acts))
    shown = _put_up(view)

    view.slideshow.slideshow_filter("e629425b")
    _settle(view)

    assert shown == ["id-c"]
    assert (view.slideshow.hud_act_filter, view.slideshow.hud_map().loop) == ("", "seed")


class TestMovingTheSlideshowsPanel:
    """Ctrl and the arrow keys or WASD move this slideshow's panel round the corners:
    the keys a Fun Time session gives its portrait Funestra and its landscape
    one, since a slideshow on its own can be either shape."""

    @staticmethod
    def _slideshow(qtbot, moves):
        slideshow = SlideshowView([("scene one.png", "image")], engine=FakeEngine(),
                                  shuffle=in_order,
                                  actions=SlideshowActions(move_hud=moves.append))
        qtbot.addWidget(slideshow)
        return slideshow

    @_ARROW_KEYS_OR_WASD
    def test_each_ctrl_arrow_asks_for_that_direction(self, qtbot, arrows):
        moves: list[str] = []
        slideshow = self._slideshow(qtbot, moves)

        for key in (arrows.left, arrows.right, arrows.up, arrows.down):
            slideshow.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key,
                                              Qt.KeyboardModifier.ControlModifier))

        assert moves == ["left", "right", "up", "down"]

    @_ARROW_KEYS_OR_WASD
    def test_an_arrow_with_no_ctrl_asks_for_no_move(self, qtbot, arrows):
        moves: list[str] = []
        slideshow = self._slideshow(qtbot, moves)

        slideshow.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, arrows.right,
                                          Qt.KeyboardModifier.NoModifier))

        assert moves == []


# --- a picture that something is being made of -------------------------------

def test_a_slideshow_opened_while_a_picture_of_it_is_being_enhanced_opens_on_it(qtbot):
    view = _view(qtbot, _THREE, enhancing={"id-c": "running"})

    assert _media_on_screen(view) == "c.png"


def test_a_picture_being_enhanced_holds_the_screen_for_half_the_pace(qtbot):
    view = _view(qtbot, _THREE, enhancing={"id-a": "running"})

    assert _engine(view).held_for == 2


def test_a_picture_being_made_makes_its_move_at_the_ordinary_pace(qtbot):
    view = _view(qtbot, _THREE, enhancing={"id-a": "running"})

    assert _engine(view).pace_s == 4


def test_the_better_version_landing_on_screen_holds_for_the_whole_pace(qtbot):
    view = _view(qtbot, _THREE, enhancing={"id-a": "running"})

    view.slideshow.note_enhanced("id-a", "a_enhanced.png")
    _settle(view)

    assert _media_on_screen(view) == "a_enhanced.png"
    assert (_engine(view).pace_s, _engine(view).held_for) == (4, None)


def test_a_picture_still_being_generated_holds_the_screen_for_half_the_pace(qtbot):
    view = _view(qtbot, _THREE)
    view.slideshow.note_generating("id-run", _png_bytes())
    _settle(view)
    view.slideshow.slideshow_step(1)
    _settle(view)

    assert (view.slideshow._set.playlist.current()[2], _engine(view).held_for) == ("id-run", 2)


def test_a_frozen_room_holds_a_picture_still_being_generated_until_it_thaws(qtbot):
    view = _view(qtbot, _THREE)
    view.slideshow.note_generating("id-run", _png_bytes())
    _settle(view)
    view.slideshow.slideshow_step(1)
    _settle(view)

    view.slideshow.set_paused(True)
    _settle(view)
    frozen = (_engine(view).paused, view.slideshow._set.playlist.current()[2])
    view.slideshow.set_paused(False)
    _settle(view)

    assert frozen == (True, "id-run")
    assert (_engine(view).paused, _engine(view).held_for) == (False, 2)


def test_a_slideshow_picked_back_up_opens_on_what_is_being_made_then_where_it_left_off(qtbot):
    closed = _view(qtbot, _THREE)
    closed.slideshow.slideshow_step(1)
    _settle(closed)
    reopened = _view(qtbot, _THREE, enhancing={"id-c": "running"})

    assert reopened.slideshow.resume(closed.slideshow.state()) is True

    assert reopened.slideshow._set.playlist.current()[2] == "id-c"
    assert ahead(reopened.slideshow._set.playlist, 1)[2] == "id-b"


def test_a_slideshow_picked_back_up_on_a_locked_slide_stays_on_it(qtbot):
    closed = _view(qtbot, _THREE)
    closed.slideshow.slideshow_step(1)
    _settle(closed)
    _press(closed, Qt.Key.Key_Down)
    reopened = _view(qtbot, _THREE, enhancing={"id-c": "running"})

    reopened.slideshow.resume(closed.slideshow.state())
    _settle(reopened)

    assert reopened.slideshow._set.playlist.current()[2] == "id-b"
    assert reopened.slideshow.locked


def test_the_version_the_last_slideshow_was_on_is_not_stepped_on_what_is_being_made(
        qtbot, tmp_path):
    a, a_base, c, c_base = (_png(tmp_path / n) for n in ("a.png", "a0.png", "c.png", "c0.png"))
    items = [(a, "image", "id-a"), (c, "image", "id-c")]
    levels = {a: [(a, "image", "Enhancement 1/1"), (a_base, "image", "Original")],
              c: [(c, "image", "Enhancement 1/1"), (c_base, "image", "Original")]}
    closed = _view(qtbot, items)
    closed.slideshow.set_levels(levels)
    _settle(closed)
    _shift(closed, Qt.Key.Key_Right)
    reopened = _view(qtbot, items, enhancing={"id-c": "running"})
    reopened.slideshow.set_levels(levels)
    _settle(reopened)

    reopened.slideshow.resume(closed.slideshow.state())
    _settle(reopened)

    assert _media_on_screen(reopened) == c


def test_a_slideshow_told_to_lead_with_what_is_being_made_puts_it_on_screen_now(qtbot):
    view = _view(qtbot, _THREE)
    view.slideshow.note_generating("id-run", _png_bytes())
    _settle(view)

    view.slideshow.lead_with_what_is_being_made()
    _settle(view)

    assert view.slideshow._set.playlist.current()[2] == "id-run"
    assert _frame_up(view) == _png_bytes()


def test_a_picture_enhanced_during_the_slideshow_steps_its_versions_without_reopening(
        qtbot, tmp_path):
    a, better, b = (_png(tmp_path / n) for n in ("a.png", "a_enhanced.png", "b.png"))
    view = _view(qtbot, [(a, "image", "id-a"), (b, "image", "id-b")])
    view.slideshow.set_levels({})
    _settle(view)
    view.slideshow.note_enhanced("id-a", better)
    _settle(view)

    view.slideshow.add_levels({better: [(better, "image", "Enhancement 1/1"), (a, "image", "Original")]})
    _settle(view)
    _shift(view, Qt.Key.Key_Right)

    assert _media_on_screen(view) == a
    assert view.slideshow.hud_item_note == "Original"


def test_a_picture_being_enhanced_shows_the_enhancement_as_it_comes_in(qtbot):
    view = _view(qtbot, _THREE)
    frame = _png_bytes()

    view.slideshow.note_enhancing({"id-a": "running"}, frames={"id-a": frame})
    _settle(view)

    assert _frame_up(view) == frame


def test_each_new_frame_of_the_enhancement_replaces_the_last(qtbot):
    view = _view(qtbot, _THREE)
    view.slideshow.note_enhancing({"id-a": "running"}, frames={"id-a": _png_bytes()})
    _settle(view)
    newer = _png_bytes(color=(200, 40, 40))

    view.slideshow.note_enhancing({"id-a": "running"}, frames={"id-a": newer})
    _settle(view)

    assert _frame_up(view) == newer


def test_the_finished_enhancement_takes_the_place_of_its_frames(qtbot):
    view = _view(qtbot, _THREE)
    view.slideshow.note_enhancing({"id-a": "running"}, frames={"id-a": _png_bytes()})
    _settle(view)

    view.slideshow.note_enhanced("id-a", "a_enhanced.png")
    _settle(view)

    assert _media_on_screen(view) == "a_enhanced.png"


def test_an_enhancement_that_starts_on_screen_carries_the_pictures_move_onto_its_frames(qtbot):
    view = _view(qtbot, _THREE)

    view.slideshow.note_enhancing({"id-a": "running"}, frames={"id-a": _png_bytes()})
    _settle(view)

    engine = _engine(view)
    assert (engine.opened, len(engine.swapped)) == ([Path("a.png")], 1)


def test_a_picture_come_to_while_it_is_enhanced_opens_on_its_newest_frame(qtbot):
    view = _view(qtbot, _THREE)
    frame_of_b = _png_bytes(color=(30, 160, 60))
    view.slideshow.note_enhancing({"id-b": "running"}, frames={"id-b": frame_of_b})
    _settle(view)

    _runs_out(view)

    assert view.slideshow._set.playlist.current()[2] == "id-b"
    assert _frame_up(view) == frame_of_b


def test_a_slideshow_following_a_run_stays_on_it_when_its_pace_runs_out(qtbot, tmp_path):
    a, b, c = (_png(tmp_path / n) for n in ("a.png", "b.png", "c.png"))
    view = _following(qtbot, [(a, "image", "id-a"), (b, "image", "id-b"), (c, "image", "id-c")], shuffle=in_order)

    _runs_out(view)
    still_following = _frame_up(view) == _png_bytes()
    _press(view, Qt.Key.Key_Right)

    assert still_following
    assert _media_on_screen(view) == a


def test_a_locked_picture_being_enhanced_is_held_by_the_lock_not_moved_on_early(qtbot):
    view = _view(qtbot, _KEYED,
                 actions=SlideshowActions(enhance=lambda prompt_id: True))
    _press(view, Qt.Key.Key_Down)
    view.slideshow.note_enhancing({"id-a": "running"}, frames={"id-a": _png_bytes()})
    _settle(view)

    _runs_out(view)
    _time_passes(view, 10)

    assert (_engine(view).pace_s, _engine(view).loop_file) == (4, True)
    assert view.slideshow._set.playlist.current()[2] == "id-a"


def test_a_cancelled_enhancement_puts_the_picture_itself_back(qtbot):
    view = _view(qtbot, _THREE)
    view.slideshow.note_enhancing({"id-a": "running"}, frames={"id-a": _png_bytes()})
    _settle(view)

    view.slideshow.note_enhancing({})
    _settle(view)

    assert _media_on_screen(view) == "a.png"
    assert _frame_up(view) is None


def test_a_picture_whose_enhancement_stops_comes_back_on_the_move_it_was_on(qtbot):
    view = _view(qtbot, _THREE)
    engine = _engine(view)
    view.slideshow.note_enhancing({"id-a": "running"}, frames={"id-a": _png_bytes()})
    _settle(view)
    opened_while_it_was_made = len(engine.opened)

    view.slideshow.note_enhancing({})
    _settle(view)

    assert len(engine.opened) == opened_while_it_was_made
    assert engine.swapped[-1] == Path("a.png")


def test_a_picture_whose_enhancement_stops_takes_the_whole_pace_again(qtbot):
    view = _view(qtbot, _THREE, enhancing={"id-a": "running"})
    view.slideshow.note_enhancing({"id-a": "running"}, frames={"id-a": _png_bytes()})
    _settle(view)

    view.slideshow.note_enhancing({})
    _settle(view)

    assert _engine(view).held_for is None


def test_a_picture_whose_enhancement_is_waiting_shows_as_itself(qtbot):
    view = _view(qtbot, _THREE)

    view.slideshow.note_enhancing({"id-a": "queued"}, frames={})
    _settle(view)

    assert _media_on_screen(view) == "a.png"
    assert _frame_up(view) is None


def test_a_version_stepped_to_while_the_picture_is_enhanced_stays_up(qtbot, tmp_path):
    a, a_base = (_png(tmp_path / n) for n in ("a.png", "a0.png"))
    view = _view(qtbot, [(a, "image", "id-a"), ("b.png", "image", "id-b")])
    view.slideshow.set_levels({a: [(a, "image", "Enhancement 1/1"), (a_base, "image", "Original")]})
    _settle(view)
    view.slideshow.note_enhancing({"id-a": "running"}, frames={"id-a": _png_bytes()})
    _settle(view)

    _shift(view, Qt.Key.Key_Right)
    view.slideshow.note_enhancing({"id-a": "running"}, frames={"id-a": _png_bytes(color=(1, 2, 3))})
    _settle(view)

    assert _media_on_screen(view) == a_base


def test_a_closing_slideshow_is_off_the_screen_before_its_engine_lets_go(qtbot):
    seen = {}

    class RecordingEngine(FakeEngine):
        def close(self) -> None:
            super().close()
            seen["slideshow visible"] = view.isVisible()

    view = SlideshowView(_ITEMS, engine=RecordingEngine(), shuffle=in_order)
    qtbot.addWidget(view)
    view.show()

    view.close()

    assert seen == {"slideshow visible": False}


def test_a_run_the_slideshow_opened_on_comes_back_finished_after_the_picture_on_screen(qtbot):
    view = _view(qtbot, [("a.png", "image", "id-a"), ("b.png", "image", "id-b")])
    view.slideshow.note_generating("id-run", _png_bytes())
    _settle(view)
    view.slideshow.lead_with_what_is_being_made()
    _settle(view)
    assert view.slideshow._set.playlist.current()[2] == "id-run"
    _runs_out(view)
    moved_on_to = _media_on_screen(view)

    view.slideshow.note_added("run.png", "image", "id-run")
    _settle(view)
    _runs_out(view)

    assert moved_on_to == "a.png"
    assert _media_on_screen(view) == "run.png"


def test_a_finished_picture_comes_up_before_the_next_runs_first_frames(qtbot):
    view = _view(qtbot, _THREE)
    view.slideshow.note_generating("id-first", _png_bytes())
    _settle(view)
    _runs_out(view)
    _runs_out(view)

    view.slideshow.note_added("first.png", "image", "id-first")
    _settle(view)
    view.slideshow.note_generating("id-second", _png_bytes(color=(200, 40, 40)))
    _settle(view)
    _runs_out(view)
    first_up = _media_on_screen(view)
    _runs_out(view)

    assert first_up == "first.png"
    assert view.slideshow._set.playlist.current()[2] == "id-second"


def test_locking_a_picture_shows_its_enhancement_on_the_move_to_the_finished_picture(qtbot):
    view = _view(qtbot, _KEYED,
                 actions=SlideshowActions(enhance=lambda prompt_id: True))
    whole, face, hand = (_png_bytes(color=color) for color in ((1, 2, 3), (4, 5, 6), (7, 8, 9)))
    engine = _engine(view)

    _press(view, Qt.Key.Key_Down)
    for frame in (whole, face, hand):
        view.slideshow.note_enhancing({"id-a": "running"}, frames={"id-a": frame})
        _settle(view)
    each_on_the_pictures_move = [swapped.read_bytes() for swapped in engine.swapped]
    _runs_out(view)
    held_under_the_lock = (view.slideshow._set.playlist.current()[2], _frame_up(view))
    view.slideshow.note_enhanced("id-a", "a_enhanced.png")
    _settle(view)

    assert each_on_the_pictures_move == [whole, face, hand]
    assert held_under_the_lock == ("id-a", hand)
    assert _media_on_screen(view) == "a_enhanced.png"


def test_an_enhancement_landing_on_a_locked_picture_carries_on_the_frames_move(qtbot):
    view = _view(qtbot, _KEYED,
                 actions=SlideshowActions(enhance=lambda prompt_id: True))
    engine = _engine(view)
    _press(view, Qt.Key.Key_Down)
    view.slideshow.note_enhancing({"id-a": "running"}, frames={"id-a": _png_bytes()})
    _settle(view)
    opened_while_it_was_made = len(engine.opened)

    view.slideshow.note_enhanced("id-a", "a_enhanced.png")
    _settle(view)
    view.slideshow.note_enhancing({}, frames={})
    _settle(view)

    assert len(engine.opened) == opened_while_it_was_made
    assert engine.swapped[-1] == Path("a_enhanced.png")
    assert _media_on_screen(view) == "a_enhanced.png"


def test_an_enhancement_landing_on_an_older_version_stepped_to_counts_from_the_new_one(
        qtbot, tmp_path):
    a, a_base, better = (_png(tmp_path / n) for n in ("a.png", "a0.png", "a2.png"))
    view = _view(qtbot, [(a, "image", "id-a"), ("b.png", "image", "id-b")])
    view.slideshow.set_levels({a: [(a, "image", "Enhancement 1/1"), (a_base, "image", "Original")]})
    _settle(view)
    _shift(view, Qt.Key.Key_Right)

    view.slideshow.note_enhanced("id-a", better)
    _settle(view)
    view.slideshow.add_levels({better: [(better, "image", "Enhancement 2/2"),
                              (a, "image", "Enhancement 1/2"), (a_base, "image", "Original")]})

    assert _media_on_screen(view) == better
    assert view.slideshow.hud_item_note == "Enhancement 2/2"


def test_a_funestra_that_opens_after_the_pass_is_handed_over_takes_the_pace(qtbot):
    view = SlideshowView(_ITEMS, shuffle=lambda order: None, clock=_Clock())
    qtbot.addWidget(view)
    assert _engine(view) is None
    engine = FakeEngine()
    view._pane._engine_for = lambda wid: engine

    view._pane._open_if_ready()

    assert engine.pace_s == 4
