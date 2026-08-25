"""The corner note while a spoken request is still being worked out.

Working out what a request changes can mean asking the local LLM which of the
prompt's own terms the speaker meant — which is what that path is for, and it
routinely takes longer than a flash lasts.  Flashed, the note said the app was
working and then left the corner blank while it still was, which in a view with
no panels is indistinguishable from the request having been dropped.
"""

from unittest.mock import MagicMock

from PyQt6.QtCore import QRunnable

from origenerator.gui import gallery_view
from origenerator.gui.slideshow_view import SlideshowView

from tests.test_gallery_view import _requesting_view

_ITEMS = [("one.png", "image"), ("two.png", "image")]

_WORKING = "🎤 working out “no hat”…"


def _view(qtbot):
    view = SlideshowView(_ITEMS, player=MagicMock(), shuffle=lambda order: None)
    qtbot.addWidget(view)
    return view


class _NeverAnswers(QRunnable):
    """A revision handed to the pool that never comes back — the app left in the
    state it is in for as long as the working-out takes."""

    def run(self):
        pass


def _mid_request(qtbot, tmp_path, monkeypatch):
    """A gallery whose slideshow has just been asked for a change, with the
    working-out still going on."""
    monkeypatch.setattr(gallery_view, "ReviseTask", lambda *a, **kw: _NeverAnswers())
    view = _requesting_view(qtbot, tmp_path, monkeypatch)
    view._voice.speak("Request.")
    view._voice.speak("no hat. Over.")
    return view


def _fade(view):
    """What a flash's own timer does when it fires: a single shot, so it is no
    longer running by the time the corner falls back to whatever it should say."""
    view._note_timer.stop()
    view._refresh_note()


def _corner(view) -> str:
    """What the corner actually reads.  A note with nothing to say is hidden
    rather than emptied, and the toast keeps its last line behind that — so
    ``text()`` alone would read a blank corner as still saying the old thing."""
    return "" if view._note.isHidden() else view._note.text()


def test_the_note_that_says_the_app_is_still_working_does_not_fade(qtbot):
    view = _view(qtbot)

    view.note_request(_WORKING, working=True)

    assert _corner(view) == _WORKING
    assert not view._note_timer.isActive()  # nothing counting down to a blank corner
    _fade(view)
    assert _corner(view) == _WORKING


def test_the_answer_takes_the_corner_back_and_fades_as_notes_do(qtbot):
    view = _view(qtbot)
    view.note_request(_WORKING, working=True)

    view.note_request("🎤 dropped “hat” — generating")

    assert "generating" in _corner(view)
    _fade(view)
    assert _corner(view) == ""  # nothing else to say about this slide


def test_a_flash_while_the_work_goes_on_falls_back_to_the_work(qtbot):
    """The mic keeps saying what it hears while the request is being worked out.
    Those are still flashes — and the corner comes back to the work, not to
    nothing, which is the same defect one utterance smaller."""
    view = _view(qtbot)
    view.note_request(_WORKING, working=True)

    view.note_voice_command("🎤 heard: “no hat”")
    assert "heard" in _corner(view)
    _fade(view)

    assert _corner(view) == _WORKING


def test_the_app_says_it_is_working_for_as_long_as_it_is(qtbot, tmp_path, monkeypatch):
    show = _mid_request(qtbot, tmp_path, monkeypatch)._slideshow
    assert "working out" in _corner(show)

    _fade(show)

    assert "working out" in _corner(show)


def test_the_mic_going_on_hearing_does_not_empty_the_corner(qtbot, tmp_path, monkeypatch):
    """Whisper keeps transcribing while the request is worked out, and the app
    says what it heard. That line is a flash; the work behind it is not."""
    view = _mid_request(qtbot, tmp_path, monkeypatch)
    show = view._slideshow

    view._voice.heard.emit("something else entirely")

    assert "heard" in _corner(show)
    _fade(show)
    assert "working out" in _corner(show)
