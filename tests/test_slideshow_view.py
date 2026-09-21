"""SlideshowView — the one fullscreen player: show, advance, lock, neighbors, keys.

Also everything the retired second full-screen viewer used to do on its own, which
this view now covers because a double-clicked picture opens it at a pace of
nought: paging a folder in order, stepping an image's versions, following a
generation that is still being made, and driving the OSR2 off the clip on screen.
"""
from __future__ import annotations

from io import BytesIO

from PIL import Image
from PyQt6.QtCore import QEvent, QPointF, QSize, Qt
from PyQt6.QtGui import QIcon, QKeyEvent, QMouseEvent, QPixmap, QResizeEvent
from PyQt6.QtWidgets import QApplication, QWidget
from shared_ui.colors import AMBER, GREEN, RED, TEXT_PRIMARY

from origenerator.funscript import (
    legacy_funscript_path_for,
    synthesize_actions,
    write_funscript,
)
from origenerator.gui.show_wiring import HudFacts, ShowActions
from origenerator.gui.slideshow_pace import SlideshowPace
from origenerator.gui.slideshow_view import SlideshowView
from origenerator.gui.stylesheet import dress_application
from origenerator.gui.toast import ERROR, FAVORITE, WARNING, Toast
from origenerator.gui.toast import TOP_MARGIN as TOAST_TOP_MARGIN
from origenerator.slideshow import LIVE, Slide, in_order
from tests.motion_doubles import FakeMotion
from tests.show_surface_fakes import FakeEngine

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
    view = SlideshowView(items, engine=FakeEngine(), **_wired(kw))
    qtbot.addWidget(view)
    return view


def _will_move_on(view) -> bool:
    """Whether the show pages on by itself when the item on screen runs out.

    The engine holds a picture for the pace and ends it the way it ends a
    finished clip, so there is no clock of the view's own to ask any more:
    what decides is the same three things that decided whether one was armed
    — the room is not frozen, the slide is not locked, and the pace is not
    nought."""
    return (not view._paused and not view._playlist.holding()
            and bool(view._dwell_s))


def _wired(kw: dict) -> dict:
    """The show takes its HUD facts and its gallery actions as two records;
    these cases name the facts and the actions flat, the way the words read."""
    facts = {k: kw.pop(k) for k in ("order_label", "favorite_ids", "enhanced_ids") if k in kw}
    if facts:
        kw["hud"] = HudFacts(**facts)
    acts = {k[3:]: kw.pop(k) for k in list(kw) if k.startswith("on_")}
    if acts:
        kw["actions"] = ShowActions(**acts)
    return kw



def _named(tmp_path, *names):
    return [(_png(tmp_path / f"{name}.png"), "image", name, None) for name in names]


def test_the_enhanced_switch_narrows_the_pass_and_keeps_the_slide_showing(qtbot, tmp_path):
    # A switch is a narrowing of what you are looking through, not a new show:
    # taking the picture away as well would make the switch impossible to try.
    view = _view(qtbot, _named(tmp_path, "a", "b", "c"), enhanced_ids={"b", "c"})
    view.step(1)
    assert view._playlist.current()[2] == "b"

    assert view.toggle_enhanced_mode() is True

    assert view.hud_enhanced_mode is True
    assert [item[2] for item in view._playlist._items] == ["b", "c"]
    assert view._playlist.current()[2] == "b"     # still the one on screen
    assert view._counter.text().startswith("1 / 2")

    assert view.toggle_enhanced_mode() is True     # and back to all of them
    assert view.hud_enhanced_mode is False
    assert len(view._playlist) == 3
    assert view._playlist.current()[2] == "b"


def test_a_switch_that_takes_the_slide_away_moves_to_what_is_left(qtbot, tmp_path):
    view = _view(qtbot, _named(tmp_path, "a", "b", "c"), enhanced_ids={"b", "c"})
    assert view._playlist.current()[2] == "a"

    view.set_enhanced_mode(True)

    assert view._playlist.current()[2] == "b"


def test_a_switch_that_would_leave_nothing_is_refused(qtbot, tmp_path):
    # An empty show is not a mode: the button stays dark and the set stays whole.
    view = _view(qtbot, _named(tmp_path, "a", "b"))

    assert view.set_enhanced_mode(True) is False

    assert view.hud_enhanced_mode is False
    assert len(view._playlist) == 2


def test_both_switches_together_keep_what_answers_both(qtbot, tmp_path):
    view = _view(qtbot, _named(tmp_path, "a", "b", "c"),
                 favorite_ids={"a", "b"}, enhanced_ids={"b", "c"})

    view.toggle_favorites_filter()
    view.toggle_enhanced_mode()

    assert [item[2] for item in view._playlist._items] == ["b"]
    assert view.clear_modes() is True              # the way out of both at once
    assert (view.hud_favorites_filter, view.hud_enhanced_mode) == (False, False)
    assert len(view._playlist) == 3


def test_a_narrowed_show_takes_in_only_what_passes_its_switches(qtbot, tmp_path):
    # The show keeps up with the folder it plays; the switches decide that too,
    # or a narrowed show would fill back up with the very items it left out.
    view = _view(qtbot, _named(tmp_path, "a", "b"), enhanced_ids={"a"})
    view.set_enhanced_mode(True)

    view.note_added(_png(tmp_path / "c.png"), "image", "c", None)                 # plain
    view.note_added(_png(tmp_path / "d.png"), "image", "d", None, enhanced=True)  # enhanced

    assert sorted(item[2] for item in view._playlist._items) == ["a", "d"]
    view.clear_modes()
    assert sorted(item[2] for item in view._playlist._items) == ["a", "b", "c", "d"]


def test_an_enhancement_landing_brings_its_item_into_an_enhanced_only_pass(qtbot, tmp_path):
    view = _view(qtbot, _named(tmp_path, "a", "b"), enhanced_ids={"a"})
    view.set_enhanced_mode(True)
    assert [item[2] for item in view._playlist._items] == ["a"]

    better = _png(tmp_path / "b_enhanced.png")
    view.note_enhanced("b", better, "image")

    assert sorted(item[2] for item in view._playlist._items) == ["a", "b"]
    assert next(item for item in view._playlist._items if item[2] == "b")[0] == better
    view.clear_modes()
    assert next(item for item in view._playlist._items if item[2] == "b")[0] == better


def test_a_culled_slide_stays_gone_when_a_switch_comes_off(qtbot, tmp_path):
    view = _view(qtbot, _named(tmp_path, "a", "b", "c"), enhanced_ids={"a", "b"})
    view.set_enhanced_mode(True)
    assert view._playlist.current()[2] == "a"

    view.cull()
    view.clear_modes()

    assert sorted(item[2] for item in view._playlist._items) == ["b", "c"]


def test_holding_a_slide_makes_it_a_favorite_the_switch_can_see(qtbot, tmp_path):
    # Down favorites the slide; the star readout and F-mode follow, not only the
    # database the gallery writes.
    favorite = []
    view = _view(qtbot, _named(tmp_path, "a", "b"), on_favorite=favorite.append)
    assert view.hud_is_favorite is False

    view.toggle_hold()

    assert favorite == ["a"]
    assert view.hud_is_favorite is True
    assert view.set_favorites_filter(True) is True
    assert [item[2] for item in view._playlist._items] == ["a"]


