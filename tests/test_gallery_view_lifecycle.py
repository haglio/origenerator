from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QWidget

from origenerator.comfyui_api import ForeignQueue
from origenerator.comfyui_client import ComfyUIClient
from origenerator.gui.gallery_view import GalleryView
from tests.gallery_view_support import (
    FakeDB,
    _image,
    _reroll_client,
    _seeded_db,
    _select_first_leaf,
)


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
    monkeypatch.setattr(view, "_handle_escape", lambda _modifiers: bool(reached.append(True)))
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
    monkeypatch.setattr(view, "_handle_escape", lambda _modifiers: bool(reached.append(True)))
    _press_escape_elsewhere(qtbot)

    assert reached, (
        "the key filter dropped as the gallery closes has to go back on as it is shown, or a "
        "reopened gallery is one Delete and one Esc short of working")


def test_being_shown_again_over_an_unmoved_library_draws_nothing_afresh(qtbot, monkeypatch):
    """Windows answers a minimize with a hide and then a show."""
    view = _gallery(qtbot)
    view.refresh()
    drawn = []
    monkeypatch.setattr(view, "_rebuild", lambda rows, meta, **_: drawn.append(rows))

    view.show()

    assert drawn == [], (
        "drawing four thousand generations afresh is seconds of the one thread that also "
        "answers the session's commands")


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


def test_the_ticks_reads_are_handed_what_the_jobs_were_at_the_tick(qtbot, tmp_path):
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._start_reroll(key)
    (job,) = view._jobs.all_jobs
    reads = []
    view.off_thread = lambda work, done: reads.append(work)
    view._poll()

    view._cancel_job(job.prompt_id)
    assert job.state == "canceled"
    client.fetch_history.reset_mock()
    reads[0]()

    assert client.fetch_history.call_args_list == [call(job.prompt_id)], (
        "the tick's reads run off the window's thread, so they are handed the jobs' names and "
        "states as strings and touch nothing the window owns")


def test_a_tick_asks_comfyui_only_inside_the_read_it_hands_off(qtbot, tmp_path):
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    view._start_reroll(_select_first_leaf(view))
    comfyui = MagicMock(spec=ComfyUIClient)
    comfyui.fetch_history.return_value = {}
    comfyui.foreign_backlog.return_value = None
    comfyui.executing_prompts.return_value = []
    comfyui.foreign_queue.return_value = ForeignQueue(running=[], pending=[])
    view._client = view._jobs._client = comfyui
    for job in view._jobs.all_jobs:
        job._client = comfyui
    hops = []
    view.off_thread = lambda work, done: hops.append((work, done))
    asked = {"on the window's thread": [], "in the read handed off": []}

    def asked_since(where):
        asked[where] += [name for name, _args, _kwargs in comfyui.mock_calls]
        comfyui.reset_mock()

    view._poll()
    while hops:
        work, done = hops.pop(0)
        asked_since("on the window's thread")
        facts = work()
        asked_since("in the read handed off")
        done(facts)
    asked_since("on the window's thread")

    assert asked == {"on the window's thread": [], "in the read handed off": [
        "fetch_history", "foreign_backlog", "executing_prompts", "foreign_queue"]}, (
        "every read a poll tick makes of ComfyUI is in the one read it hands off the window's "
        "thread, so none of them blocks the window")


def test_a_listing_that_could_not_be_read_draws_nothing_and_leaves_the_next_tick_free(qtbot):
    view = _gallery(qtbot)
    view.refresh()
    drawn = view._drawn_version
    view.off_thread = lambda work, done: done(None)

    view._poll()

    assert view._drawn_version == drawn
    assert view._poll_inflight is False
