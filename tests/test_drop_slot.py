"""DropSlot: a kind-gated drop target for a dragged gallery generation."""

import pytest
from PIL import Image
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QMovie

from origenerator.gui.drop_slot import DropSlot
from origenerator.gui.generation_drag import generation_mime
from origenerator.gui.media_badge import MediaBadge


def _slot(qtbot, kind="image", accepts=lambda pid: True,
          preview=lambda pid: (None, None), placeholder="Drop here", grayscale=False):
    slot = DropSlot(kind=kind, accepts=accepts, preview=preview, placeholder=placeholder,
                    grayscale=grayscale)
    qtbot.addWidget(slot)
    return slot


def _drop(slot, pid):
    # Hold the QMimeData in a local: the event stores only a C++ pointer to it, so
    # a temporary would be GC'd before dropEvent reads it (a dangling-pointer crash).
    mime = generation_mime(pid)
    ev = QDropEvent(QPointF(1, 1), Qt.DropAction.CopyAction, mime,
                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    slot.dropEvent(ev)
    return ev


def _drag_enter(slot, pid):
    mime = generation_mime(pid)
    ev = QDragEnterEvent(QPoint(1, 1), Qt.DropAction.CopyAction, mime,
                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    slot.dragEnterEvent(ev)
    return ev


def _write_looping_webp(path, size=(64, 48)):
    frames = [Image.new("RGB", size, c) for c in ((255, 0, 0), (0, 255, 0))]
    frames[0].save(path, format="WEBP", save_all=True,
                   append_images=frames[1:], duration=100, loop=0)
    return str(path)


def test_dropping_an_allowed_id_fills_the_slot_and_notifies(qtbot):
    slot = _slot(qtbot, accepts=lambda pid: pid.startswith("img"))
    seen = []
    slot.changed.connect(lambda: seen.append(slot.current_id()))

    ev = _drop(slot, "img1")

    assert slot.current_id() == "img1"
    assert ev.isAccepted()
    assert seen == ["img1"]


def test_dropping_a_disallowed_id_is_ignored(qtbot):
    slot = _slot(qtbot, accepts=lambda pid: pid.startswith("img"))

    _drop(slot, "vid9")

    assert slot.current_id() is None  # the predicate rejected it


def test_drag_enter_accepts_only_allowed_ids(qtbot):
    slot = _slot(qtbot, accepts=lambda pid: pid.startswith("img"))

    assert _drag_enter(slot, "img1").isAccepted()
    assert not _drag_enter(slot, "vid1").isAccepted()


def test_clear_empties_the_slot_and_notifies(qtbot):
    slot = _slot(qtbot)
    _drop(slot, "img1")
    seen = []
    slot.changed.connect(lambda: seen.append(slot.current_id()))

    slot.clear()

    assert slot.current_id() is None
    assert seen == [None]


def test_clear_on_an_empty_slot_does_not_notify(qtbot):
    slot = _slot(qtbot)
    seen = []
    slot.changed.connect(lambda: seen.append(1))

    slot.clear()

    assert seen == []  # idempotent: nothing to clear, no spurious change


def test_a_video_preview_animates(qtbot, tmp_path):
    webp = _write_looping_webp(tmp_path / "v1_anim.webp")
    slot = _slot(qtbot, kind="video", preview=lambda pid: (None, webp))

    _drop(slot, "vid1")

    movie = slot._label.movie()
    assert isinstance(movie, QMovie)
    assert movie.state() == QMovie.MovieState.Running  # looping, not a still


def test_a_grayscale_slot_drains_the_clip_it_holds(qtbot, tmp_path):
    # The video slot holds a recipe, not a result: in color it reads as a second
    # subject beside the image it will animate.
    webp = _write_looping_webp(tmp_path / "v1_anim.webp")
    slot = _slot(qtbot, kind="video", preview=lambda pid: (None, webp), grayscale=True)

    _drop(slot, "vid1")

    assert slot._label.movie() is None  # frames come across as pixmaps, drained
    color = slot._label.pixmap().toImage().pixelColor(2, 2)
    assert color.red() == color.green() == color.blue()
    assert slot._movie.state() == QMovie.MovieState.Running  # still looping


def test_a_grayscale_slot_drains_a_still_too(qtbot, tmp_path):
    # An i2v video with no animated preview shows its stored frame; it is held
    # for the same reason and reads the same way.
    still = tmp_path / "thumb.png"
    Image.new("RGB", (40, 30), (200, 30, 30)).save(still)
    slot = _slot(qtbot, kind="video", preview=lambda pid: (str(still), None),
                 grayscale=True)

    _drop(slot, "vid1")

    color = slot._label.pixmap().toImage().pixelColor(2, 2)
    assert color.red() == color.green() == color.blue()


def test_an_ordinary_slot_keeps_its_color(qtbot, tmp_path):
    still = tmp_path / "thumb.png"
    Image.new("RGB", (40, 30), (200, 30, 30)).save(still)
    slot = _slot(qtbot, preview=lambda pid: (str(still), None))

    _drop(slot, "img1")

    assert slot._label.pixmap().toImage().pixelColor(2, 2).red() > 150


def test_set_placeholder_updates_the_empty_prompt_live(qtbot):
    slot = _slot(qtbot, placeholder="Drop here")
    assert slot._label.text() == "Drop here"

    slot.set_placeholder("use custom action from video")

    assert slot._label.text() == "use custom action from video"


def test_set_placeholder_leaves_a_held_item_untouched(qtbot):
    slot = _slot(qtbot)
    _drop(slot, "img1")  # preview is (None, None): the held state shows a check, not a prompt

    slot.set_placeholder("something else")

    assert slot.current_id() == "img1"          # still held
    assert slot._label.text() != "something else"  # the new prompt only applies once empty


def test_set_candidate_lights_and_clears_the_slot(qtbot):
    slot = _slot(qtbot)

    slot.set_candidate(True)
    assert slot._label.property("dragActive") is True   # the drop zone stands out

    slot.set_candidate(False)
    assert slot._label.property("dragActive") is False  # cleared when the drag ends


def test_accepts_delegates_to_the_predicate(qtbot):
    slot = _slot(qtbot, accepts=lambda pid: pid.startswith("img"))

    assert slot.accepts("img1") is True
    assert slot.accepts("vid1") is False


@pytest.mark.parametrize("kind", ["image", "video"])
def test_the_kind_badge_appears_only_once_filled(qtbot, kind):
    slot = _slot(qtbot, kind=kind)
    badge = slot.findChild(MediaBadge)
    assert badge.media_type == kind      # an image/video chip, so you know what goes here
    assert badge.isHidden()              # nothing dropped yet (isHidden works offscreen)

    _drop(slot, "x1")
    assert not badge.isHidden()

    slot.clear()
    assert badge.isHidden()              # back to a bare drop zone