def test_reset_drops_both_switches(qtbot, tmp_path):
    view = _view(qtbot, _named(tmp_path, "a", "b", "c"),
                 favorite_ids={"a"}, enhanced_ids={"a"})
    view.toggle_favorites_filter()
    view.toggle_enhanced_mode()
    assert len(view._playlist) == 1

    view.reset_in_place()

    assert (view.hud_favorites_filter, view.hud_enhanced_mode) == (False, False)
    assert len(view._playlist) == 3


def test_a_show_following_a_running_generation_has_no_set_to_narrow(qtbot, tmp_path):
    # It is watching one thing being made; the frames are not a set.
    view = _view(qtbot, [], frame=_png_bytes())
    assert view.is_live()

    assert view.set_enhanced_mode(True) is False

    assert view.is_live()
    assert len(view._playlist) == 0


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
    assert view._playlist.current() == Slide("a.png", "image")
    assert view._pane.is_showing_video() is False


def test_right_and_left_navigate(qtbot):
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Right)
    assert view._playlist.current() == Slide("b.mp4", "video")
    assert view._pane.is_showing_video() is True
    _press(view, Qt.Key.Key_Left)
    assert view._playlist.current() == Slide("a.png", "image")


def test_a_finished_video_advances_to_the_next(qtbot):
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Right)          # -> the video
    view._pane.media_ended.emit()        # it played through
    assert view._playlist.current() == Slide("c.png", "image")


def test_a_locked_video_replays_instead_of_advancing(qtbot):
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Right)          # -> the video
    _press(view, Qt.Key.Key_Down)           # lock it: repeat-one, as Fun Time's is
    view._pane.media_ended.emit()
    assert view._playlist.current() == Slide("b.mp4", "video")  # stayed put
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
    assert view._playlist.current() == Slide("b.mp4", "video")
    assert "locked" not in view._counter.text()

    _press(view, Qt.Key.Key_Down)
    _press(view, Qt.Key.Key_Left)           # and back the other way
    assert not view._playlist.locked
    assert view._playlist.current() == Slide("a.png", "image")


def test_the_consoles_transport_releases_the_lock_too(qtbot):
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Down)
    view.show_step(1)                     # the console's transport, not the key
    assert not view.locked
    assert view._playlist.current() == Slide("b.mp4", "video")


def test_a_new_set_played_into_an_open_show_starts_it_over_on_that_set(qtbot):
    # Standalone the monitor holds one show, so a second set asked for while
    # this one is up arrives here rather than in a window of its own: it plays
    # the new set from the top, the way a show opened on it would.
    view = _view(qtbot, [("a.png", "image", "id-a")])

    view.play([("b.png", "image", "id-b"), ("c.png", "image", "id-c")],
              shuffle=in_order)

    assert view._playlist.current() == Slide("b.png", "image", "id-b")
    assert [slide.path for slide in view._set.playlist.in_play_order()] == ["b.png", "c.png"]


def test_a_new_set_played_in_drops_the_switches_the_last_one_left_on(qtbot):
    # A fresh show opens with neither switch on, so a re-pointed one does too:
    # the favorites filter belonged to the set it was narrowing, and carrying
    # it over would hide most of a set nobody had narrowed.
    view = _view(qtbot, [("a.png", "image", "id-a")], favorite_ids={"id-a"})
    view.toggle_favorites_filter()
    assert view.hud_favorites_filter

    view.play([("b.png", "image", "id-b")], shuffle=in_order)

    assert not view.hud_favorites_filter
    assert not view.hud_enhanced_mode


def test_culling_releases_the_lock(qtbot):
    items = [("a.png", "image", "id-a"), ("b.png", "image", "id-b")]
    view = SlideshowView(items, engine=FakeEngine(), shuffle=lambda order: None,
                         actions=ShowActions(delete=lambda prompt_id: None))
    qtbot.addWidget(view)
    _press(view, Qt.Key.Key_Down)
    _press(view, Qt.Key.Key_Up)             # the held slide is the one condemned
    assert not view._playlist.locked
    assert _will_move_on(view)   # so the rest keeps rotating


def test_space_drives_the_shared_motion_not_the_lock(qtbot):
    # Space belongs to the app-global OSR2 motion everywhere; locking the
    # slideshow is Down. The device rides on the show's one panel.
    motion = FakeMotion()
    view = SlideshowView(_ITEMS, engine=FakeEngine(), shuffle=lambda order: None,
                         motion=motion)
    qtbot.addWidget(view)
    assert view.hud_device is not None  # the device half of the panel is there
    _press(view, Qt.Key.Key_Space)
    assert ("toggle", True) in motion.calls
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
    view = SlideshowView(items, engine=FakeEngine(), shuffle=lambda order: None,
                         actions=ShowActions(delete=deleted.append))
    qtbot.addWidget(view)
    assert view._playlist.current()[2] == "id-a"

    _press(view, Qt.Key.Key_Up)

    assert deleted == ["id-a"]                     # culled via the delete act
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
    view = SlideshowView(items, engine=FakeEngine(), shuffle=lambda order: None)
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
    view = SlideshowView(items, engine=FakeEngine(), shuffle=lambda order: None)
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
    view = SlideshowView([("a.png", "image", "id-a")], engine=FakeEngine(),
                         shuffle=lambda order: None, actions=ShowActions(delete=deleted.append))
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
    view = SlideshowView(items, engine=FakeEngine(), shuffle=lambda order: None)
    qtbot.addWidget(view)
    view.resize(800, 600)

    left, right = view._neighbors._labels
    assert view._neighbors._sources == (items[2][0], items[1][0])  # c before, b ahead
    assert not left.pixmap().isNull() and not right.pixmap().isNull()

    _press(view, Qt.Key.Key_Right)  # onto b: a before it now, c ahead
    assert view._neighbors._sources == (items[0][0], items[2][0])


def test_a_video_neighbor_falls_back_to_its_thumbnail(qtbot, tmp_path):
    thumb = _png(tmp_path / "thumb.png")
    items = [("a.png", "image", "id-a"), ("b.mp4", "video", "id-b", thumb)]
    view = SlideshowView(items, engine=FakeEngine(), shuffle=lambda order: None)
    qtbot.addWidget(view)

    # Two items, so the clip is both what's before and what's ahead — and it's
    # drawn as its stored still, the only thing a video can show small.
    assert view._neighbors._sources == (thumb, thumb)


def test_a_single_item_slideshow_shows_no_neighbors(qtbot, tmp_path):
    view = SlideshowView([(_png(tmp_path / "only.png"), "image", "id")],
                         engine=FakeEngine(), shuffle=lambda order: None)
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
    view = _view(qtbot, _KEYED, actions=ShowActions(enhance=lambda pid: asked.append(pid) or True))

    _press(view, Qt.Key.Key_Down)

    assert asked == ["id-a"]
    assert view._playlist.locked
    # In the line until the gallery says otherwise — a launch is a place in the
    # queue, not a picture being made.
    assert view._note.text() == "Enhancement queued"


def test_releasing_the_hold_asks_for_nothing(qtbot):
    asked = []
    view = _view(qtbot, _KEYED, actions=ShowActions(enhance=lambda pid: asked.append(pid) or True))
    _press(view, Qt.Key.Key_Down)   # hold
    _press(view, Qt.Key.Key_Down)   # release
    assert asked == ["id-a"]        # only the stop asked, not the resume


