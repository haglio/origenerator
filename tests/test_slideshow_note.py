from __future__ import annotations

from funestra.testing import FakeEngine
from shared_ui.colors import RED, TEXT_PRIMARY, YELLOW

from origenerator.gui.message import ERROR, WARNING
from origenerator.gui.slideshow_view import SlideshowView, ViewShow, ViewWiring
from tests.gallery_view_support import _requesting_view
from tests.marked_words import words

_ITEMS = [("one.png", "image"), ("two.png", "image")]

_WORKING = "working out “no hat”…"
_ALSO_WORKING = "working out “no beard”…"

_ASKED = object()
_ASKED_AGAIN = object()


def _view(qtbot):
    view = SlideshowView(_ITEMS, ViewShow(shuffle=lambda order: None), ViewWiring(engine=FakeEngine()))
    qtbot.addWidget(view)
    return view


def _mid_request(qtbot, tmp_path, monkeypatch, *, showing=True):
    view = _requesting_view(qtbot, tmp_path, monkeypatch)
    monkeypatch.setattr(view._voice.requests, "ask", lambda *a, **kw: None)
    if not showing:
        view._slideshows.showing.close()
        view.select_generation("orig")
    view._voice.listener.speak("Request.")
    view._voice.listener.speak("no hat. Over.")
    return view


def _fade(view):
    view._note_timer.stop()
    view._refresh_note()


def _corner(view) -> str:
    return "" if view._note.isHidden() else words(view._note)


def test_the_message_up_while_a_request_is_being_said_does_not_fade(qtbot):
    view = _view(qtbot)
    view.flash("Locked")

    view.dictating("Request: no hat")
    view._note_timer.timeout.emit()

    assert "Request" in _corner(view), (
        "held rather than flashed: with no HUD up, this message is the only sign that the mic "
        "is taking a sentence")


def test_the_note_that_says_the_app_is_still_working_does_not_fade(qtbot):
    view = _view(qtbot)

    view.slideshow.note_request(_WORKING, _ASKED, working=True)

    assert _corner(view) == _WORKING
    assert not view._note_timer.isActive(), (
        "working out what a request changes can mean asking the model, which routinely takes "
        "longer than a flash lasts, and a note gone while the app still works reads as the "
        "request having been dropped")
    _fade(view)
    assert _corner(view) == _WORKING


def test_the_answer_takes_the_corner_back_and_fades_as_notes_do(qtbot):
    view = _view(qtbot)
    view.slideshow.note_request(_WORKING, _ASKED, working=True)

    view.slideshow.note_request("dropped “hat” — generating", _ASKED)

    assert "generating" in _corner(view)
    _fade(view)
    assert _corner(view) == ""


def test_an_answer_to_one_request_leaves_another_still_being_worked_out(qtbot):
    view = _view(qtbot)
    view.slideshow.note_request(_WORKING, _ASKED, working=True)
    view.slideshow.note_request(_ALSO_WORKING, _ASKED_AGAIN, working=True)

    view.slideshow.note_request("didn't catch what to change in “no hat”", _ASKED)

    assert "didn't catch" in _corner(view)
    _fade(view)
    assert _corner(view) == _ALSO_WORKING


def test_a_flash_while_the_work_goes_on_falls_back_to_the_work(qtbot):
    view = _view(qtbot)
    view.slideshow.note_request(_WORKING, _ASKED, working=True)

    view.slideshow.note_voice_command("heard: “no hat”")
    assert "heard" in _corner(view)
    _fade(view)

    assert _corner(view) == _WORKING


def test_a_line_keeps_its_color_and_the_corner_falls_back_to_white(qtbot):
    view = _view(qtbot)
    view.slideshow.note_request(_WORKING, _ASKED, working=True)

    view.slideshow.note_voice_command("nothing here is enhanced", kind=WARNING)
    assert YELLOW.name() in view._note.styleSheet()
    view.slideshow.note_voice_run(None, "couldn't launch the enhance — see the log", kind=ERROR)
    assert RED.name() in view._note.styleSheet()
    view.slideshow.note_request("didn't catch what to change in “no beard”", _ASKED_AGAIN,
                      kind=WARNING)
    assert YELLOW.name() in view._note.styleSheet()
    _fade(view)

    assert _corner(view) == _WORKING
    assert TEXT_PRIMARY.name() in view._note.styleSheet()


def test_the_app_says_it_is_working_for_as_long_as_it_is(qtbot, tmp_path, monkeypatch):
    window = _mid_request(qtbot, tmp_path, monkeypatch)._slideshows.showing.shown
    assert "working out" in _corner(window)

    _fade(window)

    assert "working out" in _corner(window)


def test_the_mic_going_on_hearing_does_not_empty_the_corner(qtbot, tmp_path, monkeypatch):
    view = _mid_request(qtbot, tmp_path, monkeypatch)
    window = view._slideshows.showing.shown

    view._voice.listener.heard.emit("something else entirely")

    assert "heard" in _corner(window)
    _fade(window)
    assert "working out" in _corner(window)


def test_the_pane_says_it_is_working_too_when_no_slideshow_is_up(qtbot, tmp_path,
                                                                 monkeypatch):
    view = _mid_request(qtbot, tmp_path, monkeypatch, showing=False)
    assert "working out" in words(view._voice.status)

    view._voice.listener.heard.emit("something else entirely")
    assert "heard" in words(view._voice.status)
    what_its_timer_does_when_it_fires = view._voice._revert
    what_its_timer_does_when_it_fires()

    assert "working out" in words(view._voice.status)
