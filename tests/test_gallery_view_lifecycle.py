from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication, QWidget

from origenerator.gui.gallery_view import GalleryView
from tests.gallery_view_support import FakeDB, _image


def _gallery(qtbot, db=None):
    view = GalleryView(db or FakeDB([_image("i1", "scene one", 50, 1)]))
    qtbot.addWidget(view)
    return view


def _press_escape_elsewhere(qtbot):
    elsewhere = QWidget()
    qtbot.addWidget(elsewhere)
    QApplication.sendEvent(elsewhere, QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))


def test_closing_a_gallery_that_was_never_shown_stops_its_poll(qtbot):
    view = _gallery(qtbot)
    assert view._poll_timer.isActive()

    view.close()

    assert not view._poll_timer.isActive()


def test_a_closed_gallery_stops_answering_the_rooms_keys(qtbot, monkeypatch):
    view = _gallery(qtbot)
    reached = []
    monkeypatch.setattr(view, "_handle_escape", lambda: bool(reached.append(True)))
    _press_escape_elsewhere(qtbot)
    assert reached

    view.close()
    reached.clear()
    _press_escape_elsewhere(qtbot)

    assert reached == []


def test_a_gallery_shown_after_a_close_takes_the_keys_back(qtbot, monkeypatch):
    view = _gallery(qtbot)
    view.close()

    view.show()
    reached = []
    monkeypatch.setattr(view, "_handle_escape", lambda: bool(reached.append(True)))
    _press_escape_elsewhere(qtbot)

    assert reached


def test_being_shown_again_over_an_unmoved_library_draws_nothing_afresh(qtbot, monkeypatch):
    """Windows answers a minimize with a hide and then a show."""
    view = _gallery(qtbot)
    view.refresh()
    drawn = []
    monkeypatch.setattr(view, "_rebuild", lambda rows, meta, **_: drawn.append(rows))

    view.show()

    assert drawn == []


def test_being_shown_again_draws_what_landed_while_it_was_away(qtbot, monkeypatch):
    db = FakeDB([_image("i1", "scene one", 50, 1)])
    view = _gallery(qtbot, db)
    view.refresh()
    drawn = []
    monkeypatch.setattr(view, "_rebuild", lambda rows, meta, **_: drawn.append(rows))
    db._rows.append(_image("i2", "scene two", 50, 2))

    view.show()

    assert drawn


def _reads_held_back(view):
    held = []
    view.off_thread = lambda work, done: held.append(done)
    return held


def test_a_tick_while_the_last_ones_reads_are_out_asks_for_nothing_more(qtbot):
    view = _gallery(qtbot)
    held = _reads_held_back(view)

    view._poll()
    view._poll()

    assert len(held) == 1


def test_a_tick_whose_answers_raise_leaves_the_next_tick_free_to_read(qtbot):
    view = _gallery(qtbot)
    held = _reads_held_back(view)
    view._poll()

    def raises():
        raise RuntimeError("made-up failure")

    view._enhance.put_what_is_locked_first = raises
    with pytest.raises(RuntimeError):
        held[0](None)
    view._poll()

    assert len(held) == 2


def test_a_listing_that_could_not_be_read_draws_nothing_and_leaves_the_next_tick_free(qtbot):
    view = _gallery(qtbot)
    view.refresh()
    drawn = view._drawn_version
    view.off_thread = lambda work, done: done(None)

    view._poll()

    assert view._drawn_version == drawn
    assert view._poll_inflight is False