def test_the_gallery_can_refuse_and_nothing_is_claimed(qtbot):
    # It already has a version at these settings, or it is a video: the refusal
    # comes from the side that holds the settings, and the corner stays quiet.
    view = _view(qtbot, _KEYED, actions=ShowActions(enhance=lambda pid: False))
    _press(view, Qt.Key.Key_Down)
    assert view._note.isHidden()


def test_the_loop_key_with_nothing_to_loop_is_the_lock_and_always_enhances(qtbot):
    # E and Home are the loop key, on both of the keys a session gives its two
    # satellites; with nothing on either axis of the map the press is the
    # lock — Down's whole gesture, the enhancement included, with no switch to
    # turn that off any more — and the next press lets go, so the key is never
    # a trap.
    asked = []
    view = _view(qtbot, _KEYED, actions=ShowActions(enhance=lambda pid: asked.append(pid) or True))

    _press(view, Qt.Key.Key_E)
    assert view._playlist.locked and asked == ["id-a"]
    assert view._note.text() == "Locked"

    _press(view, Qt.Key.Key_Home)
    assert not view._playlist.locked
    assert view._note.text() == "Unlocked"


def _around(prompt_id):
    from origenerator.gui.show_map import MapNeighbors, MapRow

    if prompt_id != "id-a":
        return MapNeighbors()
    other_act = Slide("c.png", "image", "id-c")
    return MapNeighbors(seeds=(Slide("b.png", "image", "id-b"),),
                        column=(MapRow(other_act, "dawn"),), label="fox",
                        group=(other_act,))


def test_the_loop_key_loops_the_seed_row_then_the_config_column_then_stops(qtbot):
    browsing = [*_KEYED, ("z.png", "image", "id-z")]     # more than one row, so nothing loops yet
    view = _view(qtbot, browsing, actions=ShowActions(neighbors=_around))

    _press(view, Qt.Key.Key_E)
    assert view.hud_map().loop == "seed"
    assert [item[2] for item in view._playlist._items] == ["id-a", "id-b"]
    assert view._note.text() == "Looping seeds: 2"

    _press(view, Qt.Key.Key_E)
    assert view.hud_map().loop == "action"
    assert [item[2] for item in view._playlist._items] == ["id-a", "id-c"]

    _press(view, Qt.Key.Key_E)
    assert view.hud_map().loop == ""
    assert [item[2] for item in view._playlist._items] == ["id-a", "id-b", "id-z"]  # its own set
    assert view._note.text() == "Loop off"


def _put_up(view) -> list:
    shown = []
    view.media_changed.connect(lambda: shown.append(view._playlist.current()[2]))
    return shown


def _acts(prompt_ids):
    named_for = {"id-a": "Source image, alpha", "id-b": "beta"}
    return {prompt_id: named_for.get(prompt_id, "") for prompt_id in prompt_ids}


def test_a_rows_button_narrows_the_show_to_that_act_without_redrawing_what_shows_it(qtbot):
    view = _view(qtbot, _KEYED, actions=ShowActions(acts=_acts))
    shown = _put_up(view)

    view.show_filter("source_image,_alpha")

    assert (view.hud_act_filter, view.pass_size()) == ("source image, alpha", 1)
    assert shown == []
    assert view._note.text() == "Filter: 'source image, alpha' (1)"


def test_a_filter_past_the_slide_on_screen_puts_up_what_is_left(qtbot):
    view = _view(qtbot, _KEYED, actions=ShowActions(acts=_acts))
    shown = _put_up(view)

    view.show_filter("beta")

    assert shown == ["id-b"]


def test_an_act_nothing_here_shows_says_so_and_moves_nothing(qtbot):
    view = _view(qtbot, _KEYED, actions=ShowActions(acts=_acts))
    shown = _put_up(view)

    view.show_filter("gamma")

    assert (shown, view.hud_act_filter) == ([], "")
    assert view._note.text() == "Filter: no matches for 'gamma'"


def test_clearing_the_filters_lifts_the_act_filter_with_the_other_two(qtbot):
    view = _view(qtbot, _KEYED, actions=ShowActions(acts=_acts))
    view.show_filter("beta")

    assert view.clear_modes() is True

    assert (view.hud_act_filter, view.pass_size()) == ("", 2)


def test_a_walk_along_the_map_puts_the_next_cell_up(qtbot):
    view = _view(qtbot, _KEYED, actions=ShowActions(neighbors=_around))
    shown = _put_up(view)

    view.show_nav("right")
    view.show_item("a.png")
    view.show_nav("down")

    assert shown == ["id-b", "id-a", "id-c"]


def test_entering_a_loop_lets_go_of_a_held_slide_as_a_player_does(qtbot):
    view = _view(qtbot, _KEYED, actions=ShowActions(neighbors=_around))
    _press(view, Qt.Key.Key_Down)                 # hold the slide on screen
    assert view.locked

    view.show_loop("seed")
    view._pane.media_ended.emit()                 # the slide that was held runs out

    assert view.locked is False
    assert view._playlist.current()[2] == "id-b"  # and the loop moves on to its next seed


def test_a_folder_played_as_a_show_opens_with_its_seed_loop_lit(qtbot):
    """The pictures of one folder are one configuration's seeds, so playing the
    folder is looping that row — and the map's loop light says so from the start."""
    view = _view(qtbot, _KEYED, actions=ShowActions(neighbors=_around))

    assert view.hud_map().loop == "seed"

    view.show_loop("")                            # the lit button, pressed
    assert view.hud_map().loop == ""


def test_up_over_a_favorite_takes_the_star_back_rather_than_the_picture(qtbot):
    # The players' "weird": a favorite loses its star and the show moves on;
    # only a picture wearing no star is condemned — so holding a slide, which
    # stars it, takes two presses of Up to undo all the way.
    unfavorited, deleted = [], []
    view = _view(qtbot, _KEYED, favorite_ids={"id-a"},
                 actions=ShowActions(unfavorite=unfavorited.append, delete=deleted.append))

    _press(view, Qt.Key.Key_Up)

    assert (unfavorited, deleted) == (["id-a"], [])
    assert view._playlist.current()[2] == "id-b"    # moved on
    assert len(view._playlist) == 2                  # and still in the set
    assert view.hud_is_favorite is False

    view.step(-1)
    _press(view, Qt.Key.Key_Up)                     # no star left to take back

    assert deleted == ["id-a"]


def test_a_slide_whose_run_is_still_in_the_line_says_queued_not_enhancing(qtbot):
    # Holding several slides sends out several runs and ComfyUI takes them one at
    # a time, so a slide the show comes back around to is usually still waiting.
    view = _view(qtbot, _KEYED, actions=ShowActions(enhance=lambda pid: True))
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
    view = _view(qtbot, _KEYED, actions=ShowActions(enhance=lambda pid: True))
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
    view = _view(qtbot, _KEYED, actions=ShowActions(enhance=lambda pid: True))
    view.note_voice_run("id-a", "🎤 fixing teeth…")

    view.note_enhancing({"id-a": "running"})

    assert "fixing teeth" in view._note.text()
    _fade(view)
    assert view._note.text() == "Enhancing…"


def test_the_enhanced_version_replaces_the_slide_when_it_lands(qtbot, tmp_path):
    view = _view(qtbot, _KEYED, actions=ShowActions(enhance=lambda pid: True))
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
    view = _view(qtbot, _KEYED, actions=ShowActions(enhance=lambda pid: True))
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
    view = _view(qtbot, _KEYED, actions=ShowActions(enhance=lambda pid: True))

    view.note_enhanced("id-elsewhere", _png(tmp_path / "other.png"))

    assert [item[0] for item in view._playlist._items] == ["a.png", "b.png"]


