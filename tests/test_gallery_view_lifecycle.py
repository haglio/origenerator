"""What a GalleryView stops doing when it is closed.

The view arms two things application-wide in its constructor — a 1.5 s poll of
the database and the ComfyUI queue, and an event filter on the QApplication —
and both used to outlive a ``close()``.  Only ``hideEvent`` put either down, and
a widget that was never shown is never hidden, so a closed gallery went on
polling and went on answering the room's keys until the garbage collector got
round to it.
"""

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication, QWidget

from origenerator.gui.gallery_view import GalleryView
from tests.test_gallery_view import FakeDB, _image


def _gallery(qtbot):
    view = GalleryView(FakeDB([_image("i1", "scene one", 50, 1)]))
    qtbot.addWidget(view)
    return view


def _press_escape_elsewhere(qtbot):
    """A key press delivered to a widget that is not the gallery — what an
    application-wide filter sees and a widget's own handler never does."""
    elsewhere = QWidget()
    qtbot.addWidget(elsewhere)
    QApplication.sendEvent(elsewhere, QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))


def test_closing_a_gallery_that_was_never_shown_stops_its_poll(qtbot):
    """The poll does blocking HTTP and a whole-table SELECT every 1.5 s, so one
    left running behind a closed view is work nobody is looking at."""
    view = _gallery(qtbot)
    assert view._poll_timer.isActive()

    view.close()

    assert not view._poll_timer.isActive()


def test_a_closed_gallery_stops_answering_the_rooms_keys(qtbot, monkeypatch):
    """Esc is a panic-stop the filter answers from anywhere, visible or not — so
    a closed gallery still holding the filter would stop (or start) the whole
    room on a key pressed at some other window entirely."""
    view = _gallery(qtbot)
    reached = []
    monkeypatch.setattr(view, "_handle_escape", lambda: bool(reached.append(True)))
    _press_escape_elsewhere(qtbot)
    assert reached  # the filter is on the application while the view is open

    view.close()
    reached.clear()
    _press_escape_elsewhere(qtbot)

    assert reached == []


def test_a_gallery_shown_after_a_close_takes_the_keys_back(qtbot, monkeypatch):
    """Dropping the filter on the way out has to be matched on the way back in,
    or a reopened gallery would be one Delete and one Esc short of working."""
    view = _gallery(qtbot)
    view.close()

    view.show()
    reached = []
    monkeypatch.setattr(view, "_handle_escape", lambda: bool(reached.append(True)))
    _press_escape_elsewhere(qtbot)

    assert reached
