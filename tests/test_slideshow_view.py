"""SlideshowView — the fullscreen player: show, advance, pause, neighbors, keys."""

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


def test_pausing_stops_a_finished_video_from_advancing(qtbot):
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Right)          # -> the video
    _press(view, Qt.Key.Key_Down)           # hold
    view._preview.video_ended.emit()
    assert view._playlist.current() == ("b.mp4", "video")  # stayed put
    assert view._playlist.paused


def test_down_toggles_pause_and_the_caption_reflects_it(qtbot):
    view = _view(qtbot)
    _press(view, Qt.Key.Key_Down)
    assert view._playlist.paused
    assert "paused" in view._counter.text()
    _press(view, Qt.Key.Key_Down)
    assert not view._playlist.paused
    assert "paused" not in view._counter.text()


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


def test_space_drives_the_shared_stroke_not_the_pause(qtbot):
    # Space belongs to the app-global OSR2 stroke everywhere; holding the
    # slideshow is Down. The standing caption comes with the wired stroke.
    stroke = _FakeStroke()
    view = SlideshowView(_ITEMS, player=MagicMock(), shuffle=lambda order: None,
                         stroke=stroke)
    qtbot.addWidget(view)
    assert view._stroke_panel is not None  # the drive panel rides along
    _press(view, Qt.Key.Key_Space)
    assert ("toggle", True) in stroke.calls
    assert not view._playlist.paused


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
    assert view._playlist.paused


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