def test_the_upgraded_item_is_drawn_as_its_new_still_beside_the_slide(
        qtbot, tmp_path):
    # An item rides along as a small still while its neighbor is on screen; the
    # thumbnail it arrived with is of the version the swap just retired.
    view = _view(qtbot, _KEYED, actions=ShowActions(enhance=lambda pid: True))
    view.resize(800, 600)
    better_thumb = _png(tmp_path / "b_enhanced_thumb.png")

    view.note_enhanced("id-b", _png(tmp_path / "b_enhanced.png"),
                       still=better_thumb)

    assert better_thumb in view._neighbors._sources


def test_a_slideshow_with_no_enhancer_still_holds_on_down(qtbot):
    view = _view(qtbot, _KEYED)     # nothing wired to enhance with
    _press(view, Qt.Key.Key_Down)
    assert view._playlist.locked
    assert view._note.isHidden()


def test_the_enhancing_note_is_a_toast_across_the_top(qtbot):
    # Where Fun Time flashes the same kind of line over a player, and in the
    # same shape: this surface wears the players' own HUD, so what it says for
    # itself is said in the players' own toast rather than in a second dialect
    # at the far end of the screen.
    view = _view(qtbot, _KEYED, actions=ShowActions(enhance=lambda pid: True))
    view.resize(800, 600)
    _press(view, Qt.Key.Key_Down)

    note = view._note.geometry()
    assert note.top() == TOAST_TOP_MARGIN
    assert abs(note.center().x() - view.width() // 2) <= 1


def test_the_toast_wears_the_color_of_what_it_says(qtbot):
    # Red only for an error, yellow for a warning, green for the favorites, white
    # for the rest: the colors Fun Time's own toasts read in, since this is the
    # same toast.
    host = QWidget()
    qtbot.addWidget(host)
    toast = Toast(host)

    toast.say("a plain line")
    assert TEXT_PRIMARY.name() in toast.styleSheet()
    toast.say("nothing to do", kind=WARNING)
    assert AMBER.name() in toast.styleSheet()
    toast.say("it broke", kind=ERROR)
    assert RED.name() in toast.styleSheet()
    toast.say("starred", kind=FAVORITE)
    assert GREEN.name() in toast.styleSheet()


# --- the queue, in the corner this view leaves empty -------------------------

def _inflight(**kw):
    from origenerator.gui.inflight import InFlightItem, RunReading

    kw.setdefault("key", "j1")
    kw.setdefault("caption", "Alpha Workflow › a paper kite")
    kw.setdefault("status", "queued")
    kw.setdefault("reveal", lambda: None)
    reading = {k: kw.pop(k) for k in list(kw) if k in ("status", "frame", "progress", "pass_progress", "stage", "started_at", "typical_seconds")}
    return InFlightItem(reading=RunReading(**reading), **kw)


def test_the_queue_rides_along_in_the_shows_lower_left(qtbot):
    # The lower strip that normally carries it is under this view, and a show
    # is when the queue stops moving: its videos are held until it ends.
    view = _view(qtbot)
    view.resize(1920, 1080)
    QApplication.sendEvent(view, QResizeEvent(QSize(1920, 1080), QSize(640, 480)))
    view.set_queue([_inflight(status="running", typical_seconds=30, job_kind="Image"),
                    _inflight(key="j2", typical_seconds=600, job_kind="Video",
                              held=True)])

    plate = view._queue.geometry()
    assert view._queue.keys() == ["j1", "j2"]        # the rows themselves
    assert view._queue._running.key == "j1"  # and the live half
    assert plate.left() < view.width() // 2      # left…
    assert plate.top() > view.height() // 2      # …and low, clear of the console
    assert not plate.intersects(view._counter.geometry())  # beside it, not over it


def test_a_show_with_nothing_in_flight_shows_no_queue_at_all(qtbot):
    view = _view(qtbot)
    view.set_queue([])
    assert view._queue.isHidden()


def test_the_queue_follows_the_shows_lower_edge_on_a_resize(qtbot):
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

def test_locking_favorites_the_item_on_screen(qtbot):
    # Holding a slide is how the user says this one is worth keeping; having said
    # it once they should not have to say it again in a second way.
    favorite = []
    items = [("a.png", "image", "gen-a", None), ("b.png", "image", "gen-b", None)]
    view = _view(qtbot, items=items, actions=ShowActions(favorite=favorite.append))

    _press(view, Qt.Key.Key_Down)

    assert view._playlist.locked
    assert favorite == ["gen-a"]


def test_letting_go_of_the_lock_does_not_unfavorite(qtbot):
    favorite = []
    items = [("a.png", "image", "gen-a", None)]
    view = _view(qtbot, items=items, actions=ShowActions(favorite=favorite.append))

    _press(view, Qt.Key.Key_Down)
    _press(view, Qt.Key.Key_Down)

    assert not view._playlist.locked
    assert favorite == ["gen-a"]  # favorited once, on the way in


def test_a_slideshow_without_a_favoriter_still_locks(qtbot):
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Down)
    assert view._playlist.locked


# --- the transport a spoken word drives, saying which way rather than flipping

def test_asking_for_a_hold_holds_and_asking_again_changes_nothing(qtbot):
    # Someone talking to a picture is asking for a state, not for the other one,
    # and cannot see the counter's padlock to know which the flip would give.
    favorite = []
    items = [("a.png", "image", "gen-a", None), ("b.png", "image", "gen-b", None)]
    view = _view(qtbot, items=items, actions=ShowActions(favorite=favorite.append))

    assert view.set_held(True) is True
    assert view.locked and favorite == ["gen-a"]

    assert view.set_held(True) is False   # already holding: nothing moved
    assert view.locked and favorite == ["gen-a"]


def test_a_spoken_hold_favorites_the_slide_like_a_pressed_one(qtbot):
    # Holding is Down's whole gesture here; a spoken hold must not quietly mean
    # less than a pressed one.
    favorite = []
    items = [("a.png", "image", "gen-a", None)]
    view = _view(qtbot, items=items, actions=ShowActions(favorite=favorite.append))

    view.set_held(True)

    assert favorite == ["gen-a"]


def test_asking_to_let_go_releases_only_what_was_held(qtbot):
    view = _view(qtbot)

    assert view.set_held(False) is False   # nothing was held
    view.set_held(True)
    assert view.set_held(False) is True
    assert not view.locked


def test_favoriting_the_slide_on_screen_without_holding_it(qtbot):
    favorite = []
    items = [("a.png", "image", "gen-a", None)]
    view = _view(qtbot, items=items, actions=ShowActions(favorite=favorite.append))

    assert view.favorite() is True

    assert favorite == ["gen-a"]
    assert not view.locked  # bookmarked, still moving on


def test_favoriting_says_no_when_there_is_nothing_to_favorite(qtbot):
    # A show whose items carry no generation id — or a live one with no row of
    # its own yet — has nothing to bookmark, and says so rather than seeming to.
    assert _view(qtbot).favorite() is False


