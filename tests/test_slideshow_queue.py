"""The bottom strip's queue, floated into the fullscreen show's corner.

It is :class:`GenerationQueue` itself — the live frame, the bar, the rows with
their buttons and their drag — so what it *says* is covered by
``test_generation_queue``. What is tested here is the difference between a docked
pane and a floating plate: where it sits, that it leaves the screen when there is
nothing in flight, that it brings its own background, and that pressing anything
in it doesn't take the arrows away from the slides.
"""

import pytest
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtWidgets import QPushButton, QWidget

from origenerator.gui.generation_queue import QueueRow
from origenerator.gui.inflight import InFlightItem
from origenerator.gui.slideshow_queue import MARGIN, ROWS, SlideshowQueue


def _item(key="j1", status="running", **kw):
    kw.setdefault("caption", "Alpha Workflow › a paper kite")
    kw.setdefault("frame", None)
    kw.setdefault("reveal", lambda: None)
    kw.setdefault("cancel", lambda: None)
    return InFlightItem(key=key, status=status, **kw)


@pytest.fixture
def plate(qtbot):
    """The float on a screen-sized host. Yielded rather than returned so the host
    stays referenced for the test — the plate is its child, and a collected host
    takes the plate down with it."""
    host = QWidget()
    host.resize(1920, 1080)
    qtbot.addWidget(host)
    yield SlideshowQueue(host)


def test_it_is_the_strip_itself_rows_buttons_and_all(plate):
    # Not a summary of the queue: the widget, with the running job driving its
    # live half and every waiting job carrying its own row.
    plate.set_items([_item("running-one", typical_seconds=30, job_kind="Image"),
                     _item("waiting-one", status="queued", typical_seconds=600,
                           job_kind="T2V", held=True)])

    assert plate.keys() == ["running-one", "waiting-one"]
    assert plate._running.key == "running-one"
    assert plate.rows()[1].lead() == "~10 min · T2V"
    assert plate.rows()[1].note() == "Held until the slideshow closes"
    assert plate.rows()[1].findChild(QPushButton) is not None  # its Cancel


def test_it_leaves_the_screen_with_nothing_in_flight(plate):
    plate.set_items([_item(typical_seconds=30)])
    plate.reposition()
    assert not plate.isHidden()

    plate.set_items([])
    assert plate.isHidden()  # a plate over a picture has no slot to hold


def test_another_apps_backlog_alone_is_worth_showing(plate):
    # Nothing of ours running, but ComfyUI is busy for someone else — the same
    # thing the docked strip stays up to report, and its Clear with it.
    plate.set_items([], foreign_queued=3)
    assert not plate.isHidden()


def test_it_sits_in_the_bottom_left_corner(plate):
    host = plate.parentWidget()
    plate.set_items([_item(typical_seconds=30)])
    plate.reposition()

    assert plate.x() == MARGIN
    assert plate.y() + plate.height() == host.height() - MARGIN
    assert plate.width() < host.width() // 2  # a corner, not a strip across


def test_it_opens_taller_than_the_docked_strip(plate):
    # The main window's answer to wanting more rows is a drag of the splitter
    # above it, and there is nowhere to make that gesture here.
    plate.set_items([_item(typical_seconds=30)])
    plate.reposition()
    assert plate.height() == ROWS * QueueRow.HEIGHT


def test_it_gives_up_width_rather_than_move_off_the_corner(plate):
    # The position counter owns the middle of the same edge.
    host = plate.parentWidget()
    plate.set_items([_item(typical_seconds=30)])

    plate.reposition()
    full = plate.width()
    counter = QRect(200, host.height() - 44, 92, 20)
    plate.reposition(avoid=counter)

    assert plate.x() == MARGIN                            # still the corner's
    assert plate.y() + plate.height() == host.height() - MARGIN
    assert plate.width() < full                           # width is what gave
    assert plate.geometry().right() < counter.left()


def test_a_counter_clear_of_the_plate_costs_it_no_width(plate):
    host = plate.parentWidget()
    plate.set_items([_item(typical_seconds=30)])
    plate.reposition()
    full = plate.width()

    plate.reposition(avoid=QRect(900, 0, 92, 20))  # up at the top, out of the way
    assert plate.width() == full


def test_nothing_in_it_takes_the_keyboard(plate):
    """A press that stole focus would leave the arrows no longer stepping the
    slides, with nothing on screen to say why."""
    plate.set_items([_item("running-one", typical_seconds=30),
                     _item("waiting-one", status="queued", typical_seconds=30)])

    assert plate.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert all(child.focusPolicy() == Qt.FocusPolicy.NoFocus
               for child in plate.findChildren(QWidget))


def test_it_brings_its_own_background(plate):
    """Docked, the strip is transparent and takes the pane's surface behind it;
    floated over a picture that would be rows of text lying on the media."""
    assert plate.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    assert "background-color" in plate.styleSheet()
    # And native, or it cannot paint over a video's own native surface.
    assert plate.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)
