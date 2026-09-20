from __future__ import annotations

import time

import pytest
from PyQt6.QtCore import QObject
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtTest import QSignalSpy

from origenerator.gui.ken_burns_still import KenBurnsStill
from origenerator.ken_burns import ZOOM_SPAN


def _picture():
    image = QImage(400, 300, QImage.Format.Format_RGB32)
    image.fill(QColor(0, 0, 200))
    return image


def _bordered_picture():
    """Blue inside a thin red border: the border is the first thing a push throws
    away, so a corner pixel says whether the picture is drawn part-way in."""
    image = QImage(400, 300, QImage.Format.Format_RGB32)
    image.fill(QColor(200, 0, 0))
    painter = QPainter(image)
    painter.fillRect(4, 3, 392, 294, QColor(0, 0, 200))
    painter.end()
    return image


def _shown_still(qtbot, width, height):
    still = KenBurnsStill()
    qtbot.addWidget(still)
    still.resize(width, height)
    still.show()
    qtbot.waitExposed(still)
    return still


def test_the_push_keeps_drawing_while_the_window_is_busy(qtbot):
    still = _shown_still(qtbot, 200, 150)
    # Counted by a spy rather than a Python slot: the frames are swapped on the
    # render thread, and Python code there waits on the lock this thread holds.
    swaps = QSignalSpy(still._view.frameSwapped)
    still.show_picture(_picture())
    still.start(dwell_ms=4000, progress=0.0)
    qtbot.wait(200)
    before = len(swaps)

    time.sleep(1.0)

    assert len(swaps) - before >= 5


def test_a_released_still_draws_nothing_more(qtbot):
    """What makes a still safe to take apart: nothing is being drawn for it.

    Taking a shown Qt Quick scene down is a round trip with the render thread
    drawing it, and reached from a destructor -- a parent widget going away, a
    suite reaping what a test built -- the window's thread has no event loop
    left to answer that thread with, so the two wait on each other for good.
    A released still has stopped asking for frames and let its scene go, so
    whatever takes the widget apart afterwards finds nothing to wait for.
    """
    still = _shown_still(qtbot, 200, 150)
    still.show_picture(_picture())
    still.start(dwell_ms=4000, progress=0.0)
    qtbot.wait(200)
    swaps = QSignalSpy(still._view.frameSwapped)

    still.release()

    drawn = len(swaps)
    time.sleep(0.5)
    assert len(swaps) == drawn


def test_a_push_started_part_way_begins_that_far_into_the_picture(qtbot):
    still = _shown_still(qtbot, 400, 300)
    still.show_picture(_bordered_picture())

    still.start(dwell_ms=100_000_000, progress=0.5)
    qtbot.wait(200)

    corner = still._view.grabWindow().pixelColor(1, 1)
    assert corner.blue() > 150 and corner.red() < 50


def _striped_picture():
    image = QImage(400, 300, QImage.Format.Format_RGB32)
    image.fill(QColor(200, 0, 0))
    painter = QPainter(image)
    for x in range(0, 400, 8):
        painter.fillRect(x, 0, 4, 300, QColor(0, 0, 200))
    painter.end()
    return image


def test_a_paused_push_holds_still_until_it_is_resumed(qtbot):
    still = _shown_still(qtbot, 400, 300)
    still.show_picture(_striped_picture())
    still.start(dwell_ms=1000, progress=0.0)
    qtbot.wait(200)

    still.pause()
    qtbot.wait(150)
    held = still._view.grabWindow()
    qtbot.wait(300)
    assert still._view.grabWindow() == held

    still.resume()
    qtbot.wait(300)
    assert still._view.grabWindow() != held


def test_a_new_pace_carries_the_push_on_from_the_depth_it_had_reached(qtbot):
    still = _shown_still(qtbot, 400, 300)
    still.show_picture(_bordered_picture())
    still.start(dwell_ms=100_000, progress=0.5)
    qtbot.wait(150)

    still.retime(dwell_ms=100_000_000)
    qtbot.wait(150)

    corner = still._view.grabWindow().pixelColor(1, 1)
    assert corner.blue() > 150 and corner.red() < 50


def test_a_stopped_push_goes_back_to_the_whole_picture(qtbot):
    still = _shown_still(qtbot, 400, 300)
    still.show_picture(_bordered_picture())
    still.start(dwell_ms=100_000, progress=0.5)
    qtbot.wait(150)

    still.stop()
    qtbot.wait(150)

    corner = still._view.grabWindow().pixelColor(1, 1)
    assert corner.red() > 150 and corner.blue() < 50


@pytest.mark.parametrize("dwell_ms", [4000, 12000])
def test_every_pace_ends_its_move_the_same_depth_in(qtbot, dwell_ms):
    # A longer pace is a slower move over the same ground, never a longer one:
    # travelling further would end on a crop of the picture.
    still = _shown_still(qtbot, 200, 150)
    still.show_picture(_picture())

    still.start(dwell_ms=dwell_ms, progress=0.0)

    whole_moves = still._scene.findChild(QObject, "wholeMoves")
    assert whole_moves.property("to") == pytest.approx(ZOOM_SPAN)
    assert whole_moves.property("duration") == dwell_ms


def test_a_new_picture_keeps_the_push_it_arrived_under(qtbot):
    # Another version of the picture on screen swaps in part-way through a push,
    # and carries on from that depth rather than starting over.
    still = _shown_still(qtbot, 400, 300)
    still.show_picture(_bordered_picture())
    still.start(dwell_ms=100_000_000, progress=0.5)
    qtbot.wait(150)

    still.show_picture(_bordered_picture())
    qtbot.wait(150)

    corner = still._view.grabWindow().pixelColor(1, 1)
    assert corner.blue() > 150 and corner.red() < 50