def test_stepping_and_culling_are_the_arrows_own_moves(qtbot):
    culled = []
    items = [("a.png", "image", "gen-a", None), ("b.png", "image", "gen-b", None),
             ("c.png", "image", "gen-c", None)]
    view = _view(qtbot, items=items, actions=ShowActions(delete=culled.append))

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
    view._pane._on_double_click()
    assert not view.isVisible()
    assert closes == [True]  # the dismissal reaches the gallery, like Escape's


def test_a_spoken_fix_targets_the_slide_on_screen(qtbot):
    view = _view(qtbot, _KEYED)
    assert view.voice_target() == "id-a"
    _press(view, Qt.Key.Key_Right)
    assert view.voice_target() == "id-b"


def test_a_spoken_fix_answers_in_the_corner_then_reads_enhancing(qtbot):
    view = _view(qtbot, _KEYED, actions=ShowActions(enhance=lambda pid: True))
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
    assert not _will_move_on(view)
    assert view._playlist.dwell_ms() is None


def test_the_arrows_still_move_a_show_held_at_nought(qtbot):
    view = _view(qtbot, image_dwell_ms=0)
    _press(view, Qt.Key.Key_Right)
    assert view._playlist.current() == Slide("b.mp4", "video")


def test_a_clip_replays_rather_than_advancing_at_nought(qtbot):
    # Nothing moves on its own at nought — a finished clip included, which is how
    # the retired viewer's looping video behaved.
    view = _view(qtbot, image_dwell_ms=0)
    _press(view, Qt.Key.Key_Right)          # -> the video
    view._pane.media_ended.emit()
    assert view._playlist.current() == Slide("b.mp4", "video")


def test_turning_the_console_pace_up_sets_a_held_show_going(qtbot):
    # The console's clip-seconds pair is what starts a double-clicked picture
    # moving, and the number it sets is the app-wide one.
    pace = SlideshowPace(parent=None)
    view = _view(qtbot, image_dwell_ms=0, pace=pace)

    view.set_dwell_s(2)

    assert view.dwell_s == 2
    assert pace.seconds == 2
    assert _will_move_on(view)


def test_turning_up_to_the_pace_the_app_already_held_still_starts_it(qtbot):
    # The app-wide pace never moves here, so no signal comes back — the show has
    # to take the number itself or it stays frozen at nought forever.
    pace = SlideshowPace(seconds=1, parent=None)
    view = _view(qtbot, image_dwell_ms=0, pace=pace)

    view.set_dwell_s(1)

    assert view.dwell_s == 1
    assert _will_move_on(view)


def test_the_pace_can_be_wound_back_down_to_nought(qtbot):
    view = _view(qtbot, image_dwell_ms=4000)
    view.set_dwell_s(0)
    assert view.dwell_s == 0
    assert not _will_move_on(view)


def test_a_show_opens_on_the_item_it_was_asked_for(qtbot):
    # Double-clicking the third picture in a folder opens on the third picture.
    view = _view(qtbot, start=2)
    assert view._playlist.current() == Slide("c.png", "image")
    assert view._counter.text().startswith("3 / 3")


# --- the hold a picture keeps the screen for, and what stops the clock -------
# The creep into a still is the engine's own (player_core.still_push), paced by
# the hold it was given, so the show's part is the hold it hands over and the
# freeze it hands with it.


def _engine(view):
    return view._pane._engine


def test_a_still_slide_is_handed_the_hold_it_keeps_the_screen_for(qtbot):
    view = _view(qtbot, _KEYED, image_dwell_ms=4000)

    _press(view, Qt.Key.Key_Right)

    assert _engine(view).pace == 4


def test_a_pace_of_nought_is_handed_over_as_nought(qtbot):
    # Nought holds one picture until an arrow moves it, which is what the
    # engine does with a hold of nought.
    view = _view(qtbot, _KEYED, image_dwell_ms=0)

    _press(view, Qt.Key.Key_Right)

    assert _engine(view).pace == 0


def test_holding_a_slide_leaves_it_where_it_is(qtbot):
    view = _view(qtbot, _KEYED, image_dwell_ms=4000)
    opened = list(_engine(view).loaded)

    _press(view, Qt.Key.Key_Down)           # hold it

    assert _engine(view).loaded == opened   # not opened again under the hold
    assert not _will_move_on(view)


def test_a_new_pace_reaches_a_held_slide_without_opening_it_again(qtbot):
    # Not back out to the top of the move: a held slide keeps where its creep
    # had got to, and the pace changes only how fast the rest of it goes.
    view = _view(qtbot, _KEYED, image_dwell_ms=4000)
    _press(view, Qt.Key.Key_Down)
    opened = list(_engine(view).loaded)

    view.set_dwell_s(8)

    assert _engine(view).pace == 8
    assert _engine(view).loaded == opened


def test_a_show_reopened_on_a_held_slide_opens_it_with_its_hold(qtbot):
    closed = _view(qtbot, _KEYED, image_dwell_ms=4000)
    _press(closed, Qt.Key.Key_Down)
    reopened = _view(qtbot, _KEYED, image_dwell_ms=4000)

    reopened.resume(closed.state())

    assert _engine(reopened).pace == 4
    assert not _will_move_on(reopened)


def test_a_request_holds_the_picture_and_its_release_lets_it_go(qtbot):
    view = _view(qtbot, _KEYED, image_dwell_ms=4000)

    view.hold_for_request(True, "🎤 listening…")
    assert _engine(view).paused is True

    view.hold_for_request(False)
    assert _engine(view).paused is False


def test_the_rooms_freeze_holds_it_and_its_resume_lets_it_go(qtbot):
    view = _view(qtbot, _KEYED, image_dwell_ms=4000)

    view.set_paused(True)
    assert _engine(view).paused is True

    view.set_paused(False)
    assert _engine(view).paused is False


def test_a_held_slide_is_held_again_by_a_request_and_by_the_rooms_freeze(qtbot):
    view = _view(qtbot, _KEYED, image_dwell_ms=4000)
    _press(view, Qt.Key.Key_Down)

    view.hold_for_request(True, "🎤 listening…")
    assert _engine(view).paused is True
    view.hold_for_request(False)
    assert _engine(view).paused is False

    view.set_paused(True)
    assert _engine(view).paused is True
    view.set_paused(False)
    assert _engine(view).paused is False
    assert not _will_move_on(view)


def test_a_request_released_under_the_rooms_freeze_leaves_it_held(qtbot):
    view = _view(qtbot, _KEYED, image_dwell_ms=4000)

    view.set_paused(True)
    view.hold_for_request(True, "🎤 listening…")
    view.hold_for_request(False)

    assert _engine(view).paused is True


def test_a_request_leaves_a_clip_playing_and_only_stops_the_show_moving_on(qtbot):
    """The request is about what is on screen; a clip that stopped mid-sentence
    would be answering a question nobody asked."""
    view = _view(qtbot, image_dwell_ms=4000)
    _press(view, Qt.Key.Key_Right)          # -> the video

    view.hold_for_request(True, "🎤 listening…")

    assert _engine(view).paused is False
    assert view._playlist.holding()


def _click(view):
    at = QPointF(view._pane.width() / 2, view._pane.height() / 2)
    view._pane.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, at, at, Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))


def test_a_click_pauses_a_show_standing_on_its_own_at_once_and_a_second_plays_it(qtbot):
    view = _view(qtbot, _KEYED, image_dwell_ms=4000)

    _click(view)
    assert not _will_move_on(view)
    assert _engine(view).paused is True

    _click(view)
    assert _will_move_on(view)
    assert _engine(view).paused is False


