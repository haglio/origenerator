"""DropSlot: a kind-gated drop target for a dragged gallery generation."""

from PyQt6.QtCore import Qt, QPoint, QPointF
from PyQt6.QtGui import QDropEvent, QDragEnterEvent

from origenerator.gui.drop_slot import DropSlot
from origenerator.gui.thumbnail_widget import generation_mime


def _slot(qtbot, accepts=lambda pid: True, preview=lambda pid: None, placeholder="Drop here"):
    slot = DropSlot(accepts=accepts, preview=preview, placeholder=placeholder)
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
