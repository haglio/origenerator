"""DropSlot: a kind-gated drop target for a dragged gallery generation."""

from PIL import Image
from PyQt6.QtCore import Qt, QPoint, QPointF
from PyQt6.QtGui import QDropEvent, QDragEnterEvent, QMovie

from origenerator.gui.drop_slot import DropSlot
from origenerator.gui.media_badge import MediaBadge
from origenerator.gui.thumbnail_widget import generation_mime


def _slot(qtbot, kind="image", accepts=lambda pid: True,
          preview=lambda pid: (None, None), placeholder="Drop here"):
    slot = DropSlot(kind=kind, accepts=accepts, preview=preview, placeholder=placeholder)
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


def test_the_kind_badge_appears_only_once_filled(qtbot):
    slot = _slot(qtbot, kind="video")
    badge = slot.findChild(MediaBadge)
    assert badge.media_type == "video"   # the slot's kind, so you know what to drop here
    assert badge.isHidden()              # nothing dropped yet (isHidden works offscreen)

    _drop(slot, "vid1")
    assert not badge.isHidden()

    slot.clear()
    assert badge.isHidden()              # back to a bare drop zone