def test_a_click_on_a_hosted_show_asks_the_room_to_pause_instead_of_pausing_itself(qtbot):
    asked = []
    view = _view(qtbot, _KEYED, image_dwell_ms=4000,
                 on_omnipause=lambda: asked.append(True))

    _click(view)

    assert asked == [True]
    assert _will_move_on(view)


def test_each_slide_is_opened_in_its_own_right(qtbot):
    view = _view(qtbot, _KEYED, image_dwell_ms=4000)
    _press(view, Qt.Key.Key_Right)
    opened = len(_engine(view).loaded)

    _press(view, Qt.Key.Key_Right)

    assert len(_engine(view).loaded) == opened + 1


def test_closing_the_show_lets_the_engine_go(qtbot):
    view = _view(qtbot, _KEYED, image_dwell_ms=4000)

    view.close()

    assert _engine(view).closed is True


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
    assert view._pane._media[0] == original
    # And back round: two versions wrap, so the pair is a toggle.
    _shift(view, Qt.Key.Key_Right)
    assert view._pane._media[0] == enhanced


def test_shift_arrows_do_nothing_for_an_image_with_one_version(qtbot, tmp_path):
    lone = _png(tmp_path / "only.png")
    view = _view(qtbot, [(lone, "image", "id-a")])
    view.set_levels({})

    _shift(view, Qt.Key.Key_Right)

    # Silently nothing, rather than stepping the set when the shift was the
    # whole point of the press.
    assert view._pane._media[0] == lone


def test_stepping_to_another_image_starts_its_versions_from_the_top(qtbot, tmp_path):
    first, second, second_base = (_png(tmp_path / n) for n in
                                  ("a.png", "b.png", "b_base.png"))
    view = _view(qtbot, [(first, "image", "id-a"), (second, "image", "id-b")])
    view.set_levels({second: [(second, "image"), (second_base, "image")]})

    _press(view, Qt.Key.Key_Right)   # onto the second image
    _shift(view, Qt.Key.Key_Right)   # its own versions, from the top

    assert view._pane._media[0] == second_base


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

def _showing_a_picture(view):
    picture = view._pane._frame
    return picture is not None and not picture.isNull()


def test_opens_over_a_running_generation_showing_its_frame(qtbot):
    view = _view(qtbot, [], frame=_png_bytes())
    assert view.is_live() is True
    assert view._pane._media is None                     # no file under it yet
    assert _showing_a_picture(view)  # the streamed frame shows


def test_opened_before_the_first_frame_it_says_it_is_generating(qtbot):
    view = _view(qtbot, [])
    assert view.is_live() is True
    assert view._pane._picture.text() == "Generating…"


def test_a_later_frame_replaces_the_one_it_opened_over(qtbot):
    view = _view(qtbot, [])
    view.show_frame(_png_bytes())
    assert _showing_a_picture(view)


def test_the_landed_file_takes_over_from_the_frames(qtbot, tmp_path):
    # Watching a generation full-screen ends on the finished image, not the last
    # low-res frame it streamed.
    png = _png(tmp_path / "done.png")
    view = _view(qtbot, [], frame=_png_bytes())
    changed = []
    view.media_changed.connect(lambda: changed.append(True))

    view.show_landed((png, "image"))

    assert view._pane._media == (png, "image")
    assert view.is_live() is False
    assert changed == [True]  # a landed video is a fresh OSR2 target


def test_frames_are_ignored_once_it_has_landed(qtbot, tmp_path):
    png = _png(tmp_path / "done.png")
    view = _view(qtbot, [])
    view.show_landed((png, "image"))

    view.show_frame(_png_bytes())  # a later run's frames must not paint over it

    assert view._pane._media == (png, "image")


def test_stepping_leaves_the_live_generation_behind(qtbot, tmp_path):
    # Stepped onto a saved item, the show is no longer the run's — later frames of
    # it must not paint over what the user stepped to.
    a, b = (_png(tmp_path / n) for n in ("a.png", "b.png"))
    view = _view(qtbot, [], frame=_png_bytes())
    view.set_playlist([(a, "image", "id-a"), (b, "image", "id-b")], 0)

    _press(view, Qt.Key.Key_Right)

    assert view.is_live() is False
    assert view._pane._media == (b, "image")


def test_a_run_with_no_folder_armed_behind_it_ignores_the_arrows(qtbot):
    view = _view(qtbot, [], frame=_png_bytes())
    _press(view, Qt.Key.Key_Right)
    assert view.is_live() is True
    assert _showing_a_picture(view)


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

def test_a_streamed_frame_fits_the_screen_without_clipping(qtbot):
    # The reported "black on all four sides" was the picture left scaled at its
    # tiny pre-show size on the full screen.  A file is fitted by the engine;
    # a run's streamed frame is the one picture this app still draws itself.
    buf = BytesIO()
    Image.new("RGB", (24, 60), (10, 120, 200)).save(buf, "PNG")
    view = _view(qtbot, [], frame=buf.getvalue())
    label = view._pane._picture
    old = label.size()
    label.resize(600, 500)  # stand in for the screen the window grows to
    QApplication.sendEvent(label, QResizeEvent(QSize(600, 500), old))

    pm = label.pixmap()
    assert pm.width() <= 600 and pm.height() <= 500        # nothing clipped off
    assert pm.width() == 600 or pm.height() == 500         # as large as it fits


def test_it_plays_audio_unlike_the_muted_inline_preview(qtbot):
    # Filling the screen with a clip is deliberate, so it's heard.
    view = _view(qtbot)
    assert view._pane.audio_muted() is False


def test_a_scripted_clip_shows_its_strip(qtbot, tmp_path):
    vid = tmp_path / "c.mp4"
    write_funscript(legacy_funscript_path_for(vid),
                    synthesize_actions(2.0, hz=1.0, loop=False))
    view = _view(qtbot, [(str(vid), "video")])
    assert view._pane._strip is not None
    assert view._pane._strip._actions


def test_closing_releases_the_video_file(qtbot, tmp_path):
    # A held media handle blocks move-to-trash on Windows, so closing must drop it.
    view = _view(qtbot, [(str(tmp_path / "c.mp4"), "video")])
    view.close()
    assert view._pane.current_media_path() == ""


def test_closing_lets_the_engine_go_before_what_it_draws_into(qtbot, tmp_path):
    # A closed show is dropped by whoever held it, and a new one opening on the
    # same region drops it at once. Its engine must be finished with by then,
    # not still rendering into a framebuffer about to go under it: that was the
    # crash on every slideshow replace and every quit.
    view = _view(qtbot, [(str(tmp_path / "c.mp4"), "video")])
    view.close()
    assert view._pane._engine.closed is True


def test_a_show_wears_the_apps_icon_in_the_window_switcher(qtbot, qapp):
    # The show is a window of its own with no frame and no icon of its own, and
    # the switcher drew it a blank page until the app carried one for every
    # window it opens.
    before = qapp.windowIcon()
    qapp.setWindowIcon(QIcon())
    try:
        dress_application(qapp)

        assert not _view(qtbot).windowIcon().isNull()
    finally:
        qapp.setWindowIcon(before)


def test_releasing_a_condemned_file_lets_go_of_it(qtbot, tmp_path):
    clip = str(tmp_path / "c.mp4")
    view = _view(qtbot, [(clip, "video")])

    view.release_media([clip])

    assert view._pane.current_media_path() == ""


