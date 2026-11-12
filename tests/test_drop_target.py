from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent
from PyQt6.QtWidgets import QApplication, QWidget

from origenerator.gui.drags import under_way
from origenerator.gui.drop_style import AIMED, EDGE, LIT
from origenerator.gui.drop_target import DropTarget
from origenerator.gui.gallery_pane import GalleryPaneScrollArea
from origenerator.gui.generation_drag import generation_mime
from origenerator.gui.stylesheet import build_stylesheet
from tests.drop_style_seen import worn


def _pane(qtbot, landing=lambda _mime, _source: ("taken",)):
    """Qt sends every later drag event to the last widget that took one, so a held drag is let go of before the pane closes."""
    pane = GalleryPaneScrollArea()
    pane.setWidgetResizable(True)
    pane.setWidget(QWidget())
    pane.setStyleSheet(build_stylesheet())
    DropTarget(pane, landing, lambda *_landing: None)
    qtbot.addWidget(pane, before_close_func=lambda held: QApplication.sendEvent(
        held.viewport(), QDragLeaveEvent()))
    pane.resize(300, 200)
    with qtbot.waitExposed(pane):
        pane.show()
    return pane


def _style_worn(pane):
    return worn(pane.grab().toImage(), pane.rect())


def test_a_pane_lights_while_a_drag_it_would_take_is_under_way(qtbot):
    pane = _pane(qtbot)
    assert _style_worn(pane) is None

    under_way.started.emit(generation_mime("p1"), None)

    assert _style_worn(pane) == LIT


def _hold_over(pane, mime):
    held = (pane.viewport().rect().center(), Qt.DropAction.CopyAction, mime,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    for event in (QDragEnterEvent(*held), QDragMoveEvent(*held)):
        QApplication.sendEvent(pane.viewport(), event)


def test_the_pane_under_the_drag_lights_one_step_lighter(qtbot):
    pane = _pane(qtbot)
    mime = generation_mime("p1")
    under_way.started.emit(mime, None)

    _hold_over(pane, mime)

    assert _style_worn(pane) == AIMED


def test_a_drag_leaving_the_pane_leaves_it_only_lit(qtbot):
    pane = _pane(qtbot)
    mime = generation_mime("p1")
    under_way.started.emit(mime, None)
    _hold_over(pane, mime)

    QApplication.sendEvent(pane.viewport(), QDragLeaveEvent())

    assert _style_worn(pane) == LIT


def test_a_drag_ending_over_the_pane_leaves_it_dark(qtbot):
    pane = _pane(qtbot)
    mime = generation_mime("p1")
    under_way.started.emit(mime, None)
    _hold_over(pane, mime)

    under_way.ended.emit()

    assert _style_worn(pane) is None


def test_a_pane_that_would_turn_the_drag_away_stays_as_it_is(qtbot):
    pane = _pane(qtbot, landing=lambda _mime, _source: None)
    mime = generation_mime("p1")

    under_way.started.emit(mime, None)
    _hold_over(pane, mime)

    assert _style_worn(pane) is None


def test_the_edge_is_drawn_over_what_the_zone_comes_to_hold(qtbot):
    zone = QWidget()
    DropTarget(zone, lambda _mime, _source: ("taken",), lambda *_landing: None)
    qtbot.addWidget(zone)
    zone.resize(300, 200)
    held = QWidget(zone)
    held.setStyleSheet("background-color: #c03030;")
    held.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    held.setGeometry(zone.rect())
    with qtbot.waitExposed(zone):
        zone.show()

    under_way.started.emit(generation_mime("p1"), None)

    image = zone.grab().toImage()
    middle = zone.rect().center()
    assert image.pixelColor(middle.x(), 0).name() == EDGE.name(), (
        "the edge is drawn over everything the zone holds, which would otherwise hide it")
