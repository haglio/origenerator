"""What a GalleryView stops doing when it is closed.

The view arms two things application-wide in its constructor — a 1.5 s poll of
the database and the ComfyUI queue, and an event filter on the QApplication —
and both used to outlive a ``close()``.  Only ``hideEvent`` put either down, and
a widget that was never shown is never hidden, so a closed gallery went on
polling and went on answering the room's keys until the garbage collector got
round to it.
"""

from origenerator.gui.gallery_view import GalleryView

from tests.test_gallery_view import FakeDB, _image


def _gallery(qtbot):
    view = GalleryView(FakeDB([_image("i1", "scene one", 50, 1)]))
    qtbot.addWidget(view)
    return view


def test_closing_a_gallery_that_was_never_shown_stops_its_poll(qtbot):
    """The poll does blocking HTTP and a whole-table SELECT every 1.5 s, so one
    left running behind a closed view is work nobody is looking at."""
    view = _gallery(qtbot)
    assert view._poll_timer.isActive()

    view.close()

    assert not view._poll_timer.isActive()