def test_releasing_another_file_leaves_the_show_alone(qtbot, tmp_path):
    kept = str(tmp_path / "kept.mp4")
    view = _view(qtbot, [(kept, "video")])

    view.release_media([str(tmp_path / "doomed.mp4")])

    assert view._pane.current_media_path() == kept


# --- the OSR2 drive target: the clip on screen ------------------------------

def test_osr2_drive_target_bundles_the_scripted_video(qtbot, tmp_path):
    vid = tmp_path / "c.mp4"
    write_funscript(legacy_funscript_path_for(vid),
                    synthesize_actions(2.0, hz=1.0, loop=False))
    view = SlideshowView([(str(vid), "video")], engine=FakeEngine(),
                         shuffle=lambda order: None)
    qtbot.addWidget(view)

    target = view.osr2_drive_target()

    assert target is not None
    path, tgt_player, actions = target
    # The pane itself is what the drive follows: it is what knows where the
    # clip has got to, the way the config panel's media player is there.
    assert path == str(vid) and tgt_player is view._pane and actions


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


def test_stepping_a_paused_show_still_re_aims_the_device(qtbot):
    view = _view(qtbot)
    view.set_paused(True)
    changed = []
    view.media_changed.connect(lambda: changed.append(True))

    _press(view, Qt.Key.Key_Right)

    assert changed == [True]

# --- the hold a spoken request puts on the show -----------------------------


def test_a_request_holds_the_advance_and_says_so(qtbot):
    view = _view(qtbot, _KEYED)
    assert _will_move_on(view)  # an image, dwelling

    view.hold_for_request(True, "🎤 Request: no hat…")

    assert not _will_move_on(view)
    assert view._playlist.paused
    assert "Request" in view._note.text()


def test_releasing_the_hold_resumes_the_dwell(qtbot):
    view = _view(qtbot, _KEYED)
    view.hold_for_request(True, "🎤 Request…")

    view.hold_for_request(False)

    assert _will_move_on(view)
    assert not view._playlist.paused
    assert view._note.isHidden()


def test_the_slide_stays_put_while_a_request_is_being_said(qtbot):
    # The point of the hold: the request is about this slide, so the show must
    # not page on while the sentence is still being spoken.
    view = _view(qtbot, _KEYED)
    view.hold_for_request(True, "🎤 Request…")

    view._on_media_ended()  # the clip on screen ran out mid-sentence

    assert view.voice_target() == "id-a"


def test_releasing_the_hold_leaves_a_locked_slide_locked(qtbot):
    view = _view(qtbot, _KEYED)
    view._hold_current()  # the user locked this one
    view.hold_for_request(True, "🎤 Request…")

    view.hold_for_request(False)

    assert view._playlist.locked
    assert not _will_move_on(view)  # still held — by the lock, now


def test_a_request_targets_the_slide_on_screen(qtbot):
    view = _view(qtbot, _KEYED)
    assert view.voice_target() == "id-a"
    _press(view, Qt.Key.Key_Right)
    assert view.voice_target() == "id-b"


def test_a_finished_request_answers_in_the_corner(qtbot):
    view = _view(qtbot, _KEYED)
    view.note_request("🎤 dropped “a hat” — generating")
    assert "dropped" in view._note.text()


def test_a_clip_the_backend_cannot_open_does_not_park_the_show(qtbot, tmp_path):
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
    assert view._playlist.current()[2] == "v-1"

    view._pane._engine.idle = True      # the engine opened nothing at all
    view._pane._follow_the_engine()

    qtbot.waitUntil(lambda: view._playlist.current()[2] == "i-1")


def test_an_unopenable_clip_is_stepped_past_even_while_held(qtbot, tmp_path):
    """A lock replays the clip it holds, and a pace of nought never moves on —
    both of which would hold a clip that cannot play forever.  So this one step
    happens regardless: the item stays in the set, but the screen does not stay
    black."""

    still = tmp_path / "a.png"
    Image.new("RGB", (40, 30)).save(still)
    view = _view(qtbot, [(str(tmp_path / "broken.mp4"), "video", "v-1", None),
                         (str(still), "image", "i-1", None)],
                 shuffle=in_order)
    view._playlist.toggle_lock()

    view._pane.media_unplayable.emit()

    assert view._playlist.current()[2] == "i-1"


# --- picking a closed show back up ------------------------------------------

_THREE = [("a.png", "image", "id-a"), ("b.png", "image", "id-b"),
          ("c.png", "image", "id-c")]


def test_the_state_names_the_pass_and_the_slide_it_is_on(qtbot):
    view = _view(qtbot, _THREE)
    _press(view, Qt.Key.Key_Right)

    state = view.state()

    assert state.order == ("id-a", "id-b", "id-c")
    assert state.current == "id-b"
    assert state.locked is False


def test_a_reopened_show_stands_where_the_last_one_was_closed(qtbot):
    # Closing a show is usually a detour — the folder under the picture, a fix
    # in a tab — so coming back is coming back to that picture.
    closed = _view(qtbot, _THREE)
    _press(closed, Qt.Key.Key_Right)
    _press(closed, Qt.Key.Key_Right)

    reopened = _view(qtbot, _THREE, shuffle=lambda order: order.reverse())
    assert reopened.resume(closed.state()) is True

    assert reopened._playlist.current()[2] == "id-c"
    assert reopened._pane._media[0] == "c.png"
    assert reopened._counter.text().startswith("3 / 3")


def test_a_reopened_show_carries_on_in_the_order_it_was_playing(qtbot):
    closed = _view(qtbot, _THREE, shuffle=lambda order: order.reverse())  # c, b, a
    _press(closed, Qt.Key.Key_Right)   # -> b

    reopened = _view(qtbot, _THREE)    # a fresh shuffle would lead with a
    reopened.resume(closed.state())

    _press(reopened, Qt.Key.Key_Right)
    assert reopened._playlist.current()[2] == "id-a"   # the closed show's pass


def test_a_slide_closed_under_a_hold_reopens_under_it(qtbot):
    closed = _view(qtbot, _THREE)
    _press(closed, Qt.Key.Key_Down)    # held: this is the one
    state = closed.state()
    closed.close()

    reopened = _view(qtbot, _THREE)
    reopened.resume(state)

    assert reopened._playlist.locked
    assert not _will_move_on(reopened)  # held, so nothing moves it on
    assert "locked" in reopened._counter.text()


def test_a_show_of_a_set_without_that_slide_starts_fresh(qtbot):
    # Another folder, or one the slide has since been culled from: there is
    # nowhere in here to put it, so the shuffle it opened with stands.
    closed = _view(qtbot, _THREE)
    _press(closed, Qt.Key.Key_Down)

    elsewhere = _view(qtbot, [("x.png", "image", "id-x"), ("y.png", "image", "id-y")])
    assert elsewhere.resume(closed.state()) is False

    assert elsewhere._playlist.current()[2] == "id-x"
    assert not elsewhere._playlist.locked


def test_a_reopened_show_shows_the_version_that_was_on_screen(qtbot, tmp_path):
    enhanced, original = (_png(tmp_path / n) for n in ("e1.png", "src.png"))
    levels = {enhanced: [(enhanced, "image"), (original, "image")]}
    closed = _view(qtbot, [(enhanced, "image", "id-a")])
    closed.set_levels(levels)
    _shift(closed, Qt.Key.Key_Right)   # stepped down to the original

    reopened = _view(qtbot, [(enhanced, "image", "id-a")])
    reopened.set_levels(levels)        # armed before the resume, as the gallery does
    reopened.resume(closed.state())

    assert reopened._pane._media[0] == original


