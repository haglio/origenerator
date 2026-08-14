"""SlideshowView — the fullscreen player: show, advance, lock, neighbors, keys."""

from unittest.mock import MagicMock

from PIL import Image
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QKeyEvent

from origenerator.gui.slideshow_view import SlideshowView
from origenerator.stroke_engine import Stroke

_ITEMS = [("a.png", "image"), ("b.mp4", "video"), ("c.png", "image")]


def _png(path):
    Image.new("RGB", (16, 16), (20, 80, 160)).save(path, "PNG")
    return str(path)


def _view(qtbot, items=_ITEMS, **kw):
    kw.setdefault("shuffle", lambda order: None)  # deterministic order for these tests
    view = SlideshowView(items, player=MagicMock(), **kw)
    qtbot.addWidget(view)
    return view


def _press(view, key):
    view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


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
    # matching the auto-generate slideshow and Fun Time's next/prev.
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
    assert not view._note.isHidden() and "Enhancing" in view._note.text()


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


def test_double_clicking_leaves_the_slideshow(qtbot):
    # The way out of every other fullscreen view here, and the way it used to work.
    view = _view(qtbot)
    view.show()
    closed = []
    view.closed = closed  # a marker; the real signal is the window closing
    view._preview._on_double_click()
    assert not view.isVisible()


# --- an item still being made ------------------------------------------------

def test_an_item_with_no_file_yet_says_it_is_being_made(qtbot):
    view = _view(qtbot, items=[(None, "image", "gen-live", None)])
    assert view._playlist.current()[2] == "gen-live"
    assert view._preview.is_showing_video() is False


def test_a_streamed_frame_lands_on_the_item_being_made(qtbot, tmp_path):
    from PIL import Image
    from io import BytesIO

    buffer = BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buffer, "PNG")
    view = _view(qtbot, items=[(None, "image", "gen-live", None)])

    view.show_live_frame("gen-live", buffer.getvalue())

    assert view._preview._live_frame == buffer.getvalue()


def test_a_frame_for_something_else_is_kept_but_not_shown(qtbot):
    # It rides along for when the rotation reaches that item, without disturbing
    # the one on screen.
    view = _view(qtbot, items=[("a.png", "image", "gen-a", None),
                               (None, "image", "gen-live", None)])

    view.show_live_frame("gen-live", b"not-a-real-png")

    assert view._frames["gen-live"] == b"not-a-real-png"