def test_a_show_following_a_running_generation_resumes_nothing(qtbot):
    # It has no items of its own yet, so there is no slide in it to stand on.
    closed = _view(qtbot, _THREE)
    live = _view(qtbot, [], frame=_png_bytes())

    assert live.resume(closed.state()) is False
    assert live.is_live()


def test_the_state_read_as_a_show_closes_still_shows_its_hold(qtbot):
    # The gallery reads it from the ``closed`` signal, and the lock is dropped
    # immediately after — a slide closed under a hold has to still be held there,
    # or a reopened show would come back to it released.
    view = _view(qtbot, _THREE)
    _press(view, Qt.Key.Key_Down)
    seen = []
    view.closed.connect(lambda: seen.append(view.state()))

    view.close()

    assert seen[0].current == "id-a"
    assert seen[0].locked


# --- a generation that is still being made ----------------------------------

def test_a_run_that_starts_to_look_like_something_joins_the_show(qtbot):
    # Not the wait — a black screen saying "Generating…" is nothing to watch —
    # but the first iterations coming in, which are what the show is being
    # watched for in the first place.
    view = _view(qtbot, [("a.png", "image", "id-a")])

    view.note_generating("id-run", _png_bytes())

    assert len(view._playlist) == 2
    assert view._playlist.current()[2] == "id-a"      # the slide on screen is left alone
    assert view._playlist.peek(1)[1] == LIVE
    assert view.holds("id-run")


def test_a_live_slide_shows_the_newest_frame_while_it_is_on_screen(qtbot):
    view = _view(qtbot, [("a.png", "image", "id-a")])
    view.note_generating("id-run", _png_bytes())
    _press(view, Qt.Key.Key_Right)                    # step onto it

    later = _png_bytes()
    view.note_generating("id-run", later)

    newest = QPixmap()
    newest.loadFromData(later)
    assert view._pane._frame.toImage() == newest.toImage()


def test_a_live_slide_becomes_the_file_when_the_run_lands(qtbot, tmp_path):
    # The same slide, finished — not a second one beside the frames it arrived as.
    landed = _png(tmp_path / "landed.png")
    view = _view(qtbot, [(_png(tmp_path / "a.png"), "image", "id-a")])
    view.note_generating("id-run", _png_bytes())
    _press(view, Qt.Key.Key_Right)

    view.note_added(landed, "image", "id-run", None)

    assert len(view._playlist) == 2
    assert view._playlist.current() == (landed, "image", "id-run", None)
    assert view._pane._media[0] == landed


def test_a_run_that_was_cancelled_leaves_the_show(qtbot, tmp_path):
    # No file is coming, so the half-rendered frame it got to would otherwise
    # hold a place in the pass forever.
    view = _view(qtbot, [(_png(tmp_path / "a.png"), "image", "id-a")])
    view.note_generating("id-run", _png_bytes())

    view.note_in_flight(set())

    assert len(view._playlist) == 1
    assert not view.holds("id-run")


def test_a_run_still_going_keeps_its_slide(qtbot):
    view = _view(qtbot, [("a.png", "image", "id-a")])
    view.note_generating("id-run", _png_bytes())

    view.note_in_flight({"id-run"})

    assert view.holds("id-run")


def test_culling_a_slide_being_made_calls_nothing_off(qtbot, tmp_path):
    # The run is on the GPU and its row is a record of that, not a picture that
    # has been judged. Up takes it off the show and leaves the run alone.
    condemned = []
    view = _view(qtbot, [(_png(tmp_path / "a.png"), "image", "id-a")],
                 actions=ShowActions(delete=condemned.append))
    view.note_generating("id-run", _png_bytes())
    _press(view, Qt.Key.Key_Right)

    _press(view, Qt.Key.Key_Up)

    assert condemned == []
    assert not view.holds("id-run")


def test_a_culled_run_does_not_come_back_on_its_next_frame(qtbot, tmp_path):
    # Offered once, or Up over it would mean nothing at all.
    view = _view(qtbot, [(_png(tmp_path / "a.png"), "image", "id-a")])
    view.note_generating("id-run", _png_bytes())
    _press(view, Qt.Key.Key_Right)
    _press(view, Qt.Key.Key_Up)

    view.note_generating("id-run", _png_bytes())

    assert not view.holds("id-run")


def test_holding_a_slide_being_made_asks_for_no_enhancement(qtbot, tmp_path):
    # There is no file yet to make a better version of; the hold still holds.
    asked = []
    view = _view(qtbot, [(_png(tmp_path / "a.png"), "image", "id-a")],
                 actions=ShowActions(enhance=lambda pid: asked.append(pid) or True))
    view.note_generating("id-run", _png_bytes())
    _press(view, Qt.Key.Key_Right)

    _press(view, Qt.Key.Key_Down)

    assert asked == []
    assert view._playlist.locked


def test_a_show_following_one_run_full_screen_takes_no_live_slides(qtbot):
    # It is already showing that generation; a slide of it would be it twice.
    view = _view(qtbot, [], frame=_png_bytes())

    view.note_generating("id-run", _png_bytes())

    assert view._playlist.is_empty()


def test_a_slide_still_being_made_says_so(qtbot, tmp_path):
    # An early iteration looks exactly like a bad generation, so the corner says
    # which it is — the same corner an enhancement in flight speaks from.
    view = _view(qtbot, [(_png(tmp_path / "a.png"), "image", "id-a")])
    view.note_generating("id-run", _png_bytes())

    _press(view, Qt.Key.Key_Right)

    assert view._note.text() == "Generating…"
    assert not view._note.isHidden()


def test_the_order_pair_asks_the_gallery_for_the_side_in_that_order(qtbot):
    asked = []
    view = _view(qtbot, on_reorder=lambda held, latest: asked.append((held, latest)))

    view.show_order(latest=True)
    view.show_order(latest=False)

    assert asked == [(view, True), (view, False)]


def test_a_reorder_puts_the_top_of_the_new_set_on_screen_and_lets_go(qtbot, tmp_path):
    view = _view(qtbot, _named(tmp_path, "a", "b", "c"))
    view.step(1)
    view.toggle_hold()

    view.reorder(_named(tmp_path, "e", "d"), latest=True)

    assert view._playlist.current()[2] == "e"
    assert view.locked is False
    assert view.hud_order_label == "Latest"


def test_a_configuration_rows_button_puts_it_up_and_loops_its_seeds(qtbot):
    """The other half of the column: its rows are gone to and looped, where an
    act's row narrows the show instead."""
    from origenerator.gui.show_map import MapNeighbors, MapRow

    a_configuration = Slide("c.png", "image", "id-c")
    around = lambda pid: MapNeighbors(  # noqa: E731
        column=(MapRow(a_configuration, "E629425B", configuration=True),)
        if pid == "id-a" else (),
        seeds=(Slide("d.png", "image", "id-d"),) if pid == "id-c" else ())
    view = _view(qtbot, _KEYED, actions=ShowActions(neighbors=around, acts=_acts))
    shown = _put_up(view)

    view.show_filter("e629425b")

    assert shown == ["id-c"]
    assert (view.hud_act_filter, view.hud_map().loop) == ("", "seed")
